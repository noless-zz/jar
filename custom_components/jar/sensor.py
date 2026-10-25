"""Coins this week per family member (the Jar leaderboard), and how many tasks are open."""

from __future__ import annotations

from datetime import date, datetime, time

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import JarConfigEntry
from .const import DOMAIN
from .coordinator import JarCoordinator, owners


async def async_setup_entry(hass: HomeAssistant, entry: JarConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities([JarCoins(coord, p) for p in coord.data.family]
                       + [JarOpen(coord, p) for p in coord.data.family])


class _Base(CoordinatorEntity[JarCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: JarCoordinator, person: dict, kind: str) -> None:
        super().__init__(coord)
        self.pid = person["id"]
        self._attr_unique_id = f"{coord.config_entry.entry_id}_{self.pid}_{kind}"
        self.entity_id = f"sensor.jar_{self.pid}_{kind}"
        self._attr_device_info = {"identifiers": {(DOMAIN, coord.config_entry.entry_id)}, "name": "Jar",
                                  "manufacturer": "Jar", "entry_type": "service"}


class JarCoins(_Base):
    _attr_icon = "mdi:hand-coin"
    _attr_native_unit_of_measurement = "🪙"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord: JarCoordinator, person: dict) -> None:
        super().__init__(coord, person, "coins_week")
        self._attr_name = f"{person['name']} coins this week"

    @property
    def native_value(self) -> int | None:
        row = self.coordinator.data.points.get(self.pid)
        return row.get("week") if row else None

    @property
    def extra_state_attributes(self) -> dict:
        row = self.coordinator.data.points.get(self.pid) or {}
        rank = [p["id"] for p in self.coordinator.data.points.values()].index(self.pid) + 1 \
            if self.pid in self.coordinator.data.points else None
        return {"all_time": row.get("all_time"), "tasks_this_week": row.get("tasks_week"),
                "streak_days": row.get("streak"), "rank": rank}


def _local(value: str | None):
    """A task's due ("YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", Jar's local time) -> aware datetime, or None.
    A date alone counts as the end of that day."""
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value).replace(tzinfo=dt_util.get_default_time_zone())
        d = date.fromisoformat(value[:10])
        return datetime.combine(d, time(23, 59), dt_util.get_default_time_zone())
    except ValueError:
        return None


def next_tasks(data, pid: str, limit: int = 3) -> list[dict]:
    """The person's most urgent open tasks: overdue first, then by due time; tasks without a day after them
    (oldest first). Snoozed ones wait until their time."""
    now = dt_util.now()
    rows = []
    for t in data.tasks:
        if pid not in owners(t) or t.get("status") != "open" or pid in (t.get("done_parts") or {}):
            continue
        snoozed = _local(t.get("snoozed_until"))
        if snoozed is not None and snoozed > now:
            continue
        due = _local(t.get("due"))
        a = data.areas.get(t.get("area") or "") or {}
        rows.append(((0, due) if due else (1, None), t.get("created_at") or "", {
            "id": t["id"], "title": t.get("title", ""), "due": t.get("due"),
            "overdue": bool(due and due < now), "coins": t.get("coins") or 0,
            "area": ((a.get("emoji", "") + " " + a.get("name", "")).strip() if a else ""),
            "shared": len(owners(t)) > 1, "repeat": t.get("repeat") or ""}))
    far = datetime.max.replace(tzinfo=dt_util.UTC)
    rows.sort(key=lambda r: (r[0][0], r[0][1] or far, r[1]))
    return [r[2] for r in rows[:limit]]


class JarOpen(_Base):
    _attr_icon = "mdi:format-list-checks"
    _attr_native_unit_of_measurement = "tasks"

    def __init__(self, coord: JarCoordinator, person: dict) -> None:
        super().__init__(coord, person, "open_tasks")
        self._attr_name = f"{person['name']} open tasks"

    @property
    def native_value(self) -> int:
        return sum(1 for t in self.coordinator.data.tasks
                   if self.pid in owners(t) and t.get("status") == "open"
                   and self.pid not in (t.get("done_parts") or {}))

    @property
    def extra_state_attributes(self) -> dict:
        """next: the 3 most urgent tasks, for a compact panel card (docs/HOME_ASSISTANT.md)."""
        return {"next": next_tasks(self.coordinator.data, self.pid)}
