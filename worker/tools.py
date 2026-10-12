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


HE_WEEKDAYS = {"שני": 0, "שלישי": 1, "רביעי": 2, "חמישי": 3, "שישי": 4, "שבת": 5, "ראשון": 6}
EN_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _date(value: str | None, today: date | None = None) -> date | None:
    """YYYY-MM-DD, or the day as said: "מחר", "מחרתיים", "יום רביעי", "ברביעי", "Thursday", "tomorrow".
    Weekday words become the next such day (today's weekday = next week), so the model never has to
    do calendar arithmetic, which small models get wrong."""
    if not value:
        return None
    v = value.strip()
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    if today is None:
        return None
    w = re.sub(r"[^\w\s]", " ", v.casefold())
    words = w.split()
    if not words:
        return None
    if any(x in words for x in ("today", "היום", "הערב", "tonight")):
        return today
    if "מחרתיים" in words or "day after tomorrow" in w:
        return today + timedelta(days=2)
    if any(x in words for x in ("tomorrow", "מחר")):
        return today + timedelta(days=1)
    target = None
    for word in words:
        bare = re.sub(r"^(ו?ב?יום|ב|ה|ו)", "", word) if word not in HE_WEEKDAYS else word
        if word in EN_WEEKDAYS:
            target = EN_WEEKDAYS[word]
        elif word in HE_WEEKDAYS:
            target = HE_WEEKDAYS[word]
        elif bare in HE_WEEKDAYS:
            target = HE_WEEKDAYS[bare]
        if target is not None:
            break
    if target is None:
        return None
    return today + timedelta(days=(target - today.weekday()) % 7 or 7)


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
    join_info: object = None    # callable(person) -> {"download", "pair_link"}: for get_join_instructions
    transcript: str = ""        # what was said: lets day words in the memo correct a miscomputed date

    def _day(self, value: str | None):
        """A date for a tool call. If the model gave YYYY-MM-DD but the memo names exactly one weekday and the
        date falls on another weekday, trust the words (models miscount weekdays)."""
        today = self.ctx.recorded_local.date()
        d = _date(value, today)
        if d is None or not value or not re.match(r"^\s*\d{4}-\d{2}-\d{2}", value) or not self.transcript:
            return d
        said = {_date(w, today) for w in re.findall(r"\S+", self.transcript)
                if _date(w, today) is not None and not re.match(r"^\d{4}-", w)
                and re.sub(r"^(ו?ב?יום|ב|ה|ו)", "", w.casefold().strip(",.")) in (*HE_WEEKDAYS, *EN_WEEKDAYS)}
        if len(said) == 1:
            want = next(iter(said))
            if want.weekday() != d.weekday() and abs((want - d).days) < 7:
                return want
        return d

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
        d, tm = self._day(due_date), _time(due_time)
        if due_date and not d:
            raise ToolError("due_date: give the day as said (e.g. 'מחר', 'יום רביעי', 'Thursday') or YYYY-MM-DD")
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

    def get_join_instructions(self, for_person: str = "", language: str = "he") -> str:
        """Facts for a "how to install / join Jar" message: download link, the person's own pairing link."""
        who = self.family.resolve(for_person) if (self.family is not None and for_person) else None
        info = self.join_info(who) if callable(self.join_info) else {
            "download": "https://github.com/noless-zz/jar/releases/latest", "pair_link": ""}
        dl, pair = info.get("download", ""), info.get("pair_link", "")
        if (language or "he").lower().startswith("en"):
            steps = [f"1. On your Android phone open {dl} and tap the .apk file under Assets to install Jar "
                     "(allow installing from the browser if asked).",
                     "2. Open Jar and allow notifications and the microphone."]
            if pair:
                steps.append(f"3. Copy this personal link, then in Jar tap ⋮ → Settings & pairing → Paste link:\n{pair}")
                steps.append("4. At home it works over the Wi-Fi. To use it outside, install Tailscale and I'll sign it in.")
            else:
                steps.append("3. Then ask me for your personal pairing code.")
            steps.append("In Jar you see your tasks, tick them off, and record a voice memo with the mic button.")
        else:
            steps = [f"1. בטלפון (אנדרואיד) פתחו את הקישור {dl} ולחצו על קובץ ה-apk שתחת Assets כדי להתקין את Jar "
                     "(אם שואלים – לאשר התקנה מהדפדפן).",
                     "2. פותחים את Jar ומאשרים התראות ומיקרופון."]
            if pair:
                steps.append(f"3. מעתיקים את הקישור האישי הזה, ובאפליקציה: ⋮ ← הגדרות וצימוד ← הדבקת קישור:\n{pair}")
                steps.append("4. בבית זה עובד דרך ה-WiFi. כדי שיעבוד גם בחוץ צריך להתקין Tailscale – אני אחבר.")
            else:
                steps.append("3. אחר כך תבקשו ממני את קוד הצימוד האישי.")
            steps.append("ב-Jar רואים את המשימות, מסמנים מה בוצע, ומקליטים הודעה קולית בכפתור המיקרופון.")
        note = "" if pair else " (no personal pairing link: not a family member in config.toml)"
        return "Put these steps in the message (you may add a friendly opening line):" + note + "\n" + "\n".join(steps)

    def draft_join_instructions(self, for_person: str, greeting: str = "", language: str = "he") -> str:
        """The whole "how to install and join Jar" WhatsApp message in one step: greeting + real steps
        + the person's own pairing link, prepared on the speaker's phone."""
        facts = self.get_join_instructions(for_person, language)
        steps = facts.split("\n", 1)[1] if "\n" in facts else facts
        who = self.family.resolve(for_person) if self.family is not None else None
        hello = (greeting or "").strip() or (
            (f"היי {who.name}! " if who else "היי! ") + "ככה מתקינים את Jar ומתחברים:"
            if not (language or "he").lower().startswith("en") else
            (f"Hi {who.name}! " if who else "Hi! ") + "Here's how to install Jar and join:")
        return self.draft_whatsapp(hello + "\n\n" + steps, to=who.name if who else for_person)

    def search_notes(self, query: str) -> str:
        """Find things the speaker saved before (notes, ideas, lesson ideas) to use in a message or task."""
        words = [w for w in re.split(r"\W+", (query or "").casefold()) if len(w) >= 2]
        if not words:
            raise ToolError("query is required")
        hits = []
        for p in self.root.rglob("*.md"):
            if p.name in ("Tasks.md",) or "Memos" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            low = text.casefold()
            score = sum(1 for w in words if w in low or (len(w) > 3 and w[1:] in low))
            if score:
                i = min((low.find(w) for w in words if w in low), default=0)
                snippet = text[max(0, i - 120): i + 280].replace("\n", " ").strip()
                hits.append((score, p, snippet))
        hits.sort(key=lambda h: -h[0])
        if not hits:
            return "nothing found in the saved notes."
        return "\n".join(f"- {h[1].relative_to(self.root)}: …{h[2]}…" for h in hits[:3])

    def draft_whatsapp(self, text: str, to: str = "") -> str:
        """A WhatsApp message prepared on the speaker's phone: they open it and press Send themselves."""
        if self.store is None:
            raise ToolError("there is no task list to put the message on")
        if not text.strip():
            raise ToolError("text is required")
        name, phone = self.family.phone_for(to) if to.strip() else ("", "")
        for a in self.actions:
            if a.get("tool") == "draft_whatsapp" and a.get("to") == name:
                # One prepared message per person per memo: the model sometimes writes a second one.
                return f"ok: the message to {name or 'them'} is already prepared; nothing more to do"
        title = f"WhatsApp → {name}" if name else "WhatsApp message"
        t = self.store.add(self.speaker, title, self.speaker, None, "", self.ctx.memo_id,
                           kind="message", message=text.strip(), to=name, phone=phone)
        where = f" to {name}" + ("" if phone else " (pick the chat in WhatsApp)") if name else " (pick the chat in WhatsApp)"
        summary = f"WhatsApp message ready{where}: tap Send in WhatsApp in the app"
        self.actions.append({"tool": "draft_whatsapp", "summary": summary, "task_id": t["id"], "file": "Tasks.md",
                             "to": name})
        return f"ok: {summary}"

    def find_tasks(self, query: str = "", for_person: str = "") -> str:
        """For corrections by voice: the open tasks that match, with ids for update_task."""
        if self.store is None:
            raise ToolError("there is no task list")
        who = self.family.resolve(for_person) if for_person else None
        found = self.store.find(self.speaker, query, who)
        if not found:
            return "no open task matches. (If the memo is a NEW task, use add_task.)"
        name = lambda pid: self.family.get(pid).name if self.family.get(pid) else pid  # noqa: E731
        lines = [f"- id={t['id']} | {t['title']} | for {name(t['assignee'])}"
                 + (f" | due {t['due'].replace('T', ' ')}" if t.get("due") else "") for t in found]
        return "matching open tasks:\n" + "\n".join(lines)

    def update_task(self, task_id: str, title: str = "", due_date: str = "", due_time: str = "",
                    for_person: str = "", status: str = "") -> str:
        """Change, move, finish or cancel an existing task (id from find_tasks)."""
        from .taskstore import TaskError
        if self.store is None:
            raise ToolError("there is no task list")
        task_id = (task_id or "").strip().removeprefix("id=")
        fields, did = {}, []
        if title.strip():
            fields["title"] = title.strip()
            did.append(f"renamed to “{title.strip()}”")
        d, tm = self._day(due_date), _time(due_time)
        if due_date and not d:
            raise ToolError("due_date: give the day as said (e.g. 'מחר', 'יום רביעי', 'Thursday') or YYYY-MM-DD")
        if tm and not d:
            d = self.ctx.recorded_local.date()
            if tm <= f"{self.ctx.recorded_local:%H:%M}":
                d += timedelta(days=1)
        if d:
            fields["due"] = f"{d.isoformat()}T{tm}" if tm else d.isoformat()
            did.append(f"due {fields['due'].replace('T', ' ')}")
        if for_person.strip():
            who = self.family.resolve(for_person)
            if who is None:
                raise ToolError(f"unknown person '{for_person}'")
            fields["assignee"] = who.id
            did.append(f"now for {who.name}")
        status = (status or "").strip().lower()
        try:
            if fields:
                t = self.store.act(self.speaker, task_id, "edit", fields=fields)
            if status in ("done", "finished", "complete"):
                t = self.store.act(self.speaker, task_id, "done")
                did.append("marked done")
            elif status in ("cancel", "cancelled", "delete", "deleted"):
                t = self.store.act(self.speaker, task_id, "delete")
                did.append("cancelled")
            elif status in ("open", "reopen"):
                t = self.store.act(self.speaker, task_id, "reopen")
                did.append("reopened")
        except TaskError as e:
            raise ToolError(f"{e} (use an id from find_tasks)") from e
        if not did:
            raise ToolError("nothing to change: give title, due_date/due_time, for_person or status")
        summary = f"task “{t['title']}”: " + ", ".join(did)
        self.actions.append({"tool": "update_task", "summary": summary, "task_id": t["id"], "file": "Tasks.md"})
        return f"ok: {summary}"

    def create_event(self, title: str, date: str, start_time: str = "", duration_min: int = 60,
                     location: str = "", notes: str = "", account: str = "personal") -> str:
        """In the account's real calendar when connected; otherwise an .ics file to double-click."""
        d, tm = self._day(date), _time(start_time)
        if not title.strip():
            raise ToolError("title is required")
        if not d:
            raise ToolError("date: give the day as said (e.g. 'מחר', 'יום רביעי', 'Thursday') or YYYY-MM-DD")
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
        tools = {k: v for k, v in tools.items()
                 if k in ("save_note", "add_task", "find_tasks", "update_task", "draft_whatsapp",
                          "draft_join_instructions", "search_notes")}
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
                  due_date=string("the day AS SAID ('מחר', 'יום רביעי', 'Thursday', 'today') or YYYY-MM-DD for an explicit "
                                  "calendar date ('15 באוקטובר'); empty if no day was said"),
                  due_time=string("HH:MM 24h if a time was mentioned, else empty"),
                  notes=string("extra details, optional")),
              "required": ["title"]},
             "internal", notes.add_task),
        Tool("draft_join_instructions", "Prepare a WhatsApp message to someone explaining how to install the "
             "Jar app and join (real download link + their own pairing link + steps). Use for any memo about "
             "sending someone instructions to install / join / set up Jar or 'the app'. It prepares the whole "
             "message, so don't call draft_whatsapp for it too.",
             {**s(for_person=FOR,
                  greeting=string("optional short opening line in the speaker's voice, e.g. 'היי ליבני, הנה מה "
                                  "שצריך כדי להתחבר לאפליקציה של המשפחה'"),
                  language={"type": "string", "enum": ["he", "en"], "description": "language of the message"}),
              "required": ["for_person"]},
             "internal", notes.draft_join_instructions),
        Tool("search_notes", "Search the notes the speaker saved before (ideas, information, lesson ideas) for "
             "facts to use in a message or task. Returns short snippets.",
             {**s(query=string("a few key words")), "required": ["query"]},
             "none", notes.search_notes),
        Tool("draft_whatsapp", "Prepare a WhatsApp message on the speaker's phone; they review it and press "
             "Send themselves (nothing is sent automatically). Use when the memo says to message, text or WhatsApp "
             "someone ('תשלח לסווטה ש…', 'write to Dana on WhatsApp…', 'תכתוב בקבוצה…').",
             {**s(text=string("the complete message, ready to send as-is, in the memo's language, written as the "
                              "speaker (first person). Include every detail the recipient needs (steps, links, "
                              "times, places) — never 'here are the instructions' without them"),
                  to=string("who it is for, as said (a family member's name or any contact name); empty if not said. "
                            "Never invent phone numbers")),
              "required": ["text"]},
             "internal", notes.draft_whatsapp),
        Tool("find_tasks", "Look up EXISTING open tasks by words in them. Use first when the memo changes, "
             "moves, finishes or cancels something already on the list ('move the dentist to Thursday', "
             "'סיימתי לתלות כביסה', 'בטל את התזכורת על החלב', 'Yoni already did the dishes').",
             {**s(query=string("a few key words of the task, in the memo's language"),
                  for_person=FOR),
              "required": ["query"]},
             "none", notes.find_tasks),
        Tool("update_task", "Change an existing task found with find_tasks: new title, new day/time, another "
             "person, or status done / cancel / reopen. Only the fields you give change.",
             {**s(task_id=string("the id from find_tasks"),
                  title=string("new title, or empty"),
                  due_date=string("new day AS SAID ('יום חמישי', 'מחר') or YYYY-MM-DD, or empty"),
                  due_time=string("new time HH:MM, or empty"),
                  for_person=FOR,
                  status={"type": "string", "enum": ["", "done", "cancel", "reopen"],
                          "description": "done = finished; cancel = no longer needed; empty = no change"}),
              "required": ["task_id"]},
             "internal", notes.update_task),
        Tool("create_event", "Create a calendar event: a meeting, appointment or anything at a set time.",
             {**s(title=string("event title"), date=string("the day AS SAID ('מחר', 'ביום רביעי', 'Thursday') or YYYY-MM-DD for an explicit calendar date"),
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
