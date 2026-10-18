"""The family points game, phase 1 (docs/POINTS.md): coins for tasks done, a ledger, a weekly board.

    coins = round(5 · E · R · S · T)

Phase 1 pays E only (R = S = T = 1.0); the factors are already in every ledger line's breakdown so
phase 2 only has to change `factors()`.

data/points.json
    lines    one per payment: person, task_id, title, chore_key, kind (task | lesson | work_day), at (UTC),
             coins, breakdown, by_parent, created_by, rated_by, reversed (+ reversed_at, reversed_why)
    ratings  chore_key -> {effort, by, at}: what a parent said it is worth; the starting point next time
A line is never deleted: reopening, deleting or reassigning a done task marks its line reversed, and
reversed lines count for nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .effort import default_rating
from .filelock import locked

COIN = 5


@dataclass
class PointsConfig:
    """[points] in config.toml. daily_cap, parent_ok_over and the factors arrive with phase 2."""
    daily_cap: int = 150
    work_day_coins: int = 30
    parent_ok_over: int = 0           # 0 = off
    week_start: str = "sunday"
    announce: str = "sat 20:00"

    @classmethod
    def from_raw(cls, raw: dict | None) -> "PointsConfig":
        raw = raw or {}

        def num(key: str, default: int) -> int:
            try:
                return max(0, int(raw.get(key, default)))
            except (TypeError, ValueError):
                return default
        return cls(daily_cap=num("daily_cap", 150), work_day_coins=num("work_day_coins", 30),
                   parent_ok_over=num("parent_ok_over", 0),
                   week_start="monday" if str(raw.get("week_start", "sunday")).lower().startswith("mon") else "sunday",
                   announce=str(raw.get("announce", "sat 20:00")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(at: str) -> datetime:
    return datetime.fromisoformat((at or "").replace("Z", "+00:00"))


class PointsStore:
    def __init__(self, path: Path, family, tz: str = "Asia/Jerusalem", cfg: PointsConfig | None = None):
        self.path, self.family, self.cfg = path, family, cfg or PointsConfig()
        self.tz = ZoneInfo(tz)
        self.lock_path = path.with_suffix(".lock")

    # ---- storage ----
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        data.setdefault("seq", 0)
        data.setdefault("lines", [])
        data.setdefault("ratings", {})
        return data

    def _write(self, data: dict) -> None:
        data["rev"] = int(data.get("rev", 0)) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- what a task is worth ----
    @staticmethod
    def factors(person_id: str, points: dict, at: datetime | None = None) -> dict:
        """E, R, S, T and the habit bonus. Phase 1: effort only; phase 2 fills in the rest."""
        e = max(1, min(10, int(points.get("effort", 3) or 3)))
        return {"E": e, "R": 1.0, "S": 1.0, "T": 1.0, "habit": 1.0}

    def compute(self, person_id: str, points: dict | None, at: datetime | None = None) -> tuple[int, dict]:
        """(coins, breakdown) for a rated task; 0 coins for no-coin tasks."""
        if not points or points.get("no_coins"):
            return 0, {}
        if points.get("work_day"):
            return self.cfg.work_day_coins, {"fixed": self.cfg.work_day_coins}
        f = self.factors(person_id, points, at)
        return int(round(COIN * f["E"] * f["R"] * f["S"] * f["T"] * f["habit"])), f

    def preview(self, task: dict) -> int:
        """What an open task will pay (0 until it is rated)."""
        pts = task.get("points")
        if not pts or ("effort" not in pts and not pts.get("work_day")):
            return 0
        return self.compute(task.get("assignee", ""), pts)[0]

    # ---- parent corrections, remembered per chore ----
    def parent_effort(self, chore_key: str) -> int | None:
        r = self._read()["ratings"].get(chore_key)
        return int(r["effort"]) if r and r.get("effort") else None

    def remember(self, chore_key: str, effort: int, by: str) -> None:
        if not chore_key:
            return
        with locked(self.lock_path):
            data = self._read()
            data["ratings"][chore_key] = {"effort": int(effort), "by": by, "at": _now_iso()}
            self._write(data)

    def known_keys(self, limit: int = 15) -> list[str]:
        """Chore keys to offer the model so the same chore keeps the same key: parents' ratings first,
        then the most recently paid."""
        data = self._read()
        keys = [k for k, _ in sorted(data["ratings"].items(), key=lambda kv: kv[1].get("at", ""), reverse=True)]
        for ln in reversed(data["lines"]):
            k = ln.get("chore_key")
            if k and k not in keys and not k.startswith("t-") and k not in ("work-day", "lesson"):
                keys.append(k)
            if len(keys) >= limit:
                break
        return keys[:limit]

    # ---- paying and taking back ----
    @staticmethod
    def _active(data: dict, task_id: str, person: str | None = None) -> dict | None:
        return next((ln for ln in data["lines"] if ln.get("task_id") == task_id and not ln.get("reversed")
                     and (person is None or ln.get("person") == person)), None)

    def paid_map(self) -> dict[str, dict[str, int]]:
        """task id -> {person: coins paid} (active lines only), for showing "🪙 40" on done tasks.
        A shared task done by each of several people has a line per person."""
        out: dict[str, dict[str, int]] = {}
        for ln in self._read()["lines"]:
            if ln.get("task_id") and not ln.get("reversed"):
                out.setdefault(ln["task_id"], {})[ln.get("person", "")] = ln["coins"]
        return out

    def pay(self, task: dict, at: str | None = None, person: str | None = None) -> dict | None:
        """Pay `person` (default: the assignee) for a task that was just done. Safe to call twice: the second
        call finds the line. An unrated task is paid at the default rating and keeps it (a parent can
        correct it later). Returns {"new", "coins", "breakdown", "week_total", "line"} or None for a
        no-coin task."""
        points = task.get("points")
        if points is None:
            points = task["points"] = default_rating(task.get("title", ""))
        if points.get("no_coins"):
            return None
        who = person or task.get("assignee", "")
        at = at or task.get("done_at") or _now_iso()
        with locked(self.lock_path):
            data = self._read()
            old = self._active(data, task["id"], who)
            if old is not None:
                return self._award(data, old, new=False)
            if points.get("work_day") and self._work_day_paid(data, who, at):
                return None                                  # one work day per person per day
            coins, breakdown = self.compute(who, points, _parse(at))
            creator = self.family.get(task.get("created_by"))
            data["seq"] += 1
            line = {"id": data["seq"], "person": who, "task_id": task["id"], "title": task.get("title", ""),
                    "chore_key": points.get("chore_key", ""), "category": points.get("category", "other"),
                    "kind": self._kind(task, points),
                    "at": at, "coins": coins, "breakdown": breakdown,
                    "by_parent": bool(creator and creator.is_parent), "created_by": task.get("created_by", ""),
                    "rated_by": points.get("rated_by", "ai"), "reversed": False}
            if points.get("note"):
                line["note"] = points["note"]
            data["lines"].append(line)
            self._write(data)
            return self._award(data, line, new=True)

    @staticmethod
    def _kind(task: dict, points: dict) -> str:
        if points.get("work_day"):
            return "work_day"
        return "lesson" if task.get("kind") == "lesson" else "task"

    def _work_day_paid(self, data: dict, person: str, at: str) -> bool:
        day = _parse(at).astimezone(self.tz).date()
        return any(ln.get("kind") == "work_day" and ln.get("person") == person and not ln.get("reversed")
                   and _parse(ln["at"]).astimezone(self.tz).date() == day for ln in data["lines"])

    def _award(self, data: dict, line: dict, new: bool) -> dict:
        start, end = self.week_bounds(_parse(line["at"]).astimezone(self.tz))
        total = sum(ln["coins"] for ln in data["lines"] if ln["person"] == line["person"] and not ln.get("reversed")
                    and start <= _parse(ln["at"]).astimezone(self.tz).date() <= end)
        return {"new": new, "line": line["id"], "coins": line["coins"], "breakdown": line.get("breakdown", {}),
                "week_total": total}

    def reverse(self, task_id: str, why: str = "", person: str | None = None) -> int:
        """Take back what a task paid (reopened, deleted, reassigned) — from everyone, or from one
        person of a shared task. Returns the coins taken back."""
        with locked(self.lock_path):
            data = self._read()
            back = 0
            for ln in data["lines"]:
                if ln.get("task_id") == task_id and not ln.get("reversed") \
                        and (person is None or ln.get("person") == person):
                    ln.update(reversed=True, reversed_at=_now_iso(), reversed_why=why)
                    back += ln["coins"]
            if back or any(ln.get("task_id") == task_id for ln in data["lines"]):
                self._write(data)
            return back

    def repay(self, task: dict) -> dict | None:
        """A parent changed the effort of a task that is already done: pay again at the new rate, keeping
        the time it was done."""
        with locked(self.lock_path):
            data = self._read()
            olds = [ln for ln in data["lines"] if ln.get("task_id") == task["id"] and not ln.get("reversed")]
        if not olds:
            return self.pay(task, task.get("done_at"))
        self.reverse(task["id"], "rating changed")
        award = None
        for old in olds:
            award = self.pay(task, old["at"], old["person"]) or award
        return award

    def pay_work_day(self, person_id: str, at: str | None = None) -> dict | None:
        """A parent's work day without a task: the fixed base from [points] work_day_coins, once a day."""
        at = at or _now_iso()
        with locked(self.lock_path):
            data = self._read()
            if self._work_day_paid(data, person_id, at):
                return None
            data["seq"] += 1
            line = {"id": data["seq"], "person": person_id, "task_id": None, "title": "work day",
                    "chore_key": "work-day", "category": "job", "kind": "work_day", "at": at,
                    "coins": self.cfg.work_day_coins, "breakdown": {"fixed": self.cfg.work_day_coins},
                    "by_parent": True, "created_by": person_id, "rated_by": "rule", "reversed": False}
            data["lines"].append(line)
            self._write(data)
            return self._award(data, line, new=True)

    # ---- weeks ----
    def week_bounds(self, local: datetime) -> tuple[date, date]:
        """The Sunday-to-Saturday week (or Monday-Sunday by config) that contains this local time."""
        back = local.weekday() if self.cfg.week_start == "monday" else (local.weekday() + 1) % 7
        start = local.date() - timedelta(days=back)
        return start, start + timedelta(days=6)

    def _local_day(self, at: str) -> date:
        return _parse(at).astimezone(self.tz).date()

    def _streak(self, days: set[date], today: date) -> int:
        d = today if today in days else today - timedelta(days=1)
        n = 0
        while d in days:
            n += 1
            d -= timedelta(days=1)
        return n

    def _may_see(self, viewer, ln: dict) -> bool:
        """The same rule as tasks: yours, ones you gave, and (parents) the children's. Work days are open."""
        if ln.get("kind") == "work_day" or viewer.id in (ln.get("person"), ln.get("created_by")):
            return True
        who = self.family.get(ln.get("person"))
        return viewer.is_parent and who is not None and not who.is_parent

    def _public(self, viewer, ln: dict) -> dict:
        see = self._may_see(viewer, ln)
        out = {k: ln.get(k) for k in ("id", "task_id", "kind", "category", "at", "coins", "breakdown",
                                       "rated_by", "reversed", "reversed_why")}
        out["title"] = ln.get("title") if see else None
        if see and ln.get("note"):
            out["note"] = ln["note"]
        out["chore_key"] = ln.get("chore_key") if see else None
        return out

    def board(self, viewer, now: datetime | None = None) -> dict:
        """Everything the app's Leaderboard tab shows, as seen by `viewer`."""
        data = self._read()
        now = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        start, end = self.week_bounds(now)
        today = now.date()
        active = [ln for ln in data["lines"] if not ln.get("reversed")]
        people = []
        for p in self.family.people.values():
            mine = [ln for ln in active if ln["person"] == p.id]
            this_week = [ln for ln in mine if start <= self._local_day(ln["at"]) <= end]
            by_key: dict[str, list] = {}
            for ln in (this_week or mine):
                if ln.get("chore_key") and ln.get("kind") == "task":
                    by_key.setdefault(ln["chore_key"], []).append(ln)
            best = None
            if by_key:
                key, lns = max(by_key.items(), key=lambda kv: sum(x["coins"] for x in kv[1]))
                last = max(lns, key=lambda x: x["at"])
                best = {"coins": sum(x["coins"] for x in lns), "category": last.get("category", "other"),
                        "title": last.get("title") if self._may_see(viewer, last) else None}
            people.append({
                "id": p.id, "name": p.name, "role": p.role,
                "week": sum(ln["coins"] for ln in this_week), "all_time": sum(ln["coins"] for ln in mine),
                "tasks_week": len(this_week),
                "streak": self._streak({self._local_day(ln["at"]) for ln in mine if ln.get("by_parent")}, today),
                "best": best})
        people.sort(key=lambda x: (-x["week"], -x["all_time"], x["name"]))
        ledgers = {}
        for p in people:
            lines = sorted((ln for ln in data["lines"] if ln["person"] == p["id"]), key=lambda x: x["at"],
                           reverse=True)[:40]
            ledgers[p["id"]] = [self._public(viewer, ln) for ln in lines]
        cutoff = (now - timedelta(days=14)).date()
        feed = [ln for ln in active if ln.get("kind") == "lesson" and ln.get("note")
                and self._local_day(ln["at"]) >= cutoff and self._may_see(viewer, ln)]
        feed.sort(key=lambda x: x["at"], reverse=True)
        names = {p.id: p.name for p in self.family.people.values()}
        return {
            "week": {"start": start.isoformat(), "end": end.isoformat()},
            "people": people, "ledgers": ledgers,
            "lessons": [{"id": ln["id"], "person": ln["person"], "name": names.get(ln["person"], ln["person"]),
                         "title": ln.get("title", ""), "note": ln["note"], "coins": ln["coins"], "at": ln["at"]}
                        for ln in feed[:15]],
            "summary": self.summary(data, now),
            "config": {"work_day_coins": self.cfg.work_day_coins, "announce": self.cfg.announce},
            "me": viewer.id,
        }

    def summary(self, data: dict | None = None, now: datetime | None = None) -> dict:
        """This week's result for the Saturday announcement: the winner(s) and the most improved."""
        data = data or self._read()
        now = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        start, end = self.week_bounds(now)
        weeks: dict[str, dict[date, int]] = {}
        for ln in data["lines"]:
            if ln.get("reversed"):
                continue
            ws = self.week_bounds(_parse(ln["at"]).astimezone(self.tz))[0]
            weeks.setdefault(ln["person"], {})
            weeks[ln["person"]][ws] = weeks[ln["person"]].get(ws, 0) + ln["coins"]
        totals = [{"id": p.id, "name": p.name, "coins": weeks.get(p.id, {}).get(start, 0)}
                  for p in self.family.people.values()]
        totals.sort(key=lambda x: (-x["coins"], x["name"]))
        top = totals[0]["coins"] if totals else 0
        winners = [t["id"] for t in totals if top > 0 and t["coins"] == top]
        improved = None
        for p in self.family.people.values():
            mine = weeks.get(p.id, {})
            this = mine.get(start, 0)
            before = [c for ws, c in sorted(mine.items()) if ws < start][-4:]     # the last 4 weeks with coins
            if this < 20 or not before:
                continue
            avg = sum(before) / len(before)
            gain = (this - avg) / avg if avg > 0 else 0
            if gain >= 0.1 and (improved is None or gain > improved["pct"] / 100):
                improved = {"id": p.id, "name": p.name, "pct": int(round(gain * 100)), "coins": this,
                            "before": int(round(avg))}
        return {"week_start": start.isoformat(), "week_end": end.isoformat(), "totals": totals,
                "winners": winners, "top": top, "most_improved": improved}
