"""A to-do list per family member: Jar's household tasks for that person.

Ticking an item ticks the task in Jar for that person (their coins, their part of an "each of them" task);
unticking undoes it. A new item becomes a Jar task for that person. Titles are changed in the Jar app.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import JarConfigEntry
from .api import JarError
from .const import DOMAIN
from .coordinator import JarCoordinator, owners

KEEP_DONE = timedelta(hours=18)     # ticked tasks stay visible (crossed out) for the rest of the day


async def async_setup_entry(hass: HomeAssistant, entry: JarConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities([JarTodo(coord, p) for p in coord.data.family]
                       + [JarShopping(coord, p) for p in coord.data.family])


def _due(value: str | None) -> date | datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value).replace(tzinfo=dt_util.get_default_time_zone())
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _when(value: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt_util.UTC)
    except ValueError:
        return None


class JarTodo(CoordinatorEntity[JarCoordinator], TodoListEntity):
    _attr_has_entity_name = True
    _attr_supported_features = (TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM
                                | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
                                | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
                                | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def __init__(self, coord: JarCoordinator, person: dict) -> None:
        super().__init__(coord)
        self.pid = person["id"]
        self._attr_unique_id = f"{coord.config_entry.entry_id}_{self.pid}_tasks"
        self.entity_id = f"todo.jar_{self.pid}"          # readable even when names are in Hebrew
        self._attr_name = person["name"]
        self._attr_icon = "mdi:account-check" if person.get("role") == "child" else "mdi:account-tie"
        self._attr_device_info = {"identifiers": {(DOMAIN, coord.config_entry.entry_id)}, "name": "Jar",
                                  "manufacturer": "Jar", "entry_type": "service"}
        self._items: list[TodoItem] = []

    def _mine(self) -> list[dict]:
        now = dt_util.utcnow()
        out = []
        for t in self.coordinator.data.tasks:
            if self.pid not in owners(t):
                continue
            if t.get("status") == "done":
                at = _when(t.get("done_at"))
                if at is None or now - at > KEEP_DONE:
                    continue
            elif t.get("status") not in ("open", "requested"):
                continue
            out.append(t)
        return out

    def _item(self, t: dict) -> TodoItem:
        done = t.get("status") == "done" or self.pid in (t.get("done_parts") or {})
        notes = []
        others = [self.coordinator.data.name(i) for i in owners(t) if i != self.pid]
        if others:
            notes.append(("👥 כל אחד: " if t.get("mode") == "all" else "👥 עם: ") + ", ".join(others))
        if t.get("status") == "requested":
            notes.append("⏳ מחכה לאישור הורה")
        if t.get("coins"):
            notes.append(f"🪙 {t['coins']}")
        if t.get("notes"):
            notes.append(t["notes"])
        return TodoItem(summary=t.get("title", ""), uid=t["id"],
                        status=TodoItemStatus.COMPLETED if done else TodoItemStatus.NEEDS_ACTION,
                        due=_due(t.get("due")), description="\n".join(notes) or None)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._items = [self._item(t) for t in self._mine()]
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._items = [self._item(t) for t in self._mine()]

    @property
    def todo_items(self) -> list[TodoItem]:
        return self._items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        due = item.due.strftime("%Y-%m-%dT%H:%M") if isinstance(item.due, datetime) else (
            item.due.isoformat() if isinstance(item.due, date) else None)
        try:
            await self.coordinator.api.add_task(item.summary or "", [self.pid], due, item.description or "")
        except JarError as e:
            raise HomeAssistantError(f"Jar: {e}") from e
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = next((i for i in self._items if i.uid == item.uid), None)
        if current is None:
            raise ServiceValidationError("no such task in Jar")
        if item.summary != current.summary or item.due != current.due:
            raise ServiceValidationError("change the task in the Jar app; here you can only tick it")
        if item.status == current.status:
            return
        action = "done" if item.status == TodoItemStatus.COMPLETED else "reopen"
        try:
            await self.coordinator.api.act(item.uid, action, self.pid)
        except JarError as e:
            raise HomeAssistantError(f"Jar: {e}") from e
        await self.coordinator.async_request_refresh()


class JarShopping(CoordinatorEntity[JarCoordinator], TodoListEntity):
    """What this family member is going to buy (worker/shopping.py). Ticking = bought; a new item lands on
    their list, asked for by Home Assistant."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cart-outline"
    _attr_supported_features = TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coord: JarCoordinator, person: dict) -> None:
        super().__init__(coord)
        self.pid = person["id"]
        self._attr_unique_id = f"{coord.config_entry.entry_id}_{self.pid}_shopping"
        self.entity_id = f"todo.jar_{self.pid}_shopping"
        self._attr_name = f"🛒 {person['name']}"
        self._attr_device_info = {"identifiers": {(DOMAIN, coord.config_entry.entry_id)}, "name": "Jar",
                                  "manufacturer": "Jar", "entry_type": "service"}
        self._items: list[TodoItem] = []

    def _build(self) -> list[TodoItem]:
        out = []
        for i in self.coordinator.data.shopping:
            if i.get("buyer") != self.pid:
                continue
            notes = []
            if i.get("requested_by") and i["requested_by"] != self.pid:
                notes.append("ביקש/ה: " + self.coordinator.data.name(i["requested_by"]))
            if i.get("notes"):
                notes.append(i["notes"])
            out.append(TodoItem(summary=i.get("title", ""), uid=i["id"],
                                status=TodoItemStatus.COMPLETED if i.get("status") == "bought"
                                else TodoItemStatus.NEEDS_ACTION,
                                description=" · ".join(notes) or None))
        out.sort(key=lambda x: x.status == TodoItemStatus.COMPLETED)
        return out

    @callback
    def _handle_coordinator_update(self) -> None:
        self._items = self._build()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._items = self._build()

    @property
    def todo_items(self) -> list[TodoItem]:
        return self._items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        try:
            await self.coordinator.api.shop_add([item.summary or ""], self.pid, item.description or "")
        except JarError as e:
            raise HomeAssistantError(f"Jar: {e}") from e
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = next((i for i in self._items if i.uid == item.uid), None)
        if current is None:
            raise ServiceValidationError("no such item in Jar")
        if item.summary != current.summary:
            raise ServiceValidationError("change the item in the Jar app; here you can only tick it")
        if item.status == current.status:
            return
        try:
            await self.coordinator.api.shop_act(
                item.uid, "bought" if item.status == TodoItemStatus.COMPLETED else "unbought")
        except JarError as e:
            raise HomeAssistantError(f"Jar: {e}") from e
        await self.coordinator.async_request_refresh()
