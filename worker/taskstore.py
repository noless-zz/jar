"""The family's task list: one JSON file shared by the worker (adds tasks from memos) and the
server (the phone apps read and tick them). A lock file keeps the two processes from clobbering
each other. notes/Tasks.md is rewritten from it after every change, so Obsidian still shows it.

A task:
    id, title, notes, assignee, created_by, status, due, snoozed_until,
    created_at, updated_at, done_at, done_by, memo_id
    points   {effort 1-10, minutes, category, chore_key, reason, rated_by, no_coins}: what it is worth
             (worker/effort.py rates it once; a parent can change it; coins are paid by worker/points.py)
status:  open | done | requested (a child asked someone; waits for a parent) | declined
due / snoozed_until:  local time, "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" (the family's time zone)

Who sees what: your own tasks, tasks you gave someone, and (parents only) the children's tasks.
A task you give yourself is private to you.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import effort as effort_mod
from .family import Family, Person
from .filelock import locked

WHEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
ACTIONS = ("done", "reopen", "snooze", "accept", "decline", "delete", "edit")


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


class TaskStore:
    def __init__(self, path: Path, family: Family, markdown: Path | None = None, points=None):
        self.path, self.family, self.markdown = path, family, markdown
        self.points = points              # PointsStore, or None (no coins)
        self.lock_path = path.with_suffix(".lock")

    # ---- storage ----
    @contextmanager
    def _locked(self):
        with locked(self.lock_path, lambda: TaskError(503, "task list is busy, try again")):
            yield

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"rev": 0, "tasks": []}

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
        if p.id in (t.get("assignee"), t.get("created_by")):
            return True
        a = self.family.get(t.get("assignee"))
        return p.is_parent and a is not None and not a.is_parent

    # ---- API ----
    def snapshot(self, p: Person) -> dict:
        data = self._read()
        tasks = [t for t in data["tasks"] if self.visible(t, p) and t.get("status") != "deleted"]
        tasks = self._decorate(tasks)
        return {"rev": data.get("rev", 0), "tasks": tasks}

    def _decorate(self, tasks: list[dict]) -> list[dict]:
        """Copies of the tasks with "coins": what a done task paid, or what an open one will pay
        (0 = nothing, or not rated yet), and "paid": true for the first."""
        if self.points is None:
            return tasks
        paid = self.points.paid_map()
        out = []
        for t in tasks:
            t = dict(t)
            if t["id"] in paid:
                t.update(coins=paid[t["id"]], paid=True)
            elif t.get("status") in ("open", "requested"):
                t["coins"] = self.points.preview(t)
            out.append(t)
        return out

    def add(self, creator: Person, title: str, assignee: Person | None = None, due: str | None = None,
            notes: str = "", memo_id: str | None = None, kind: str = "task", message: str = "",
            to: str = "", phone: str = "") -> dict:
        title = (title or "").strip()
        if not title:
            raise TaskError(400, "title is required")
        assignee = assignee or creator
        status = "requested" if (not creator.is_parent and assignee.id != creator.id) else "open"
        t = {"id": uuid.uuid4().hex[:10], "title": title[:300], "notes": (notes or "").strip()[:2000],
             "assignee": assignee.id, "created_by": creator.id, "status": status,
             "due": clean_when(due), "snoozed_until": None, "created_at": _now(), "updated_at": _now(),
             "done_at": None, "done_by": None, "memo_id": memo_id}
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
            if action in ("accept", "decline"):
                if t["status"] != "requested":
                    raise TaskError(409, "this task isn't waiting for approval")
                if not actor.is_parent:
                    raise TaskError(403, "a parent approves requests")
                t["status"] = "open" if action == "accept" else "declined"
            elif action == "done":
                if t["status"] == "requested" and not actor.is_parent:
                    raise TaskError(409, "still waiting for a parent to approve it")
                # An offline tick carries the time it was made ("at", epoch seconds): paid at that time.
                t.update(status="done", done_at=done_time((fields or {}).get("at")), done_by=actor.id,
                         snoozed_until=None)
                if self.points is not None:
                    award = self.points.pay(t, t["done_at"])
            elif action == "reopen":
                t.update(status="open", done_at=None, done_by=None)
                self._take_back(t, "reopened")
            elif action == "snooze":
                t["snoozed_until"] = clean_when(until)
            elif action == "delete":
                if actor.id != t["created_by"] and not actor.admin:
                    raise TaskError(403, "only whoever created it can delete it")
                t["status"] = "deleted"
                self._take_back(t, "deleted")
            elif action == "edit":
                f = fields or {}
                if "title" in f and str(f["title"]).strip():
                    t["title"] = str(f["title"]).strip()[:300]
                if "due" in f:
                    t["due"] = clean_when(f["due"])
                    t["snoozed_until"] = None
                if "notes" in f:
                    t["notes"] = str(f["notes"] or "").strip()[:2000]
                if "message" in f and t.get("kind") == "message":
                    t["message"] = str(f["message"] or "").strip()[:4000]
                if f.get("assignee") and f["assignee"] != t["assignee"]:
                    who = self.family.get(f["assignee"])
                    if who is None:
                        raise TaskError(400, "no such family member")
                    t["assignee"] = who.id
                    if not actor.is_parent and who.id != actor.id:
                        t["status"] = "requested"     # a child handing it to someone else: a parent OKs it
                    if t.get("status") == "done":
                        self._take_back(t, "reassigned")          # the new person didn't do it
                    elif (t.get("points") or {}).get("rated_by") in ("ai", "default"):
                        t.pop("points")                           # rated for someone else: rate again
                        ruled = effort_mod.rule_rating(t["title"], t.get("kind", "task"), who)
                        if ruled is not None:
                            t["points"] = ruled
            t["updated_at"] = _now()
            self._write(data)
            return dict(t, award=award) if award else t

    # ---- coins ----
    def _take_back(self, t: dict, why: str) -> None:
        if self.points is not None:
            self.points.reverse(t["id"], why)

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
            self._write(data)
        if self.points is not None:
            if effort is not None:
                self.points.remember(pts.get("chore_key", ""), effort, actor.id)
            if t.get("status") == "done":
                self.points.repay(t)
        return self._decorate([t])[0]

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
        out = self._decorate([t])[0]
        return dict(out, award=award) if award else out

    def _local_day(self, iso: str):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        tz = getattr(self.points, "tz", None)
        return (dt.astimezone(tz) if tz else dt).date()

    # ---- notes and questions on a task ----
    @staticmethod
    def counterpart(t: dict, actor: Person) -> str:
        """Who a question from `actor` goes to: the one doing it, or (from them) whoever asked for it."""
        if actor.id != t.get("assignee"):
            return t.get("assignee") or ""
        return t.get("created_by") if t.get("created_by") != actor.id else ""

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
            if person is not None and t["assignee"] != person.id:
                continue
            text = (t["title"] + " " + (t.get("notes") or "")).casefold()
            # Hebrew prefixes (ה, ל, ב, ש, ו…) glue onto words, so substring matches count too.
            score = sum(1 for w in words if w in text or (len(w) > 3 and w[1:] in text))
            if words and score == 0:
                continue
            found.append((score, t.get("updated_at", ""), t))
        found.sort(key=lambda x: (x[0], x[1]), reverse=True)     # best match, then most recently touched
        return [t for _, _, t in found[:limit]]

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
        for pid in people + sorted({t["assignee"] for t in tasks} - set(people)):
            mine = [t for t in tasks if t["assignee"] == pid and t.get("status") in ("open", "requested", "done")]
            if not mine:
                continue
            lines.append(f"## {name(pid)}")
            mine.sort(key=lambda t: (t["status"] == "done", t.get("due") or "9999", t["created_at"]))
            recent = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            for t in mine:
                if t["status"] == "done" and (t.get("done_at") or "") < recent:
                    continue
                box = "x" if t["status"] == "done" else " "
                s = f"- [{box}] {t['title']}"
                if t.get("due"):
                    d, _, tm = t["due"].partition("T")
                    s += f" 📅 {d}" + (f" ⏰ {tm}" if tm else "")
                if t["created_by"] != pid:
                    s += f" — from {name(t['created_by'])}"
                if t["status"] == "requested":
                    s += " (waiting for a parent's OK)"
                if t.get("memo_id"):
                    s += f" `memo {t['memo_id'][:6]}`"
                if t["status"] == "done" and t.get("done_at"):
                    s += f" ✅ {t['done_at'][:10]}"
                lines.append(s)
            lines.append("")
        return "\n".join(lines) + "\n"
