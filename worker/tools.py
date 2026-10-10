"""Endpoints the local model can call — phase 1 writes plain files only.

Each tool follows the plugin contract from the spec: a name, a description,
a JSON schema for its inputs, and a side_effect level the approval gate reads
(none / internal / external). Everything here is "internal": it writes to
your own notes folder, so nothing needs approval yet.

Files (Obsidian-compatible Markdown, so any vault or OneDrive folder works):
    Inbox/<date> <time> <title>.md   one file per note
    Tasks.md                         checklist, Obsidian Tasks syntax (📅 date)
    Calendar/<date> <time> <title>.ics + Calendar.md   double-click .ics to add to Outlook/Google
    Lesson ideas.md
    Deep work/<date> <title>.md      queued for the cloud model (not wired yet)
    Memos/<date>.md                  daily log: every transcript + what was done
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f#\[\]^]')


def slug(text: str, limit: int = 50) -> str:
    """A filename-safe title that keeps Hebrew letters."""
    s = ILLEGAL.sub("", text).strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    return (s[:limit].rstrip() or "untitled")


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _time(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", value)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


class ToolError(Exception):
    """Bad arguments: the message goes back to the model so it can fix the call."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    side_effect: str
    handler: Callable[..., str]

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


@dataclass
class MemoContext:
    """Who and when, so every file can link back to the memo that created it."""
    memo_id: str
    recorded_local: datetime


