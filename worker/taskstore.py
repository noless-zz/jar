"""The family's task list: one JSON file shared by the worker (adds tasks from memos) and the
server (the phone apps read and tick them). A lock file keeps the two processes from clobbering
each other. notes/Tasks.md is rewritten from it after every change, so Obsidian still shows it.

A task:
    id, title, notes, assignee, created_by, status, due, snoozed_until,
    created_at, updated_at, done_at, done_by, memo_id
status:  open | done | requested (a child asked someone; waits for a parent) | declined
due / snoozed_until:  local time, "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" (the family's time zone)

Who sees what: your own tasks, tasks you gave someone, and (parents only) the children's tasks.
A task you give yourself is private to you.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .family import Family, Person

WHEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
ACTIONS = ("done", "reopen", "snooze", "accept", "decline", "delete", "edit")


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
    def __init__(self, path: Path, family: Family, markdown: Path | None = None):
        self.path, self.family, self.markdown = path, family, markdown
        self.lock_path = path.with_suffix(".lock")

    # ---- storage ----
    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.lock_path, "a+")
        try:
            for _ in range(200):                     # up to ~10 s
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise TaskError(503, "task list is busy, try again")
            yield
        finally:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            f.close()                                # also releases flock

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
        return {"rev": data.get("rev", 0), "tasks": tasks}

    def add(self, creator: Person, title: str, assignee: Person | None = None, due: str | None = None,
            notes: str = "", memo_id: str | None = None) -> dict:
        title = (title or "").strip()
        if not title:
            raise TaskError(400, "title is required")
        assignee = assignee or creator
        status = "requested" if (not creator.is_parent and assignee.id != creator.id) else "open"
        t = {"id": uuid.uuid4().hex[:10], "title": title[:300], "notes": (notes or "").strip()[:2000],
             "assignee": assignee.id, "created_by": creator.id, "status": status,
             "due": clean_when(due), "snoozed_until": None, "created_at": _now(), "updated_at": _now(),
             "done_at": None, "done_by": None, "memo_id": memo_id}
        with self._locked():
            data = self._read()
            data["tasks"].append(t)
            self._write(data)
        return t

    def act(self, actor: Person, task_id: str, action: str, until: str | None = None,
            fields: dict | None = None) -> dict:
        if action not in ACTIONS:
            raise TaskError(400, f"unknown action {action}")
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
                t.update(status="done", done_at=_now(), done_by=actor.id, snoozed_until=None)
            elif action == "reopen":
                t.update(status="open", done_at=None, done_by=None)
            elif action == "snooze":
                t["snoozed_until"] = clean_when(until)
            elif action == "delete":
                if actor.id != t["created_by"] and not actor.admin:
                    raise TaskError(403, "only whoever created it can delete it")
                t["status"] = "deleted"
            elif action == "edit":
                f = fields or {}
                if "title" in f and str(f["title"]).strip():
                    t["title"] = str(f["title"]).strip()[:300]
                if "due" in f:
                    t["due"] = clean_when(f["due"])
                    t["snoozed_until"] = None
                if "notes" in f:
                    t["notes"] = str(f["notes"] or "").strip()[:2000]
                if f.get("assignee") and f["assignee"] != t["assignee"]:
                    who = self.family.get(f["assignee"])
                    if who is None:
                        raise TaskError(400, "no such family member")
                    t["assignee"] = who.id
                    if not actor.is_parent and who.id != actor.id:
                        t["status"] = "requested"     # a child handing it to someone else: a parent OKs it
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
