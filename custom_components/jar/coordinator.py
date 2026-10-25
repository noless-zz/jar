"""Polls Jar for the family, the household tasks and the leaderboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import JarApi, JarAuthError, JarError
from .const import DOMAIN, EVENT_TASK_DONE, EVENT_TASK_NEW, SCAN_SECONDS

_LOGGER = logging.getLogger(__name__)


def owners(t: dict) -> list[str]:
    a = t.get("assignees")
    if isinstance(a, list) and a:
        return list(a)
    return [t["assignee"]] if t.get("assignee") else []


@dataclass
class JarData:
    family: list[dict] = field(default_factory=list)       # [{"id", "name", "role", "admin"}]
    tasks: list[dict] = field(default_factory=list)
    points: dict = field(default_factory=dict)              # person id -> leaderboard row
    areas: dict = field(default_factory=dict)               # area id -> {"name", "emoji", "owner"}

    def name(self, pid: str) -> str:
        return next((p["name"] for p in self.family if p["id"] == pid), pid)


class JarCoordinator(DataUpdateCoordinator[JarData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: JarApi) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=SCAN_SECONDS),
                         config_entry=entry)
        self.api = api
        self._family: list[dict] = []
        self._family_rounds = 0

    async def _async_update_data(self) -> JarData:
        try:
            if not self._family or self._family_rounds >= 120:        # the family list: once an hour
                me = await self.api.me()
                self._family = [p for p in me.get("family", []) if p.get("id") != "home"]
                self._family_rounds = 0
            self._family_rounds += 1
            snap = await self.api.tasks()
            board = await self.api.points()
        except JarAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except JarError as e:
            raise UpdateFailed(str(e)) from e
        data = JarData(self._family, snap.get("tasks", []),
                       {row["id"]: row for row in board.get("people", [])},
                       {a["id"]: a for a in snap.get("areas", []) if isinstance(a, dict) and a.get("id")})
        self._fire_events(data)
        return data

    def _fire_events(self, new: JarData) -> None:
        """jar_task_done / jar_task_new for automations (not on the first load)."""
        old = self.data
        if old is None:
            return
        before = {t["id"]: t for t in old.tasks}
        for t in new.tasks:
            prev = before.get(t["id"])
            info = {"id": t["id"], "title": t.get("title", ""), "people": owners(t),
                    "names": [new.name(i) for i in owners(t)], "created_by": t.get("created_by", "")}
            if prev is None and t.get("status") in ("open", "requested"):
                self.hass.bus.async_fire(EVENT_TASK_NEW, info)
            elif prev is not None and prev.get("status") != "done" and t.get("status") == "done":
                self.hass.bus.async_fire(EVENT_TASK_DONE, {**info, "done_by": t.get("done_by", ""),
                                                           "coins": t.get("coins", 0)})