@dataclass
class Notes:
    root: Path
    tz: ZoneInfo
    ctx: MemoContext | None = None
    actions: list[dict] = field(default_factory=list)
    accounts: dict = field(default_factory=dict)   # "personal"/"school" -> connector (or None)
    store: object = None        # TaskStore (family task list); None = old Tasks.md-only mode
    family: object = None       # Family
    speaker: object = None      # Person who recorded the memo

    @property
    def restricted(self) -> bool:
        """Memos from family members other than the admin only get tasks and their own notes."""
        return self.speaker is not None and not getattr(self.speaker, "admin", True)

    # ---- helpers ----
    def _append(self, rel: str, text: str, header: str = "") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            if new and header:
                f.write(header + "\n\n")
            f.write(text)
        return p

    def _link(self) -> str:
        d = self.ctx.recorded_local.strftime("%Y-%m-%d")
        return f"[[Memos/{d}|memo {self.ctx.recorded_local:%H:%M}]]"

    def _record(self, tool: str, summary: str, path: Path, link: str = "") -> str:
        a = {"tool": tool, "summary": summary,
             "file": str(path.relative_to(self.root)).replace("\\", "/")}
        if link:
            a["link"] = link
        self.actions.append(a)
        return f"ok: {summary}"

    def _connector(self, account: str):
        """The connector for this role, or None (not configured) — callers fall back to files."""
        role = (account or "personal").strip().lower()
        return self.accounts.get(role)

    # ---- tools ----
    def save_note(self, title: str, body: str = "", tags: list[str] | None = None) -> str:
        if not title.strip():
            raise ToolError("title is required")
        t = self.ctx.recorded_local
        tag_list = [re.sub(r"\s+", "-", x.strip().lstrip("#")) for x in (tags or []) if x.strip()]
        front = ["---", f"created: {t:%Y-%m-%dT%H:%M}", f"memo: {self.ctx.memo_id}"]
        if tag_list:
            front.append("tags: [" + ", ".join(tag_list) + "]")
        front.append("---")
        name = f"Inbox/{t:%Y-%m-%d %H%M} {slug(title)}.md"
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p = p.with_name(p.stem + f" {uuid.uuid4().hex[:4]}.md")
        p.write_text("\n".join(front) + f"\n\n# {title.strip()}\n\n{body.strip()}\n\nSource: {self._link()}\n",
                     encoding="utf-8", newline="\n")
        return self._record("save_note", f"note “{title.strip()}”", p)

    def add_task(self, title: str, due_date: str = "", due_time: str = "", notes: str = "",
                 for_person: str = "") -> str:
        if not title.strip():
            raise ToolError("title is required")
        d, tm = _date(due_date), _time(due_time)
        if due_date and not d:
            raise ToolError("due_date must be YYYY-MM-DD")
        if tm and not d:
            d = self.ctx.recorded_local.date()
            if tm <= f"{self.ctx.recorded_local:%H:%M}":
                d += timedelta(days=1)          # "at 8" said in the evening means tomorrow
        if self.store is not None:
            return self._family_task(title.strip(), d, tm, notes.strip(), for_person)
        line = f"- [ ] {title.strip()}"
        if d:
            line += f" 📅 {d.isoformat()}"
        if tm:
            line += f" ⏰ {tm}"
        if notes.strip():
            line += f" — {notes.strip()}"
        p = self._append("Tasks.md", line + f" ({self._link()})\n", "# Tasks")
        when = f" due {d.isoformat()}{' ' + tm if tm else ''}" if d else ""
        return self._record("add_task", f"task “{title.strip()}”{when}", p)

    def _family_task(self, title: str, d, tm, notes: str, for_person: str) -> str:
        from .taskstore import TaskError
        who = self.family.resolve(for_person) if for_person else None
        if for_person and who is None and for_person.strip().lower() not in ("me", "self", "אני"):
            names = ", ".join(f"{p.id} ({p.name})" for p in self.family.people.values())
            raise ToolError(f"unknown person '{for_person}'. Use one of: {names}, or leave empty for the speaker")
        who = who or self.speaker
        due = f"{d.isoformat()}T{tm}" if d and tm else (d.isoformat() if d else None)
        try:
            t = self.store.add(self.speaker, title, who, due, notes, self.ctx.memo_id)
        except TaskError as e:
            raise ToolError(str(e)) from e
        when = (f" {d.isoformat()} {tm}" if tm else f" on {d.isoformat()}") if d else ""
        alert = (f"the phone reminds at {d.isoformat()} {tm}" if tm else
                 "in the morning summary that day" if d else "no time given: in the morning summary")
        if who.id == self.speaker.id:
            summary = f"task “{title}”{when} ({alert})"
        elif t["status"] == "requested":
            summary = f"request to {who.name}: “{title}”{when} (waits for a parent's OK)"
        else:
            summary = f"task for {who.name}: “{title}”{when} (on {who.name}'s phone; {alert})"
        md = self.store.markdown or (self.root / "Tasks.md")
        a = {"tool": "add_task", "summary": summary, "task_id": t["id"]}
        try:
            a["file"] = str(md.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            a["file"] = "Tasks.md"
        self.actions.append(a)
        return f"ok: {summary}"

    def create_event(self, title: str, date: str, start_time: str = "", duration_min: int = 60,
                     location: str = "", notes: str = "", account: str = "personal") -> str:
        """In the account's real calendar when connected; otherwise an .ics file to double-click."""
        d, tm = _date(date), _time(start_time)
        if not title.strip():
            raise ToolError("title is required")
        if not d:
            raise ToolError("date must be YYYY-MM-DD")
        try:
            duration = max(5, min(int(duration_min or 60), 24 * 60))
        except (TypeError, ValueError):
            duration = 60
        conn = self._connector(account)
        why_local = "not connected"
        if conn is not None:
            from .connectors import NotConnected
            try:
                r = conn.create_event(title.strip(), d, tm, duration, location.strip(), notes.strip())
                when = f"{d.isoformat()} {tm}" if tm else f"{d.isoformat()} (all day)"
                p = self._append("Calendar.md", f"- {when} · {title.strip()} → {r.summary}"
                                 f"{' ([open](' + r.link + '))' if r.link else ''} ({self._link()})\n",
                                 "# Calendar")
                return self._record("create_event", f"event “{title.strip()}” {when} in {r.summary}", p, r.link)
            except NotConnected as e:
                why_local = str(e)
            except Exception as e:  # noqa: BLE001 — the memo must not be lost because an API failed
                why_local = f"{type(e).__name__}: {e}"
        result = self._ics_event(title, d, tm, duration, location, notes)
        return result + f" (saved as .ics: {why_local})"

    def _ics_event(self, title: str, d, tm, duration: int, location: str = "", notes: str = "") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = f"{self.ctx.memo_id}-{uuid.uuid4().hex[:8]}@jar"
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Jar//memo worker//EN", "BEGIN:VEVENT",
                 f"UID:{uid}", f"DTSTAMP:{stamp}"]
        if tm:
            start = datetime.combine(d, datetime.strptime(tm, "%H:%M").time(), self.tz)
            end = start + timedelta(minutes=duration)
            fmt = lambda x: x.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
            lines += [f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        esc = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
        lines.append(f"SUMMARY:{esc(title.strip())}")
        if location.strip():
            lines.append(f"LOCATION:{esc(location.strip())}")
        lines.append(f"DESCRIPTION:{esc((notes.strip() + chr(10) if notes.strip() else '') + 'From Jar memo ' + self.ctx.memo_id)}")
        lines += ["END:VEVENT", "END:VCALENDAR"]
        ics = self.root / f"Calendar/{d.isoformat()} {(tm or 'all-day').replace(':', '')} {slug(title)}.ics"
        ics.parent.mkdir(parents=True, exist_ok=True)
        ics.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
        when = f"{d.isoformat()} {tm}" if tm else f"{d.isoformat()} (all day)"
        self._append("Calendar.md", f"- {when} · {title.strip()}"
                     f"{' @ ' + location.strip() if location.strip() else ''}"
                     f" → [[Calendar/{ics.name}]] ({self._link()})\n", "# Calendar drafts")
        return self._record("create_event", f"event “{title.strip()}” {when}", ics)

    def save_lesson_idea(self, idea: str, class_name: str = "", topic: str = "") -> str:
        if not idea.strip():
            raise ToolError("idea is required")
        tags = " · ".join(x.strip() for x in (class_name, topic) if x.strip())
        p = self._append("Lesson ideas.md",
                         f"- {self.ctx.recorded_local:%Y-%m-%d}{' · ' + tags if tags else ''}: "
                         f"{idea.strip()} ({self._link()})\n", "# Lesson ideas")
        return self._record("save_lesson_idea", f"lesson idea{' for ' + tags if tags else ''}", p)

    def escalate_deep_work(self, request: str, title: str = "") -> str:
        if not request.strip():
            raise ToolError("request is required")
        t = self.ctx.recorded_local
        name = title.strip() or request.strip()[:40]
        p = self.root / f"Deep work/{t:%Y-%m-%d %H%M} {slug(name)}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nstatus: queued\nmemo: {self.ctx.memo_id}\n---\n\n# {name}\n\n{request.strip()}\n\n"
                     f"Source: {self._link()}\n", encoding="utf-8", newline="\n")
        return self._record("escalate_deep_work", f"deep-work request “{name}” queued", p)

    def draft_email(self, subject: str, body: str, to: str = "", account: str = "personal") -> str:
        """A DRAFT in Outlook/Gmail — never sent. Without a connected account: a draft note."""
        if not subject.strip() or not body.strip():
            raise ToolError("subject and body are required")
        recipients = [a.strip() for a in re.split(r"[,;\s]+", to or "") if "@" in a]
        conn = self._connector(account)
        why_local = "not connected"
        if conn is not None:
            from .connectors import NotConnected
            try:
                r = conn.create_draft(recipients, subject.strip(), body.strip())
                p = self._append("Email drafts.md", f"- {self.ctx.recorded_local:%Y-%m-%d %H:%M} · "
                                 f"{subject.strip()}{' → ' + ', '.join(recipients) if recipients else ''}"
                                 f" · {r.summary}{' ([open](' + r.link + '))' if r.link else ''} ({self._link()})\n",
                                 "# Email drafts")
                who = f" to {', '.join(recipients)}" if recipients else " (add the recipient)"
                return self._record("draft_email", f"email draft “{subject.strip()}”{who} in {r.summary}", p, r.link)
            except NotConnected as e:
                why_local = str(e)
            except Exception as e:  # noqa: BLE001
                why_local = f"{type(e).__name__}: {e}"
        p = self.root / f"Email drafts/{self.ctx.recorded_local:%Y-%m-%d %H%M} {slug(subject)}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nto: {', '.join(recipients)}\naccount: {account}\nmemo: {self.ctx.memo_id}\n---\n\n"
                     f"# {subject.strip()}\n\n{body.strip()}\n\nSource: {self._link()}\n",
                     encoding="utf-8", newline="\n")
        return self._record("draft_email", f"email draft “{subject.strip()}” saved as a note ({why_local})", p)

    def log_memo(self, duration_ms: int, device: str, transcript: str, language: str, summary: str) -> None:
        """The daily memo log: always written, so nothing said is ever lost."""
        t = self.ctx.recorded_local
        done = "\n".join(f"- {a['summary']} → [[{a['file']}]]" for a in self.actions) or "- (no action)"
        quote = "\n".join("> " + line for line in (transcript or "(no speech)").splitlines())
        self._append(f"Memos/{t:%Y-%m-%d}.md",
                     f"## {t:%H:%M} · {duration_ms / 1000:.1f} s · {device} · {language or '?'}\n"
                     f"{quote}\n\n{done}\n{('*' + summary + '*' + chr(10)) if summary else ''}\n",
                     f"# Memos {t:%Y-%m-%d}")


