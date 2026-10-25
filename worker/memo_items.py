"""Deleting one thing a memo made, from the phone's "My memos" screen (Noam's idea fb206325c3).

Each memo keeps the list of what Jar did with it ("actions"). From the app, its owner can take back one of them:
  - a task, a WhatsApp message or an idea it added → the task is deleted (same rules as deleting it in the app);
  - a note → the note file goes;
  - an event (family calendar, Outlook / Google) or an email draft → removed there; a calendar file (.ics) or a
    draft saved as a note → the file goes.
Things that changed something that was already there (a note on a task, an update) can't be taken back this way.

The server does what it can by itself (tasks, files) and leaves calendar and email to the worker, which has the
accounts: it writes a small request into data/deletes/, the worker carries it out on its next poll and marks the
action "removed" (or "remove_failed"). The memo's action gets "removing" in the meantime.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

TASK_TOOLS = ("add_task", "draft_whatsapp", "suggest_idea")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kind(a: dict) -> str | None:
    """What deleting this action means: "task", "file", "family_event", "event", "draft" — or None (can't)."""
    tool = a.get("tool")
    f = (a.get("file") or "").replace("\\", "/")
    if tool in TASK_TOOLS and a.get("task_id"):
        return "task"
    if tool == "save_note" and f.startswith("Inbox/"):
        return "file"
    if tool == "family_event" and a.get("event_id"):
        return "family_event"
    if tool == "create_event":
        if a.get("event_id"):
            return "event"
        if f.endswith(".ics"):
            return "file"
    if tool == "draft_email":
        if a.get("draft_id"):
            return "draft"
        if f.startswith("Email drafts/"):
            return "file"
    return None


def items(actions: list) -> list[dict]:
    """For the app: each action with whether it can be deleted and whether it already was."""
    out = []
    for a in actions or []:
        if not isinstance(a, dict):
            out.append({"summary": str(a), "deletable": False})
            continue
        removed = a.get("removed")
        out.append({"summary": a.get("summary", ""), "tool": a.get("tool", ""),
                    "deletable": kind(a) is not None and not removed and not a.get("removing"),
                    "removed": bool(removed), "removing": bool(a.get("removing")) and not removed,
                    "failed": a.get("remove_failed", "")})
    return out


def notes_root(notes_dir: Path, person, admin: bool) -> Path:
    """Where this person's memos write: the admin's notes, everyone else's own folder (as the worker does)."""
    if admin:
        return notes_dir
    from .tools import slug
    return notes_dir / "Family" / slug(person.name)


def remove_file(root: Path, rel: str) -> bool:
    """Delete a note / .ics / draft file the memo wrote. Only inside the person's notes folder."""
    p = (root / rel).resolve()
    if root.resolve() not in p.parents:
        raise ValueError("outside the notes folder")
    if p.exists():
        p.unlink()
    return True


def save(meta_path: Path, meta: dict) -> None:
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, meta_path)


def queue(queue_dir: Path, memo_id: str, index: int) -> None:
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / f"{memo_id}_{index}.json").write_text(
        json.dumps({"memo": memo_id, "index": index, "at": time.time()}), encoding="utf-8")


def mark(meta: dict, index: int, ok: bool, problem: str = "") -> None:
    a = meta["actions"][index]
    a.pop("removing", None)
    if ok:
        a["removed"] = _now()
        a.pop("remove_failed", None)
    else:
        a["remove_failed"] = problem[:200]
