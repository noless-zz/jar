"""The family's task list: one JSON file shared by the worker (adds tasks from memos) and the
server (the phone apps read and tick them). A lock file keeps the two processes from clobbering
each other. notes/Tasks.md is rewritten from it after every change, so Obsidian still shows it.

A task:
    id, title, notes, assignee, created_by, status, due, snoozed_until,
    created_at, updated_at, done_at, done_by, memo_id
    points   {effort 1-10, minutes, category, chore_key, reason, rated_by, no_coins}: what it is worth
             (worker/effort.py rates it once; a parent can change it; coins are paid by worker/points.py)
status:  open | done | requested (a child asked someone; waits for a parent) | declined
Shared (family) tasks: "assignees" lists everyone it is for ("assignee" stays the first of them, so older
apps still work) and "mode" says who has to do it: "any" = one of them is enough, "all" = each of them.
In "all" mode "done_parts" {person: when} records who has done their part; the task is done when everyone has.
due / snoozed_until:  local time, "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" (the family's time zone)

Who sees what: your own tasks, tasks you gave someone, and (parents only) the children's tasks.
A task you give yourself is private to you. Jar ideas (kind "idea") are seen by everyone.

Recurring tasks (משימות רב פעמיות): data["series"] holds the rules; each occurrence is an ordinary task
with "series_id" and "repeat" (the rule in words), made on its day by roll(). An occurrence still open
when the next one is made is quietly marked "missed". See worker/recurring.py for the rules.
    series: id, title, notes, created_by, owners, mode, rotate, turn, rule, time, after_done, approved,
            status (active | paused | ended), next_due (YYYY-MM-DD), current (task id), points, memo_id

Jar ideas: kind "idea", for the admin, status requested (new) -> open (accepted: the one who suggested it
gets idea coins) | declined -> done (shipped: a small bonus). Nobody earns coins for building an idea.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import effort as effort_mod
from . import recurring
from .family import Family, Person
from .filelock import locked

WHEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
ACTIONS = ("done", "reopen", "snooze", "accept", "decline", "delete", "edit")
SERIES_ACTIONS = ("stop", "pause", "resume", "edit")
LIVE = ("open", "requested")


def done_time(epoch) -> str:
    """When a task was ticked: the phone's own time for a tick made offline (within the last 14 days,
    never in the future), otherwise now."""
    try:
        at = float(epoch)
    except (TypeError, ValueError):
        return _now()
    now = datetime.now(timezone.utc).timestamp()
    if not (now - 14 * 86400 <= at <= now + 60):
        return _now()
    return datetime.fromtimestamp(min(at, now), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TaskError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_when(value: str | None) -> str | None:
    v = (value or "").strip().replace(" ", "T")[:16]
    if not v:
        return None
    if not WHEN_RE.match(v):
        raise TaskError(400, "time must be YYYY-MM-DD or YYYY-MM-DDTHH:MM")
    try:
        datetime.fromisoformat(v)
    except ValueError:
        raise TaskError(400, "no such date/time") from None
    return v


def owners(t: dict) -> list[str]:
    """Everyone a task is for: the "assignees" of a shared task, else its one assignee."""
    a = t.get("assignees")
    if isinstance(a, list) and a:
        return list(a)
    return [t["assignee"]] if t.get("assignee") else []


def shared_mode(t: dict) -> str:
    """"any" (one of them is enough; also every single-owner task) or "all" (each of them)."""
    return "all" if t.get("mode") == "all" and len(owners(t)) > 1 else "any"


def _set_owners(t: dict, people: list[Person], mode: str | None = None) -> None:
    ids = list(dict.fromkeys(p.id for p in people))
    t["assignee"] = ids[0]
    if len(ids) > 1:
        t["assignees"] = ids
        t["mode"] = "all" if (mode or t.get("mode")) == "all" else "any"
    else:
        for k in ("assignees", "mode", "done_parts"):
            t.pop(k, None)


class TaskStore:
    def __init__(self, path: Path, family: Family, markdown: Path | None = None, points=None):
        self.path, self.family, self.markdown = path, family, markdown
        self.points = points              # PointsStore, or None (no coins)
        self.lock_path = path.with_suffix(".lock")
        self.tz = getattr(points, "tz", None) or ZoneInfo("Asia/Jerusalem")

    # ---- storage ----
    @contextmanager
    def _locked(self):
        with locked(self.lock_path, lambda: TaskError(503, "task list is busy, try again")):
            yield

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"rev": 0, "tasks": []}
        data.setdefault("series", [])
        return data

    def _write(self, data: dict) -> None:
        data["rev"] = int(data.get("rev", 0)) + 1
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        if self.markdown:
            try:
                self.markdown.parent.mkdir(parents=True, exist_ok=True)
                self.markdown.write_text(self.to_markdown(data["tasks"]), encoding="utf-8", newline="\n")
            except OSError:
                pass                                 # Obsidian having the file open must not lose a task

    # ---- rules ----
    def visible(self, t: dict, p: Person) -> bool:
        if t.get("kind") == "idea":
            return True                                  # the family sees every idea and what became of it
        ids = owners(t)
        if p.id == t.get("created_by") or p.id in ids:
            return True
        return p.is_parent and any((a := self.family.get(i)) is not None and not a.is_parent for i in ids)

    def resolve_people(self, ids) -> list[Person]:
        """Family members from a list of ids (or one id); raises on an unknown one."""
        if isinstance(ids, str):
            ids = [ids]
        out = []
        for i in ids or []:
            who = self.family.get(str(i))
            if who is None:
                raise TaskError(400, f"no such family member: {i}")
            if who not in out:
                out.append(who)
        return out

    # ---- API ----
    def snapshot(self, p: Person) -> dict:
        data = self._read()
        tasks = [t for t in data["tasks"] if self.visible(t, p) and t.get("status") not in ("deleted", "missed")]
        tasks = self._decorate(tasks, p)
        series = [self._series_out(x) for x in data["series"]
                  if x.get("status") != "ended" and self._series_visible(x, p)]
        return {"rev": data.get("rev", 0), "tasks": tasks, "series": series}

    def _decorate(self, tasks: list[dict], viewer: Person | None = None) -> list[dict]:
        """Copies of the tasks with "coins": what a done task paid, or what an open one will pay
        (0 = nothing, or not rated yet), and "paid": true for the first. On a shared task the viewer
        sees their own payment once they have done their part."""
        if self.points is None:
            return tasks
        paid = self.points.paid_map()
        out = []
        for t in tasks:
            t = dict(t)
            lines = paid.get(t["id"], {})
            mine = lines.get(viewer.id) if viewer is not None else None
            if mine is not None:
                t.update(coins=mine, paid=True)
            elif lines and t.get("status") == "done":
                t.update(coins=max(lines.values()), paid=True)
            elif t.get("kind") == "idea" and t.get("status") == "requested":
                who = self.family.get(t.get("created_by"))      # what accepting it would pay the one who suggested it
                cfg = getattr(self.points, "cfg", None)
                ok = who is not None and not who.admin and (not who.is_parent or getattr(cfg, "idea_credit_parents", False))
                t["coins"] = getattr(cfg, "idea_coins", 0) if ok else 0
            elif t.get("status") in ("open", "requested"):
                t["coins"] = self.points.preview(t)
            out.append(t)
        return out

    def add(self, creator: Person, title: str, assignee: Person | list[Person] | None = None, due: str | None = None,
            notes: str = "", memo_id: str | None = None, kind: str = "task", message: str = "",
            to: str = "", phone: str = "", mode: str = "any") -> dict:
        """assignee: one person, or a list for a shared task (mode "any" = one of them is enough,
        "all" = each of them does it)."""
        title = (title or "").strip()
        if not title:
            raise TaskError(400, "title is required")
        people = [p for p in (assignee if isinstance(assignee, list) else [assignee]) if p is not None] or [creator]
        if kind == "message":
            people = people[:1]                       # a WhatsApp draft is sent by one person
        assignee = people[0]
        others = any(p.id != creator.id for p in people)
        status = "requested" if (not creator.is_parent and others) else "open"
        t = {"id": uuid.uuid4().hex[:10], "title": title[:300], "notes": (notes or "").strip()[:2000],
             "assignee": assignee.id, "created_by": creator.id, "status": status,
             "due": clean_when(due), "snoozed_until": None, "created_at": _now(), "updated_at": _now(),
             "done_at": None, "done_by": None, "memo_id": memo_id}
        _set_owners(t, people, mode)
        if kind == "message":
            # A prepared WhatsApp message: the phone shows "Send in WhatsApp"; the person presses Send.
            t.update(kind="message", message=(message or "").strip()[:4000], to=(to or "").strip()[:100],
                     phone="".join(ch for ch in (phone or "") if ch.isdigit())[:20])
        ruled = effort_mod.rule_rating(t["title"], kind, assignee)
        if ruled is not None:
            t["points"] = ruled                      # no model needed: no coins, or a parent's work day
        with self._locked():
            data = self._read()
            data["tasks"].append(t)
            self._write(data)
        return t

    def act(self, actor: Person, task_id: str, action: str, until: str | None = None,
            fields: dict | None = None) -> dict:
        if action not in ACTIONS:
            raise TaskError(400, f"unknown action {action}")
        award = None
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or not self.visible(t, actor):
                raise TaskError(404, "no such task")
            idea = t.get("kind") == "idea"
            if idea and action in ("accept", "decline", "done", "reopen") and not actor.admin:
                raise TaskError(403, f"only {self.family.admin.name} decides about Jar ideas")
            if action in ("accept", "decline"):
                if t["status"] != "requested":
                    raise TaskError(409, "this task isn't waiting for approval")
                if not actor.is_parent:
                    raise TaskError(403, "a parent approves requests")
                t["status"] = "open" if action == "accept" else "declined"
                f = fields or {}
                if idea and action == "decline":
                    if f.get("duplicate_of"):
                        t["duplicate_of"] = str(f["duplicate_of"])[:20]
                    if str(f.get("note") or "").strip():
                        self._add_note(t, actor, str(f["note"]))
                if idea and action == "accept":
                    award = self._credit_idea(t, "accepted")
                s = self._series_of(data, t)
                if s is not None and not s.get("approved"):
                    if action == "accept":
                        s["approved"] = True
                    else:
                        s["status"] = "ended"
                    s["updated_at"] = _now()
            elif action == "done":
                if t["status"] == "requested" and not actor.is_parent:
                    raise TaskError(409, "still waiting for a parent to approve it")
                # An offline tick carries the time it was made ("at", epoch seconds): paid at that time.
                at = done_time((fields or {}).get("at"))
                was_done = t["status"] == "done"
                award = self._done(t, actor, at)
                if idea and not was_done:
                    award = self._credit_idea(t, "shipped") or award
                s = self._series_of(data, t)
                if s is not None and s.get("after_done") and t["status"] == "done" and s.get("current") == t["id"]:
                    self._schedule_after_done(s, at)
            elif action == "reopen" and idea:
                if t["status"] == "done" and self.points is not None:
                    self.points.reverse(t["id"] + ":shipped", "reopened")     # the "accepted" credit stays
                t.update(status="open", done_at=None, done_by=None)
            elif action == "reopen":
                parts = t.get("done_parts") or {}
                if shared_mode(t) == "all" and t["status"] != "done" and actor.id in parts:
                    parts.pop(actor.id)                       # undo just my part
                    self._take_back(t, "reopened", actor.id)
                else:
                    t.update(status="open", done_at=None, done_by=None)
                    t.pop("done_parts", None)
                    self._take_back(t, "reopened")
            elif action == "snooze":
                t["snoozed_until"] = clean_when(until)
            elif action == "delete":
                if actor.id != t["created_by"] and not actor.admin:
                    raise TaskError(403, "only whoever created it can delete it")
                t["status"] = "deleted"
                self._take_back(t, "deleted")
                if idea and self.points is not None:
                    self.points.reverse(t["id"] + ":shipped", "deleted")
            elif action == "edit":
                f = fields or {}
                if idea and actor.id != t["created_by"] and not actor.admin:
                    raise TaskError(403, "only whoever suggested it can change an idea")
                if "title" in f and str(f["title"]).strip():
                    t["title"] = str(f["title"]).strip()[:300]
                if "due" in f:
                    t["due"] = clean_when(f["due"])
                    t["snoozed_until"] = None
                if "notes" in f:
                    t["notes"] = str(f["notes"] or "").strip()[:2000]
                if "message" in f and t.get("kind") == "message":
                    t["message"] = str(f["message"] or "").strip()[:4000]
                new_ids = f.get("assignees") or ([f["assignee"]] if f.get("assignee") else None)
                if t.get("kind") == "message" and new_ids:
                    new_ids = new_ids[:1]
                if new_ids and list(dict.fromkeys(map(str, new_ids))) != owners(t):
                    people = self.resolve_people(new_ids)
                    before, parts_before = owners(t), dict(t.get("done_parts") or {})
                    _set_owners(t, people, f.get("mode"))
                    who = people[0]
                    if not actor.is_parent and any(p.id != actor.id for p in people):
                        t["status"] = "requested"     # a child handing it to someone else: a parent OKs it
                    if t.get("status") == "done":
                        self._take_back(t, "reassigned")          # the new person didn't do it
                    else:
                        for gone in set(before) - set(owners(t)):     # a part done by someone taken off
                            (t.get("done_parts") or {}).pop(gone, None)
                            if gone in parts_before:
                                self._take_back(t, "reassigned", gone)
                        if before[0] != who.id and (t.get("points") or {}).get("rated_by") in ("ai", "default"):
                            t.pop("points")                       # rated for someone else: rate again
                            ruled = effort_mod.rule_rating(t["title"], t.get("kind", "task"), who)
                            if ruled is not None:
                                t["points"] = ruled
                elif f.get("mode") in ("any", "all") and len(owners(t)) > 1:
                    t["mode"] = f["mode"]
                if t.get("status") == "open" and shared_mode(t) == "all" \
                        and set(owners(t)) <= set(t.get("done_parts") or {}):
                    t.update(status="done", done_at=_now(), done_by=actor.id)   # the last one left was taken off
                if shared_mode(t) != "all":
                    t.pop("done_parts", None)
            t["updated_at"] = _now()
            self._write(data)
            return dict(t, award=award) if award else t

    # ---- coins ----
    def _take_back(self, t: dict, why: str, person: str | None = None) -> None:
        if self.points is not None:
            self.points.reverse(t["id"], why, person)

    def _done(self, t: dict, actor: Person, at: str) -> dict | None:
        """Tick a task. Shared "all" task: the actor's own part (the task is done once everyone's is);
        a parent who isn't one of them ticks it for all of them. "any": done, paid to whoever did it
        (to the first of them when someone else ticks it)."""
        ids = owners(t)
        pay_to: list[str]
        if shared_mode(t) == "all":
            parts = t.setdefault("done_parts", {})
            if actor.id in ids:
                if actor.id in parts:                            # my part is done already (a retried tick)
                    return self.points.pay(t, parts[actor.id], actor.id) if self.points is not None else None
                parts[actor.id] = at
                pay_to = [actor.id]
            else:
                pay_to = [i for i in ids if i not in parts]
                for i in pay_to:
                    parts[i] = at
            if set(ids) <= set(parts):
                t.update(status="done", done_at=at, done_by=actor.id, snoozed_until=None)
        else:
            if t["status"] == "done":                            # a retried tick: what it paid
                paid = t.get("done_by") if t.get("done_by") in ids else ids[0]
                return self.points.pay(t, t.get("done_at"), paid) if self.points is not None else None
            t.update(status="done", done_at=at, done_by=actor.id, snoozed_until=None)
            pay_to = [actor.id if actor.id in ids else ids[0]]
        award = None
        if self.points is not None:
            for i in pay_to:
                a = self.points.pay(t, at, i)
                if i == actor.id or award is None:
                    award = a or award
        return award

    def set_points(self, actor: Person, task_id: str, effort=None, no_coins=None) -> dict:
        """A parent's say on what a task is worth: its effort (1-10, remembered for that chore) and/or
        "no coins". A task that is already done is paid again at the new rate."""
        if not actor.is_parent:
            raise TaskError(403, "a parent sets what a task is worth")
        if effort is not None:
            try:
                effort = int(effort)
            except (TypeError, ValueError):
                raise TaskError(400, "effort must be a number from 1 to 10") from None
            if not 1 <= effort <= 10:
                raise TaskError(400, "effort must be from 1 to 10")
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or not self.visible(t, actor):
                raise TaskError(404, "no such task")
            if t.get("kind") == "message":
                raise TaskError(409, "a WhatsApp message earns no coins")
            pts = dict(t.get("points") or effort_mod.default_rating(t["title"]))
            if effort is not None:
                pts.pop("work_day", None)
                pts.update(effort=effort, rated_by="parent", rated_by_id=actor.id)
                if no_coins is None:
                    pts["no_coins"] = False
            if no_coins is not None:
                pts["no_coins"] = bool(no_coins)
            t["points"] = pts
            s = self._series_of(data, t)
            if s is not None:
                s["points"] = dict(pts)                   # the next occurrences are worth the same
            self._write(data)
        if self.points is not None:
            if effort is not None:
                self.points.remember(pts.get("chore_key", ""), effort, actor.id)
            if t.get("status") == "done" or t.get("done_parts"):
                self.points.repay(t)
        return self._decorate([t], actor)[0]

    def unrated(self, limit: int = 4) -> list[dict]:
        """Open tasks nobody has rated yet, newest first (the worker rates them)."""
        found = [dict(t) for t in self._read()["tasks"]
                 if t.get("status") in ("open", "requested") and "points" not in t and t.get("kind", "task") == "task"]
        found.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return found[:limit]

    def rate(self, task_id: str, rating: dict) -> bool:
        """Store the model's rating, but never over one a parent or a rule already put there."""
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or t.get("points") is not None:
                return False
            t["points"] = rating
            s = self._series_of(data, t)
            if s is not None and not s.get("points"):
                s["points"] = dict(rating)                # the whole series is worth the same every time
            self._write(data)
            return True

    def add_lesson(self, actor: Person, title: str, note: str, effort: int, rated_by: str = "ai") -> dict:
        """A lesson a child attended: a finished task whose "what I learned" note earns the coins
        (effort 1-5). Parents see it with the children's other tasks."""
        note = (note or "").strip()[:2000]
        today = self._local_day(_now())
        if sum(1 for x in self._read()["tasks"] if x.get("kind") == "lesson" and x.get("created_by") == actor.id
               and self._local_day(x.get("created_at", "")) == today) >= 3:
            raise TaskError(429, "three lesson notes a day is the limit")
        t = {"id": uuid.uuid4().hex[:10], "title": ((title or "").strip() or "Lesson")[:300], "notes": note,
             "assignee": actor.id, "created_by": actor.id, "status": "done", "due": None, "snoozed_until": None,
             "created_at": _now(), "updated_at": _now(), "done_at": _now(), "done_by": actor.id, "memo_id": None,
             "kind": "lesson",
             "points": {"effort": max(1, min(5, int(effort))), "minutes": 0, "category": "lesson",
                        "chore_key": "lesson", "reason": "what I learned", "rated_by": rated_by,
                        "no_coins": False, "note": note}}
        award = None
        with self._locked():
            data = self._read()
            data["tasks"].append(t)
            if self.points is not None:
                award = self.points.pay(t, t["done_at"])
            self._write(data)
        out = self._decorate([t], actor)[0]
        return dict(out, award=award) if award else out

    def _local_day(self, iso: str):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        tz = getattr(self.points, "tz", None)
        return (dt.astimezone(tz) if tz else dt).date()

    # ---- recurring tasks (משימות רב פעמיות) ----
    def _today(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(timezone.utc)).astimezone(self.tz)

    @staticmethod
    def _series_of(data: dict, t: dict) -> dict | None:
        sid = t.get("series_id")
        return next((x for x in data["series"] if x["id"] == sid), None) if sid else None

    def _series_visible(self, s: dict, p: Person) -> bool:
        return self.visible({"created_by": s.get("created_by"), "assignee": (s.get("owners") or [""])[0],
                             "assignees": s.get("owners") or []}, p)

    def _series_out(self, s: dict) -> dict:
        rule = recurring.parse(s["rule"])
        out = {k: s.get(k) for k in ("id", "title", "notes", "created_by", "owners", "mode", "rotate", "rule",
                                     "time", "after_done", "approved", "status", "next_due", "current",
                                     "created_at", "updated_at")}
        out["label"] = recurring.label(rule, s.get("time", ""))
        out["label_en"] = recurring.label(rule, s.get("time", ""), "en")
        if s.get("rotate") and s.get("owners"):
            out["next_turn"] = s["owners"][s.get("turn", 0) % len(s["owners"])]
        return out

    def add_series(self, creator: Person, title: str, people: list[Person], rule: str, time: str = "",
                   notes: str = "", memo_id: str | None = None, mode: str = "any", rotate: bool = False,
                   after_done: bool = False, now: datetime | None = None) -> dict:
        """A recurring task. Its first occurrence is made at once (so it shows in the list), the rest on
        their day. Returns that first occurrence, with "series" (the rule as the app shows it)."""
        title = (title or "").strip()
        if not title:
            raise TaskError(400, "title is required")
        try:
            r, tm = recurring.parse(rule), recurring.clean_time(time)
        except recurring.RuleError as e:
            raise TaskError(400, str(e)) from None
        people = [p for p in people if p is not None] or [creator]
        ids = list(dict.fromkeys(p.id for p in people))
        if rotate and len(ids) < 2:
            rotate = False                                # taking turns needs two people
        if after_done and r.freq != "every":
            after_done = False                            # "N days after it was done" only fits every:N
        local = self._today(now)
        start = recurring.first(r, local, tm)
        r = recurring.settle(r, start)
        s = {"id": "s" + uuid.uuid4().hex[:9], "title": title[:300], "notes": (notes or "").strip()[:2000],
             "created_by": creator.id, "owners": ids, "mode": "all" if mode == "all" else "any",
             "rotate": bool(rotate), "turn": 0, "rule": r.text(), "time": tm, "after_done": bool(after_done),
             "approved": creator.is_parent or ids == [creator.id], "status": "active", "next_due": None,
             "current": None, "points": None, "memo_id": memo_id, "created_at": _now(), "updated_at": _now()}
        ruled = effort_mod.rule_rating(title, "task", people[0])
        if ruled is not None:
            s["points"] = ruled
        with self._locked():
            data = self._read()
            data["series"].append(s)
            t = self._spawn(data, s, start)
            s["next_due"] = None if after_done else recurring.after(r, start).isoformat()
            self._write(data)
        return dict(t, series=self._series_out(s))

    def make_recurring(self, actor: Person, task_id: str, rule: str, time: str = "", rotate: bool = False,
                       now: datetime | None = None) -> dict:
        """Turn an existing one-time task into a recurring one: it stays as the first occurrence (on its own
        day, or today), and the next ones follow the rule. Whoever created it, the admin, or a parent of the
        children it is for. Returns the task, with "series"."""
        try:
            r, tm = recurring.parse(rule), recurring.clean_time(time)
        except recurring.RuleError as e:
            raise TaskError(400, str(e)) from None
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or not self.visible(t, actor):
                raise TaskError(404, "no such task")
            if t.get("series_id"):
                raise TaskError(409, "this task repeats already")
            if t.get("kind", "task") != "task" or t.get("status") not in LIVE:
                raise TaskError(409, "only an open task can repeat")
            ids = owners(t)
            if actor.id != t["created_by"] and not actor.admin and not (
                    actor.is_parent and all((p := self.family.get(i)) is not None and not p.is_parent for i in ids)):
                raise TaskError(403, "only whoever created it (or a parent) can make it repeat")
            due = t.get("due") or ""
            tm = tm or (due[11:16] if len(due) >= 16 else "")
            local = self._today(now)
            start = date.fromisoformat(due[:10]) if due else recurring.first(r, local, tm)
            r = recurring.settle(r, start)
            creator = self.family.get(t["created_by"]) or actor
            s = {"id": "s" + uuid.uuid4().hex[:9], "title": t["title"], "notes": t.get("notes", ""),
                 "created_by": t["created_by"], "owners": ids, "mode": t.get("mode", "any"),
                 "rotate": bool(rotate) and len(ids) > 1, "turn": 1 if rotate and len(ids) > 1 else 0,
                 "rule": r.text(), "time": tm, "after_done": False,
                 "approved": t["status"] == "open" or creator.is_parent or ids == [creator.id],
                 "status": "active", "next_due": recurring.after(r, start).isoformat(), "current": t["id"],
                 "points": dict(t["points"]) if t.get("points") else None, "memo_id": t.get("memo_id"),
                 "created_at": _now(), "updated_at": _now()}
            if s["rotate"]:
                _set_owners(t, [self.family.get(ids[0])], "any")   # this time: the first one's turn
            data["series"].append(s)
            t["series_id"], t["repeat"] = s["id"], recurring.label(r, tm)
            t["due"] = start.isoformat() + (f"T{tm}" if tm else "")
            t["updated_at"] = _now()
            self._write(data)
            return dict(self._decorate([t], actor)[0], series=self._series_out(s))

    def _spawn(self, data: dict, s: dict, day: date) -> dict:
        """Make one occurrence of a series (inside the lock)."""
        ids = s["owners"]
        if s.get("rotate") and len(ids) > 1:
            ids = [ids[s.get("turn", 0) % len(ids)]]
            s["turn"] = s.get("turn", 0) + 1
        people = [p for p in (self.family.get(i) for i in ids) if p is not None] \
            or [self.family.get(s["created_by"]) or self.family.admin]
        due = day.isoformat() + (f"T{s['time']}" if s.get("time") else "")
        t = {"id": uuid.uuid4().hex[:10], "title": s["title"], "notes": s.get("notes", ""),
             "assignee": people[0].id, "created_by": s["created_by"],
             "status": "open" if s.get("approved") else "requested",
             "due": due, "snoozed_until": None, "created_at": _now(), "updated_at": _now(),
             "done_at": None, "done_by": None, "memo_id": s.get("memo_id"),
             "series_id": s["id"], "repeat": recurring.label(recurring.parse(s["rule"]), s.get("time", ""))}
        _set_owners(t, people, s.get("mode"))
        if s.get("points"):
            t["points"] = dict(s["points"])
        data["tasks"].append(t)
        s["current"], s["updated_at"] = t["id"], _now()
        return t

    def _schedule_after_done(self, s: dict, at: str) -> None:
        r = recurring.parse(s["rule"])
        done_day = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(self.tz).date()
        s["next_due"] = recurring.after(r, done_day).isoformat()

    def roll(self, now: datetime | None = None) -> int:
        """Make the occurrences whose day has come. One still open from before is quietly marked "missed"
        (no coins taken, nothing shown). After a long gap (PC off) only the latest occurrence is made.
        Returns how many were made. Cheap when there's nothing to do: it writes only on a change."""
        today = self._today(now).date()
        data = self._read()
        if not any(x.get("status") == "active" and x.get("next_due") and x["next_due"] <= today.isoformat()
                   for x in data["series"]):
            return 0
        made = 0
        with self._locked():
            data = self._read()
            for s in data["series"]:
                if s.get("status") != "active" or not s.get("next_due"):
                    continue
                day = date.fromisoformat(s["next_due"])
                if day > today:
                    continue
                r = recurring.parse(s["rule"])
                while recurring.after(r, day) <= today:          # skipped while the PC was off
                    day = recurring.after(r, day)
                    if s.get("rotate"):
                        s["turn"] = s.get("turn", 0) + 1         # their turn passed too
                cur = next((t for t in data["tasks"] if t["id"] == s.get("current")), None)
                if cur is not None and cur.get("status") in LIVE:
                    cur["status"], cur["updated_at"] = "missed", _now()    # parts already done stay paid
                self._spawn(data, s, day)
                s["next_due"] = None if s.get("after_done") else recurring.after(r, day).isoformat()
                made += 1
            if made:
                self._write(data)
        return made

    def series_act(self, actor: Person, series_id: str, action: str, fields: dict | None = None) -> dict:
        """stop (ends it and removes the open occurrence), pause, resume, edit (title, notes, rule, time,
        owners, mode, rotate). Whoever created it, the admin, or a parent of the children it is for."""
        if action not in SERIES_ACTIONS:
            raise TaskError(400, f"unknown action {action}")
        f = fields or {}
        with self._locked():
            data = self._read()
            s = next((x for x in data["series"] if x["id"] == series_id and x.get("status") != "ended"), None)
            if s is None or not self._series_visible(s, actor):
                raise TaskError(404, "no such recurring task")
            if actor.id != s["created_by"] and not actor.admin and not (
                    actor.is_parent and all((p := self.family.get(i)) is not None and not p.is_parent
                                            for i in s["owners"])):
                raise TaskError(403, "only whoever created it (or a parent) can change it")
            cur = next((t for t in data["tasks"] if t["id"] == s.get("current")), None)
            live = cur if cur is not None and cur.get("status") in LIVE else None
            if action == "stop":
                s["status"] = "ended"
                if live is not None and not live.get("done_parts"):
                    live["status"], live["updated_at"] = "deleted", _now()
            elif action == "pause":
                s["status"] = "paused"
            elif action == "resume":
                if s["status"] == "paused":
                    s["status"] = "active"
                    r = recurring.parse(s["rule"])
                    start = recurring.first(r, self._today(), s.get("time", ""))
                    if live is not None and (live.get("due") or "")[:10] >= start.isoformat():
                        start = recurring.after(r, date.fromisoformat(live["due"][:10]))
                    s["next_due"] = None if s.get("after_done") and live is not None else start.isoformat()
            else:
                self._edit_series(s, actor, f, live)
            s["updated_at"] = _now()
            self._write(data)
            return self._series_out(s)

    def _edit_series(self, s: dict, actor: Person, f: dict, live: dict | None) -> None:
        if str(f.get("title") or "").strip():
            s["title"] = str(f["title"]).strip()[:300]
        if "notes" in f:
            s["notes"] = str(f["notes"] or "").strip()[:2000]
        if f.get("rule") or "time" in f:
            try:
                r = recurring.parse(f.get("rule") or s["rule"])
                tm = recurring.clean_time(f["time"]) if "time" in f else s.get("time", "")
            except recurring.RuleError as e:
                raise TaskError(400, str(e)) from None
            start = recurring.first(r, self._today(), tm)
            r = recurring.settle(r, start)
            s["rule"], s["time"] = r.text(), tm
            if s.get("after_done") and r.freq != "every":
                s["after_done"] = False
            if live is not None and (live.get("due") or "")[:10] >= start.isoformat():
                start = recurring.after(r, date.fromisoformat(live["due"][:10]))
            if not (s.get("after_done") and live is not None):
                s["next_due"] = start.isoformat()
        ids = f.get("owners") or f.get("assignees")
        if ids:
            people = self.resolve_people(ids)
            s["owners"] = [p.id for p in people]
            if not actor.is_parent and any(p.id != actor.id for p in people):
                s["approved"] = False
        if f.get("mode") in ("any", "all"):
            s["mode"] = f["mode"]
        if "rotate" in f:
            s["rotate"] = bool(f["rotate"]) and len(s["owners"]) > 1
        if live is not None and not live.get("done_parts"):     # the open one follows the change
            live["title"], live["notes"] = s["title"], s.get("notes", "")
            live["repeat"] = recurring.label(recurring.parse(s["rule"]), s.get("time", ""))
            if ids and not s.get("rotate"):
                _set_owners(live, self.resolve_people(s["owners"]), s.get("mode"))
            live["updated_at"] = _now()

    # ---- Jar ideas ----
    def add_idea(self, creator: Person, title: str, notes: str = "", memo_id: str | None = None) -> dict:
        """An idea for Jar, for the admin to accept (the one who suggested it gets idea coins) or decline."""
        title = (title or "").strip()
        if not title:
            raise TaskError(400, "title is required")
        admin = self.family.admin
        t = {"id": uuid.uuid4().hex[:10], "title": title[:300], "notes": (notes or "").strip()[:2000],
             "assignee": admin.id, "created_by": creator.id,
             "status": "open" if creator.id == admin.id else "requested",
             "due": None, "snoozed_until": None, "created_at": _now(), "updated_at": _now(),
             "done_at": None, "done_by": None, "memo_id": memo_id, "kind": "idea",
             "points": {"no_coins": True, "rated_by": "rule", "reason": "Jar idea"}}
        with self._locked():
            data = self._read()
            data["tasks"].append(t)
            self._write(data)
        return t

    def _credit_idea(self, t: dict, stage: str) -> dict | None:
        if self.points is None or not hasattr(self.points, "credit_idea"):
            return None
        award = self.points.credit_idea(t, stage)
        if stage == "accepted" and award is None and t.get("created_by") != self.family.admin.id:
            t["idea_credit"] = "none"         # cap reached, or a parent's idea (see [points] idea_* settings)
        elif award is not None:
            t.setdefault("idea_credit", {})
            if isinstance(t["idea_credit"], dict):
                t["idea_credit"][stage] = award.get("coins", 0)
        return award

    @staticmethod
    def _add_note(t: dict, actor: Person, text: str) -> None:
        thread = t.setdefault("thread", [])
        thread.append({"id": (max((c["id"] for c in thread), default=0) + 1), "by": actor.id,
                       "text": text.strip()[:2000], "at": _now(), "ask": False})

    # ---- notes and questions on a task ----
    @staticmethod
    def counterpart(t: dict, actor: Person) -> str:
        """Who a question from `actor` goes to: the one doing it, or (from them) whoever asked for it."""
        ids = owners(t)
        if actor.id not in ids:
            return ids[0] if ids else ""
        if t.get("created_by") != actor.id:
            return t.get("created_by") or ""
        return next((i for i in ids if i != actor.id), "")

    def comment(self, actor: Person, task_id: str, text: str, ask: bool = False) -> dict:
        """A note on a task. ask=True sends it as a question: the task shows up for the other side
        until they answer. Any note from the person a question waits on answers it."""
        text = (text or "").strip()
        if not text:
            raise TaskError(400, "the note is empty")
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or not self.visible(t, actor):
                raise TaskError(404, "no such task")
            thread = t.setdefault("thread", [])
            n = {"id": (max((c["id"] for c in thread), default=0) + 1), "by": actor.id, "text": text[:2000],
                 "at": _now(), "ask": bool(ask)}
            thread.append(n)
            if t.get("waiting_on") == actor.id:
                t["waiting_on"] = None                       # answered
            if ask:
                to = self.counterpart(t, actor)
                if not to:
                    raise TaskError(400, "this is your own task: there's nobody to ask")
                t["waiting_on"] = to
            t["updated_at"] = _now()
            self._write(data)
            return t

    def edit_comment(self, actor: Person, task_id: str, comment_id: int, text: str) -> dict:
        text = (text or "").strip()
        with self._locked():
            data = self._read()
            t = next((x for x in data["tasks"] if x["id"] == task_id and x.get("status") != "deleted"), None)
            if t is None or not self.visible(t, actor):
                raise TaskError(404, "no such task")
            c = next((c for c in t.get("thread", []) if c["id"] == comment_id), None)
            if c is None:
                raise TaskError(404, "no such note")
            if c["by"] != actor.id:
                raise TaskError(403, "only who wrote a note can change it")
            if text:
                c.update(text=text[:2000], edited=_now())
            else:
                t["thread"].remove(c)                          # emptied: removed
            t["updated_at"] = _now()
            self._write(data)
            return t

    def find(self, actor: Person, query: str = "", person: Person | None = None, limit: int = 8) -> list[dict]:
        """Open tasks the actor can see, best word match first: for "move the dentist to Thursday"."""
        words = [w for w in re.split(r"\W+", (query or "").casefold()) if len(w) >= 2]
        found = []
        for t in self.snapshot(actor)["tasks"]:
            if t.get("status") not in ("open", "requested"):
                continue
            if person is not None and person.id not in owners(t):
                continue
            text = (t["title"] + " " + (t.get("notes") or "")).casefold()
            # Hebrew prefixes (ה, ל, ב, ש, ו…) glue onto words, so substring matches count too.
            score = sum(1 for w in words if w in text or (len(w) > 3 and w[1:] in text))
            if words and score == 0:
                continue
            found.append((score, t.get("updated_at", ""), t))
        found.sort(key=lambda x: (x[0], x[1]), reverse=True)     # best match, then most recently touched
        return [t for _, _, t in found[:limit]]

    # ---- calendar events a task stands for (a vague event's "add details or delete it") ----
    def link_event(self, task_id: str, event: dict) -> None:
        """Tie a calendar event to a task: deleting the task deletes the event. No coins for it."""
        with self._locked():
            data = self._read()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    t["event"] = dict(event)
                    t["points"] = {"no_coins": True, "rated_by": "rule", "reason": "event follow-up"}
                    self._write(data)
                    return

    def events_to_delete(self) -> list[dict]:
        """Deleted tasks whose calendar event is still on the calendar."""
        return [t for t in self._read()["tasks"]
                if t.get("status") == "deleted" and t.get("event") and not t["event"].get("removed")]

    def event_removed(self, task_id: str, note: str = "") -> None:
        with self._locked():
            data = self._read()
            for t in data["tasks"]:
                if t["id"] == task_id and t.get("event"):
                    t["event"]["removed"] = note or _now()
                    self._write(data)
                    return

    def forget_memo(self, actor: Person, memo_id: str) -> int:
        """Re-filing a memo: delete the still-open tasks its earlier filing created, so nothing doubles."""
        n = 0
        with self._locked():
            data = self._read()
            for t in data["tasks"]:
                if t.get("memo_id") == memo_id and t.get("status") in ("open", "requested") \
                        and (t["created_by"] == actor.id or actor.admin):
                    t["status"], t["updated_at"] = "deleted", _now()
                    n += 1
            for x in data["series"]:
                if x.get("memo_id") == memo_id and x.get("status") != "ended" \
                        and (x["created_by"] == actor.id or actor.admin):
                    x["status"], x["updated_at"] = "ended", _now()
                    n += 1
            if n:
                self._write(data)
        return n

    def import_markdown(self, owner: Person) -> int:
        """First run with the family list: bring over the open "- [ ]" lines of the old Tasks.md
        (as the owner's tasks) and keep the old file as "Tasks (before family list).md"."""
        if self.path.exists() or not self.markdown or not self.markdown.exists():
            return 0
        text = self.markdown.read_text(encoding="utf-8")
        found = []
        for line in text.splitlines():
            m = re.match(r"^\s*- \[ \] (.+)$", line)
            if not m:
                continue
            body = m.group(1)
            d = re.search(r"📅 (\d{4}-\d{2}-\d{2})", body)
            tm = re.search(r"⏰ (\d{2}:\d{2})", body)
            memo = re.search(r"memo (\d{2}:\d{2})", body)
            title = re.sub(r"\s*\(\[\[.*?\]\]\)\s*$", "", body)
            title = re.sub(r"\s*(📅 \S+|⏰ \S+)", "", title).strip()
            due = (d.group(1) + ("T" + tm.group(1) if tm else "")) if d else None
            found.append((title, due))
        backup = self.markdown.with_name("Tasks (before family list).md")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        with self._locked():
            data = self._read()
            for title, due in found:
                if title:
                    data["tasks"].append({"id": uuid.uuid4().hex[:10], "title": title, "notes": "",
                                          "assignee": owner.id, "created_by": owner.id, "status": "open",
                                          "due": due, "snoozed_until": None, "created_at": _now(),
                                          "updated_at": _now(), "done_at": None, "done_by": None, "memo_id": None})
            self._write(data)
        return len(found)

    def purge_old(self, days: int = 60) -> int:
        """Drop done/declined/deleted tasks older than `days` from the JSON (Tasks.md keeps nothing old)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._locked():
            data = self._read()
            keep = [t for t in data["tasks"]
                    if t.get("status") in ("open", "requested") or (t.get("updated_at") or "") >= cutoff]
            n = len(data["tasks"]) - len(keep)
            if n:
                data["tasks"] = keep
                self._write(data)
        return n

    # ---- Tasks.md ----
    def to_markdown(self, tasks: list[dict]) -> str:
        name = lambda pid: (self.family.get(pid).name if self.family.get(pid) else pid)  # noqa: E731
        lines = ["# Tasks", "", "*Written by Jar from the family task list. Tick tasks in the phone app; "
                 "edits made here are overwritten.*", ""]
        people = list(self.family.people)
        for pid in people + sorted({i for t in tasks for i in owners(t)} - set(people)):
            mine = [t for t in tasks if pid in owners(t) and t.get("status") in ("open", "requested", "done")]
            if not mine:
                continue
            lines.append(f"## {name(pid)}")
            mine.sort(key=lambda t: (t["status"] == "done", t.get("due") or "9999", t["created_at"]))
            recent = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            for t in mine:
                if t["status"] == "done" and (t.get("done_at") or "") < recent:
                    continue
                box = "x" if t["status"] == "done" or pid in (t.get("done_parts") or {}) else " "
                s = f"- [{box}] {t['title']}"
                if len(owners(t)) > 1:
                    s += (" 👥 " + ", ".join(name(i) for i in owners(t) if i != pid)
                          + (" (each of us)" if shared_mode(t) == "all" else " (one of us)"))
                if t.get("due"):
                    d, _, tm = t["due"].partition("T")
                    s += f" 📅 {d}" + (f" ⏰ {tm}" if tm else "")
                if t.get("repeat"):
                    s += f" 🔁 {t['repeat']}"
                if t.get("kind") == "idea":
                    s = s.replace(f"- [{box}] ", f"- [{box}] 💡 ", 1)
                if t["created_by"] != pid:
                    s += f" — from {name(t['created_by'])}"
                if t["status"] == "requested":
                    s += f" (new idea for {name(t['assignee'])})" if t.get("kind") == "idea" else " (waiting for a parent's OK)"
                if t.get("memo_id"):
                    s += f" `memo {t['memo_id'][:6]}`"
                if t["status"] == "done" and t.get("done_at"):
                    s += f" ✅ {t['done_at'][:10]}"
                lines.append(s)
            lines.append("")
        return "\n".join(lines) + "\n"