def registry(notes: Notes) -> dict[str, Tool]:
    tools = _all_tools(notes)
    if notes.restricted:
        tools = {k: v for k, v in tools.items() if k in ("save_note", "add_task")}
    return tools


def _all_tools(notes: Notes) -> dict[str, Tool]:
    s = lambda **props: {"type": "object", "properties": props}  # noqa: E731
    string = lambda d: {"type": "string", "description": d}  # noqa: E731
    ACCOUNT = {"type": "string", "enum": ["personal", "school"],  # noqa: N806
               "description": "school = anything about school or work: classes, students, parents, staff, lessons, "
                              "grades; personal = everything else"}
    people = list(notes.family.people.values()) if notes.family is not None else []
    FOR = {"type": "string", "enum": [""] + [p.id for p in people],  # noqa: N806
           "description": "who should do it: " + ", ".join(f"{p.id} = {p.name}" for p in people)
                          + "; empty = the speaker themself"} if people else string("leave empty")
    tools = [
        Tool("save_note", "Save an idea, thought or piece of information as a note. "
             "Default choice when the memo is not a task, event, lesson idea or deep-work request.",
             {**s(title=string("short title in the memo's language"),
                  body=string("the note, cleaned up; keep all details"),
                  tags={"type": "array", "items": {"type": "string"}, "description": "1-3 short tags"}),
              "required": ["title", "body"]},
             "internal", notes.save_note),
        Tool("add_task", "Add a to-do or reminder. It appears in the family app on the phone of the person "
             "it is for, with a notification at the due time. Use for reminders, chores and things to do, "
             "also when asking a family member to do something.",
             {**s(title=string("the task, short and imperative, in the memo's language, without the person's name"),
                  for_person=FOR,
                  due_date=string("YYYY-MM-DD if a day was mentioned, else empty"),
                  due_time=string("HH:MM 24h if a time was mentioned, else empty"),
                  notes=string("extra details, optional")),
              "required": ["title"]},
             "internal", notes.add_task),
        Tool("create_event", "Create a calendar event: a meeting, appointment or anything at a set time.",
             {**s(title=string("event title"), date=string("YYYY-MM-DD"),
                  start_time=string("HH:MM 24h, empty for all-day"),
                  duration_min={"type": "integer", "description": "minutes, default 60"},
                  location=string("optional"), notes=string("optional"),
                  account=ACCOUNT),
              "required": ["title", "date"]},
             "internal", notes.create_event),
        Tool("draft_email", "Write an email DRAFT (it is not sent; the owner reviews and sends it). "
             "Use when the memo asks to email or write to someone.",
             {**s(subject=string("email subject in the memo's language"),
                  body=string("the full email text, polite and ready to send, in the memo's language"),
                  to=string("email address(es) ONLY if said explicitly in the memo, else empty"),
                  account=ACCOUNT),
              "required": ["subject", "body"]},
             "internal", notes.draft_email),
        Tool("save_lesson_idea", "Save a teaching idea for a class (math or software engineering).",
             {**s(idea=string("the idea, cleaned up"), class_name=string("e.g. 10th grade math, optional"),
                  topic=string("e.g. rational functions, optional")),
              "required": ["idea"]},
             "internal", notes.save_lesson_idea),
        Tool("escalate_deep_work", "Hand a big job (research, long drafting, comparisons, anything needing "
             "the web) to the cloud model. Use when the speaker says 'deep work' / 'עבודה עמוקה' or the task "
             "clearly needs research.",
             {**s(request=string("the full request, with all details from the memo"),
                  title=string("short title")),
              "required": ["request"]},
             "internal", notes.escalate_deep_work),
    ]
    return {t.name: t for t in tools}
