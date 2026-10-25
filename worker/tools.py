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

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

log = logging.getLogger("jar.tools")

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


# Words that say nothing about what an event is: a title made only of these is "vague".
VAGUE_EVENT_WORDS = {
    "אירוע", "אירועים", "משפחתי", "משפחתית", "משפחה", "המשפחה", "כולם", "לכולם", "של", "עם", "חדש", "חדשה",
    "מחר", "היום", "יום", "פגישה", "מפגש", "תזכורת", "משהו", "דבר", "ביומן", "יומן", "בלוח", "שנה",
    "event", "events", "family", "for", "everyone", "all", "the", "a", "new", "meeting", "reminder",
    "something", "tomorrow", "today", "day",
}


# Hebrew weekdays as said after "כל", "יום", "ימי" or a prefix letter: "כל ראשון ורביעי", "בימי שני וחמישי".
_HE_WEEKDAY = {"ראשון": 6, "שני": 0, "שלישי": 1, "רביעי": 2, "חמישי": 3, "שישי": 4, "שבת": 5}
_HE_WEEKDAY_RE = re.compile(r"(?:(?:כל|יום|ימי|בימי|ביום|ימים)\s+|[וב])(ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת)(?![א-ת])")


HE_HOURS = {"אחת": 1, "שתיים": 2, "שתים": 2, "שלוש": 3, "ארבע": 4, "חמש": 5, "שש": 6, "שבע": 7, "שמונה": 8,
            "תשע": 9, "עשר": 10, "אחת עשרה": 11, "אחת-עשרה": 11, "שתים עשרה": 12, "שתים-עשרה": 12}
_HOUR_WORDS = "|".join(sorted(map(re.escape, HE_HOURS), key=len, reverse=True))
_SPOKEN_TIME_RE = re.compile(r"(?<![א-ת])ב(" + _HOUR_WORDS + r")(?![א-ת])( וחצי| ורבע| ועשרה| ועשרים)?"
                             r"(?: (בבוקר|בערב|בלילה|אחר הצהריים|אחרי הצהריים|בצהריים))?")


def spoken_times(text: str) -> list[tuple[int, int, str]]:
    """Clock times said in Hebrew words: "בשמונה בערב" -> (20, 0, "evening"), "בעשר" -> (10, 0, "")."""
    out = []
    for m in _SPOKEN_TIME_RE.finditer(text or ""):
        hour = HE_HOURS[m.group(1)]
        minute = {" וחצי": 30, " ורבע": 15, " ועשרה": 10, " ועשרים": 20}.get(m.group(2) or "", 0)
        part = m.group(3) or ""
        if part == "בבוקר":
            hour, part = hour % 12, "morning"
        elif part in ("בערב", "אחר הצהריים", "אחרי הצהריים") or (part == "בלילה" and hour >= 7):
            hour, part = hour % 12 + 12, "evening"
        elif part == "בלילה":
            hour, part = hour % 12, "night"
        elif part == "בצהריים":
            hour, part = (12 if hour == 12 else hour % 12 + 12 if hour <= 3 else hour), "noon"
        out.append((hour, minute, part))
    return out


TURNS_RE = re.compile(r"(תורנות|בתורות|בתור\b|פעם זה פעם זה|פעם אחד פעם השני|take turns|taking turns)", re.I)
STOP_FOR_GOOD_RE = re.compile(r"(תפסיק|להפסיק|תפסיקי|כבר לא צריך|לא צריך יותר|יותר לא|אין צורך יותר|"
                              r"\bstop\b|no longer|not anymore|any more)", re.I)
ONLY_THIS_TIME_RE = re.compile(r"(רק היום|רק הפעם|היום לא|הפעם לא|just today|only today|this time)", re.I)


def spoken_weekdays(text: str) -> set[int]:
    """Weekday numbers (0 = Monday) named in a Hebrew memo, for checking a weekly rule against what was said."""
    found = set()
    for m in _HE_WEEKDAY_RE.finditer(text or ""):
        pre = text[max(0, m.start() - 1):m.start()]
        if m.group(0)[0] in "וב" and pre and pre not in " \t,":
            continue                                       # a ו/ב inside a word, not a prefix
        if m.group(1) == "שני" and re.match(r"\s*(ימים|שבועות|פעמים)", text[m.end():]):
            continue                                       # "שני ימים" = two days
        found.add(_HE_WEEKDAY[m.group(1)])
    return found



def _same_rule(a: str | None, b: str | None) -> bool:
    """Two ways of writing the same repeat ("every Monday" / "weekly:mon") count as one."""
    from . import recurring
    if a == b:
        return True
    try:
        return recurring.parse(a or "").text() == recurring.parse(b or "").text()
    except recurring.RuleError:
        return False


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
    _email_reminded: bool = False   # one "send the email" task per memo
    join_info: object = None    # callable(person) -> {"download", "pair_link"}: for get_join_instructions
    transcript: str = ""        # what was said: lets day words in the memo correct a miscomputed date
    family_account: object = None   # FamilyGoogle: the family's own Jar Gmail (sends to family only), or None

    def _day(self, value: str | None):
        """A date for a tool call. If the model gave YYYY-MM-DD or a weekday name but the memo names exactly one
        weekday and the date falls on another weekday, trust the words (models miscount weekdays, and sometimes
        pass the wrong weekday name: "יום חמישי" for a memo that said "ביום רביעי")."""
        today = self.ctx.recorded_local.date()
        d = _date(value, today)
        bare = re.sub(r"^(ו?ב?יום|ב|ה|ו)\s*", "", (value or "").casefold().strip(" ,."))
        if d is None or not value or not self.transcript or not (
                re.match(r"^\s*\d{4}-\d{2}-\d{2}", value) or bare in (*HE_WEEKDAYS, *EN_WEEKDAYS)):
            return d
        said = {_date(w, today) for w in re.findall(r"\S+", self.transcript)
                if _date(w, today) is not None and not re.match(r"^\d{4}-", w)
                and re.sub(r"^(ו?ב?יום|ב|ה|ו)", "", w.casefold().strip(",.")) in (*HE_WEEKDAYS, *EN_WEEKDAYS)}
        if len(said) == 1:
            want = next(iter(said))
            if want.weekday() != d.weekday() and abs((want - d).days) < 7:
                return want
        return d

    def _t(self, value: str | None) -> str | None:
        """A time for a tool call, checked against the one clock time the memo says in words ("בשמונה בערב"):
        models sometimes turn "eight in the evening" into 18:00."""
        tm = _time(value)
        said = spoken_times(self.transcript or "")
        if len(said) != 1:
            return tm
        hour, minute, part = said[0]
        if part:                                   # בבוקר / בערב / בלילה / אחר הצהריים: the words decide
            return f"{hour:02d}:{minute:02d}"
        if tm and int(tm[:2]) % 12 != hour % 12:   # no part of day said: keep the model's am/pm, fix the hour
            h = hour % 12 + (12 if int(tm[:2]) >= 12 else 0)
            return f"{h:02d}:{minute:02d}"
        return tm

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
                 for_person: str = "", also_for=None, together: str = "", repeat: str = "",
                 take_turns: bool = False) -> str:
        if not title.strip():
            raise ToolError("title is required")
        d, tm = self._day(due_date), self._t(due_time)
        if due_date and not d:
            raise ToolError("due_date: give the day as said (e.g. 'מחר', 'יום רביעי', 'Thursday') or YYYY-MM-DD")
        if (repeat or "").strip():
            if self.store is None:
                raise ToolError("recurring tasks need the family task list")
            return self._recurring_task(title.strip(), repeat.strip(), d, tm, notes.strip(), for_person,
                                        also_for, together, bool(take_turns))
        if tm and not d:
            d = self.ctx.recorded_local.date()
            if tm <= f"{self.ctx.recorded_local:%H:%M}":
                d += timedelta(days=1)          # "at 8" said in the evening means tomorrow
        if self.store is not None:
            if self._email_reminded and not for_person and re.search(r"(מייל|אימייל|e-?mail|\bmail)", title, re.I):
                return "ok: the task to send the email already exists"
            return self._family_task(title.strip(), d, tm, notes.strip(), for_person, also_for, together)
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

    def _task_people(self, for_person: str, also_for=None) -> list:
        names = ", ".join(f"{p.id} ({p.name})" for p in self.family.people.values())
        who = self.family.resolve(for_person) if for_person else None
        if for_person and who is None and for_person.strip().lower() not in ("me", "self", "אני"):
            raise ToolError(f"unknown person '{for_person}'. Use one of: {names}, or leave empty for the speaker")
        people = [who or self.speaker]
        if isinstance(also_for, str):
            also_for = [x for x in re.split(r"[,\s]+", also_for) if x]
        for name in also_for or []:
            other = self.speaker if str(name).strip().lower() in ("me", "self", "אני") else self.family.resolve(str(name))
            if other is None:
                raise ToolError(f"unknown person '{name}' in also_for. Use: {names}")
            if other not in people:
                people.append(other)
        return people

    def _recurring_task(self, title: str, repeat: str, d, tm, notes: str, for_person: str, also_for,
                        together: str, take_turns: bool) -> str:
        """A task that comes back (every day, every Sunday…): the first one now, the next ones on their day."""
        from . import recurring
        from .taskstore import TaskError
        people = self._task_people(for_person, also_for)
        if TURNS_RE.search(self.transcript or ""):
            named = self._named_people()
            ids = {p.id for p in named} | {getattr(self.speaker, "id", "")}
            if len(named) >= 2 and (len(people) < 2 or all(p.id in ids for p in people)):
                people, take_turns = named, True  # "תורנות … ליבנה ואלונה": the model missed the turns or the names
        if take_turns and not (for_person or "").strip() and len(people) >= 3 and people[0] is self.speaker:
            people = people[1:]               # "תורנות … ליבנה ואלונה": the named ones take turns, not the speaker
        rule = repeat
        try:
            r = recurring.parse(repeat)
        except recurring.RuleError as e:
            raise ToolError(f"{e}") from e
        said = spoken_weekdays(self.transcript)
        if r.freq == "weekly" and said and set(r.days) != said:
            r = recurring.Rule("weekly", days=tuple(sorted(said)))   # the days as said beat the model's guess
            rule = r.text()
        if d is not None and r.freq in ("weekly", "monthly") and not (r.days or r.dom):
            rule = recurring.settle(r, d).text()           # "every week" said with a day: that weekday
        same = next((x for x in self.store._read()["series"]
                     if x.get("memo_id") == self.ctx.memo_id and x.get("status") != "ended"
                     and x.get("owners") == [p.id for p in people] and _same_rule(x.get("rule"), rule)), None)
        if same is not None:                 # the model asked twice (once per day said): one series is enough
            return f"ok: this memo already made that recurring task (“{same['title']}”, {same['rule']}); nothing more to do"
        try:
            t = self.store.add_series(self.speaker, title, people, rule, tm or "", notes, self.ctx.memo_id,
                                      mode="all" if together == "all" else "any", rotate=take_turns,
                                      now=self.ctx.recorded_local)
        except TaskError as e:
            raise ToolError(str(e)) from e
        ser = t["series"]
        group = ", ".join(p.name for p in people)
        how = " taking turns" if ser.get("rotate") else (" (each of them)" if len(people) > 1 and together == "all"
                                                          else "")
        first = t["due"].replace("T", " ")
        wait = " (waits for a parent's OK)" if t["status"] == "requested" else ""
        summary = f"recurring task “{title}” 🔁 {ser['label_en']} for {group}{how}, first {first}{wait}"
        self.actions.append({"tool": "add_task", "summary": summary, "task_id": t["id"],
                             "series_id": t["series_id"], "file": "Tasks.md"})
        return f"ok: {summary}"

    def _named_people(self) -> list:
        """Family members the memo names (names or aliases, with a Hebrew prefix letter allowed), in order said."""
        text = self.transcript or ""
        found = []
        for p in self.family.people.values() if self.family is not None else []:
            names = [p.name, p.id, *getattr(p, "aliases", [])]
            pos = [m.start() for n in names if n and len(n) >= 2
                   for m in re.finditer(r"(?<![א-תA-Za-z])[ולבהש]{0,2}" + re.escape(n) + r"(?![א-תA-Za-z])", text)]
            if pos:
                found.append((min(pos), p))
        return [p for _, p in sorted(found, key=lambda x: x[0])]

    def suggest_idea(self, title: str, details: str = "") -> str:
        """An idea for Jar itself, for the admin to accept or decline."""
        from .taskstore import TaskError
        if self.store is None:
            return self.save_note(title, details or title, ["jar-idea"])
        try:
            t = self.store.add_idea(self.speaker, title.strip(), details.strip(), self.ctx.memo_id)
        except TaskError as e:
            raise ToolError(str(e)) from e
        admin = self.family.admin
        mine = self.speaker.id == admin.id
        summary = (f"💡 Jar idea “{t['title']}”" + ("" if mine else f" sent to {admin.name}; coins if accepted"))
        self.actions.append({"tool": "suggest_idea", "summary": summary, "task_id": t["id"], "file": "Tasks.md"})
        return f"ok: {summary}"

    def _family_task(self, title: str, d, tm, notes: str, for_person: str, also_for=None,
                     together: str = "") -> str:
        from .taskstore import TaskError
        people = self._task_people(for_person, also_for)
        who = people[0]
        same = next((t for t in self.store._read()["tasks"]
                     if t.get("memo_id") == self.ctx.memo_id and t.get("status") in ("open", "requested")
                     and t.get("title", "").strip() == title.strip() and t.get("assignee") == who.id), None)
        if same is not None:                 # the model called add_task twice for the same thing
            return f"ok: this memo already made that task (“{same['title']}”); nothing more to do"
        mode = "all" if together == "all" else "any"
        due = f"{d.isoformat()}T{tm}" if d and tm else (d.isoformat() if d else None)
        try:
            t = self.store.add(self.speaker, title, people, due, notes, self.ctx.memo_id, mode=mode)
        except TaskError as e:
            raise ToolError(str(e)) from e
        if len(people) > 1:
            group = ", ".join(p.name for p in people)
            how = "each of them" if mode == "all" else "any one of them"
            when = (f" {d.isoformat()} {tm}" if tm else f" on {d.isoformat()}") if d else ""
            wait = " (waits for a parent's OK)" if t["status"] == "requested" else ""
            summary = f"shared task for {group} ({how}): “{title}”{when}{wait}"
            self.actions.append({"tool": "add_task", "summary": summary, "task_id": t["id"], "file": "Tasks.md"})
            return f"ok: {summary}"
        when = (f" {d.isoformat()} {tm}" if tm else f" on {d.isoformat()}") if d else ""
        alert = (f"the phone reminds at {d.isoformat()} {tm}" if tm else
                 "in the morning summary that day" if d else "no time given: in the morning summary")
        if who.id == self.speaker.id:
            summary = f"task “{title}”{when} ({alert})"
            if t.get("area_suggest") and self.family.get(t["area_suggest"]):
                summary += (f"; it's in {self.family.get(t['area_suggest']).name}'s area of responsibility: the app "
                            "offers to move it to them (they or a parent approve)")
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
        from . import join
        who = self.family.resolve(for_person) if (self.family is not None and for_person) else None
        info = self.join_info(who) if callable(self.join_info) else {"download": join.DOWNLOAD, "pair_link": ""}
        steps = join.steps(info.get("download", join.DOWNLOAD), info.get("pair_link", ""),
                           info.get("join_url", ""), language)
        note = "" if info.get("pair_link") else " (no personal pairing link: not a family member in config.toml)"
        return "Put these steps in the message (you may add a friendly opening line):" + note + "\n" + "\n".join(steps)

    def draft_join_instructions(self, for_person: str, greeting: str = "", language: str = "he") -> str:
        """The whole "how to install and join Jar" WhatsApp message in one step: greeting + real steps
        + the person's own pairing link, prepared on the speaker's phone."""
        from . import join
        who = self.family.resolve(for_person) if self.family is not None else None
        info = self.join_info(who) if callable(self.join_info) else {"download": join.DOWNLOAD, "pair_link": ""}
        text = join.message(who.name if who else "", info.get("download", join.DOWNLOAD), info.get("pair_link", ""),
                            info.get("join_url", ""), language, greeting)
        return self.draft_whatsapp(text, to=who.name if who else for_person)

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
        from .taskstore import owners
        name = lambda pid: self.family.get(pid).name if self.family.get(pid) else pid  # noqa: E731
        lines = [f"- id={t['id']} | {t['title']} | for {', '.join(name(i) for i in owners(t))}"
                 + (f" | due {t['due'].replace('T', ' ')}" if t.get("due") else "")
                 + (f" | 🔁 recurring ({t['repeat']})" if t.get("repeat") else "")
                 + (" | 💡 Jar idea" if t.get("kind") == "idea" else "") for t in found]
        return "matching open tasks:\n" + "\n".join(lines)

    def update_task(self, task_id: str, title: str = "", due_date: str = "", due_time: str = "",
                    for_person: str = "", status: str = "", repeat: str = "", take_turns: bool = False) -> str:
        """Change, move, finish or cancel an existing task (id from find_tasks)."""
        from .taskstore import TaskError
        if self.store is None:
            raise ToolError("there is no task list")
        task_id = (task_id or "").strip().removeprefix("id=")
        st = (status or "").strip().lower()
        if st in ("cancel", "cancelled", "delete", "deleted") and STOP_FOR_GOOD_RE.search(self.transcript or "") \
                and not ONLY_THIS_TIME_RE.search(self.transcript or ""):
            t0 = next((x for x in self.store.snapshot(self.speaker)["tasks"] if x["id"] == task_id), None)
            if t0 is not None and t0.get("series_id"):
                st = "stop_repeating"            # "תפסיק להזכיר…", "כבר לא צריך": the whole recurring task
        if st in ("stop_repeating", "stop") or (repeat or "").strip():
            t = next((x for x in self.store.snapshot(self.speaker)["tasks"] if x["id"] == task_id), None)
            if t is None:
                raise ToolError("no such task (use an id from find_tasks)")
            rule = repeat.strip()
            if rule:
                from . import recurring
                try:
                    r = recurring.parse(rule)
                except recurring.RuleError as e:
                    raise ToolError(str(e)) from e
                said = spoken_weekdays(self.transcript)
                if r.freq == "weekly" and said and set(r.days) != said:
                    rule = recurring.Rule("weekly", days=tuple(sorted(said))).text()   # the days as said
            if not t.get("series_id"):
                if st in ("stop_repeating", "stop") or not rule:
                    raise ToolError("that task doesn't repeat (use an id of a 🔁 task from find_tasks)")
                try:                                   # a one-time task from now on comes back
                    out = self.store.make_recurring(self.speaker, t["id"], rule, self._t(due_time) or "",
                                                    bool(take_turns))
                except TaskError as e:
                    raise ToolError(str(e)) from e
                summary = f"task “{t['title']}” now repeats 🔁 {out['series']['label_en']}, next {out['series']['next_due']}"
                self.actions.append({"tool": "update_task", "summary": summary, "task_id": t["id"],
                                     "series_id": out["series_id"], "file": "Tasks.md"})
                return f"ok: {summary}"
            try:
                if st in ("stop_repeating", "stop"):
                    self.store.series_act(self.speaker, t["series_id"], "stop")
                    summary = f"recurring task “{t['title']}” stopped"
                else:
                    f = {"rule": rule}
                    if self._t(due_time):
                        f["time"] = self._t(due_time)
                    ser = self.store.series_act(self.speaker, t["series_id"], "edit", f)
                    summary = f"recurring task “{t['title']}” now 🔁 {ser['label_en']}"
            except TaskError as e:
                raise ToolError(str(e)) from e
            self.actions.append({"tool": "update_task", "summary": summary, "task_id": t["id"], "file": "Tasks.md"})
            return f"ok: {summary}"
        fields, did = {}, []
        if title.strip():
            fields["title"] = title.strip()
            did.append(f"renamed to “{title.strip()}”")
        d, tm = self._day(due_date), self._t(due_time)
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

    def note_on_task(self, task_id: str, text: str, ask: bool = False) -> str:
        """A note or a question on an existing task (id from find_tasks)."""
        from .taskstore import TaskError
        if self.store is None:
            raise ToolError("there is no task list")
        try:
            t = self.store.comment(self.speaker, (task_id or "").strip().removeprefix("id="), text, bool(ask))
        except TaskError as e:
            raise ToolError(f"{e} (use an id from find_tasks)") from e
        to = self.family.get(t.get("waiting_on")) if (ask and self.family is not None) else None
        summary = (f"question to {to.name} on “{t['title']}”: {text.strip()}" if to
                   else f"note on “{t['title']}”: {text.strip()}")
        self.actions.append({"tool": "note_on_task", "summary": summary, "task_id": t["id"], "file": "Tasks.md"})
        return f"ok: {summary}"

    def create_event(self, title: str, date: str, start_time: str = "", duration_min: int = 60,
                     location: str = "", notes: str = "", account: str = "personal", invite=None) -> str:
        """In the account's real calendar when connected; otherwise an .ics file to double-click.
        invite (family members) or a memo from anyone but the admin: the family calendar, with invitations."""
        if self.family_account is not None and self.family is not None and (invite or self.restricted):
            return self.family_event(title, date, invite or [], start_time, duration_min, location, notes)
        d, tm = self._day(date), self._t(start_time)
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
                r = conn.create_event(title.strip(), d, tm, duration, location.strip(), self._event_notes(notes))
                when = f"{d.isoformat()} {tm}" if tm else f"{d.isoformat()} (all day)"
                p = self._append("Calendar.md", f"- {when} · {title.strip()} → {r.summary}"
                                 f"{' ([open](' + r.link + '))' if r.link else ''} ({self._link()})\n",
                                 "# Calendar")
                out = self._record("create_event", f"event “{title.strip()}” {when} in {r.summary}", p, r.link)
                if r.id:      # so the memo screen can delete it again
                    self.actions[-1].update(event_id=r.id, account=(account or "personal").strip().lower())
                return out
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

    # ---- what every calendar event says about where it came from ----
    def _event_footer(self) -> str:
        """Who asked for the event, when, and what they said: the event explains itself."""
        who = getattr(self.speaker, "name", "") or "?"
        when = f" · {self.ctx.recorded_local:%d/%m %H:%M}" if self.ctx else ""
        lines = [f"נוצר ע״י Jar לבקשת {who}{when}"]
        if self.transcript.strip():
            lines.append(f"מה נאמר: “{self.transcript.strip()}”")
        return "\n".join(lines)

    def _event_notes(self, notes: str) -> str:
        notes = (notes or "").strip()
        return (notes + "\n\n" if notes else "") + self._event_footer()

    def _vague_event(self, title: str, notes: str = "", location: str = "") -> bool:
        """An event whose title says nothing about what it is ("אירוע משפחתי", "event for everyone")."""
        if (notes or "").strip() or (location or "").strip():
            return False
        words = [w for w in re.split(r"[\s\-–—,.:;!?\"'״׳“”()]+", (title or "").lower()) if w]
        return all(w in VAGUE_EVENT_WORDS or (w[0] in "והלבמש" and w[1:] in VAGUE_EVENT_WORDS) for w in words)

    def _vague_followup(self, title: str, d, tm, r) -> str:
        """A task for whoever asked: add what the event is, or delete it (deleting the task deletes the event)."""
        if self.store is None or self.speaker is None:
            return ""
        day = f"{d:%d/%m}" + (f" {tm}" if tm else "")
        task_notes = ("האירוע נוצר בלי פרטים. מה האירוע? הוסיפו פרטים ביומן" + (f": {r.link}" if r.link else "")
                      + "\nלא צריך אותו? מחקו את המשימה הזו והאירוע יימחק מהיומן של כולם.")
        due = None
        if self.ctx and self.ctx.recorded_local.hour < 20 and d >= self.ctx.recorded_local.date():
            due = f"{self.ctx.recorded_local:%Y-%m-%d}T20:00"
        try:
            t = self.store.add(self.speaker, f"להוסיף פרטים לאירוע “{title}” ({day}) או למחוק אותו",
                               self.speaker, due, task_notes, self.ctx.memo_id if self.ctx else None)
            if r.id:
                self.store.link_event(t["id"], {"id": r.id, "link": r.link, "title": title, "date": d.isoformat()})
        except Exception as e:  # noqa: BLE001 — the event is made; a missing follow-up is not worth failing for
            log.warning("vague event follow-up failed: %s", e)
            return ""
        self.actions.append({"tool": "add_task", "summary": f"task for {self.speaker.name}: add details to "
                             f"“{title}” or delete it", "task_id": t["id"], "file": "Tasks.md"})
        return (" — NOTE: the event has no details. A task asks the speaker to add what it is or delete it;"
                " tell them that in your answer, and ask what the event is.")

    # ---- the family's own Jar account: sends by itself, family members only ----
    def _family_people(self, who) -> list:
        """Family members from ids/names (empty or "all" = everyone)."""
        if isinstance(who, str):
            who = [x for x in re.split(r"[,\s]+", who) if x]
        names = ", ".join(f"{p.id} ({p.name})" for p in self.family.people.values())
        if not who or any(str(w).lower() in ("all", "everyone", "כולם") for w in who):
            return list(self.family.people.values())
        out = []
        for w in who:
            p = self.speaker if str(w).strip().lower() in ("me", "self", "אני") else self.family.resolve(str(w))
            if p is None:
                raise ToolError(f"unknown person '{w}'. Use: {names}, or 'all'")
            if p not in out:
                out.append(p)
        return out

    def family_event(self, title: str, date: str, who=None, start_time: str = "", duration_min: int = 60,
                     location: str = "", notes: str = "") -> str:
        """A family event on the family calendar, with an invitation to each family member it involves
        (who empty = just the speaker; "all" = everyone)."""
        d, tm = self._day(date), self._t(start_time)
        if not title.strip():
            raise ToolError("title is required")
        if not d:
            raise ToolError("date: give the day as said (e.g. 'מחר', 'יום רביעי', 'Thursday') or YYYY-MM-DD")
        people = self._family_people(who) if who else []
        if self.speaker is not None and self.speaker not in people:
            people.insert(0, self.speaker)               # whoever said it is part of it
        emails = [p.email for p in people if "@" in getattr(p, "email", "")]
        try:
            duration = max(5, min(int(duration_min or 60), 24 * 60))
        except (TypeError, ValueError):
            duration = 60
        why = "the family account isn't set up"
        if self.family_account is not None:
            from .connectors import NotConnected, NotFamily
            try:
                r = self.family_account.create_family_event(title.strip(), d, tm, duration, emails,
                                                            location.strip(), self._event_notes(notes))
                when = f"{d.isoformat()} {tm}" if tm else f"{d.isoformat()} (all day)"
                names = ", ".join(p.name for p in people if "@" in getattr(p, "email", ""))
                p = self._append("Calendar.md", f"- {when} · {title.strip()} → family calendar, invited {names}"
                                 f"{' ([open](' + r.link + '))' if r.link else ''} ({self._link()})\n", "# Calendar")
                out = self._record("family_event", f"family event “{title.strip()}” {when}, invited {names}", p, r.link)
                if r.id:
                    self.actions[-1]["event_id"] = r.id     # so re-filing the memo can take the event back
                if self._vague_event(title, notes, location):
                    out += self._vague_followup(title.strip(), d, tm, r)
                return out
            except (NotConnected, NotFamily) as e:
                why = str(e)
            except Exception as e:  # noqa: BLE001 — the memo must not be lost because an API failed
                why = f"{type(e).__name__}: {e}"
        return self._ics_event(title, d, tm, duration, location, notes) + f" (saved as .ics: {why})"

    def email_family(self, subject: str, body: str, who=None) -> str:
        """An email SENT at once from the family Jar account to family members (never anyone else)."""
        if not subject.strip() or not body.strip():
            raise ToolError("subject and body are required")
        people = [p for p in self._family_people(who) if p is not self.speaker] or self._family_people(who)
        emails = [p.email for p in people if "@" in getattr(p, "email", "")]
        why = "the family account isn't set up"
        if self.family_account is not None:
            from .connectors import NotConnected, NotFamily
            try:
                r = self.family_account.send(emails, subject.strip(), body.strip())
                names = ", ".join(p.name for p in people if "@" in getattr(p, "email", ""))
                p = self._append("Family email.md", f"- {self.ctx.recorded_local:%Y-%m-%d %H:%M} · {subject.strip()}"
                                 f" → {names} ({self._link()})\n", "# Sent to the family")
                return self._record("email_family", f"email “{subject.strip()}” {r.summary} to {names}", p)
            except (NotConnected, NotFamily) as e:
                why = str(e)
            except Exception as e:  # noqa: BLE001
                why = f"{type(e).__name__}: {e}"
        p = self.root / f"Email drafts/{self.ctx.recorded_local:%Y-%m-%d %H%M} {slug(subject)}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nto: {', '.join(emails)}\nmemo: {self.ctx.memo_id}\n---\n\n# {subject.strip()}\n\n"
                     f"{body.strip()}\n\nSource: {self._link()}\n", encoding="utf-8", newline="\n")
        return self._record("email_family", f"family email “{subject.strip()}” NOT sent, saved as a note ({why})", p)

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
                out = self._record("draft_email", f"email draft “{subject.strip()}”{who} in {r.summary}", p, r.link)
                if r.id:      # so the memo screen can delete it again
                    self.actions[-1].update(draft_id=r.id, account=(account or "personal").strip().lower())
                return out + self._send_reminder(subject.strip(), recipients, r.summary, r.link)
            except NotConnected as e:
                why_local = str(e)
            except Exception as e:  # noqa: BLE001
                why_local = f"{type(e).__name__}: {e}"
        p = self.root / f"Email drafts/{self.ctx.recorded_local:%Y-%m-%d %H%M} {slug(subject)}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nto: {', '.join(recipients)}\naccount: {account}\nmemo: {self.ctx.memo_id}\n---\n\n"
                     f"# {subject.strip()}\n\n{body.strip()}\n\nSource: {self._link()}\n",
                     encoding="utf-8", newline="\n")
        out = self._record("draft_email", f"email draft “{subject.strip()}” saved as a note ({why_local})", p)
        return out + self._send_reminder(subject.strip(), recipients, "Jar's notes", "")

    def _send_reminder(self, subject: str, recipients: list[str], where: str, link: str) -> str:
        """Drafts are never sent by Jar, so every draft also gets a task "send it", ticked off once sent."""
        if self.store is None or self._email_reminded:
            return ""
        hebrew = bool(re.search(r"[\u0590-\u05FF]", subject + " " + (self.transcript or "")))
        to = ", ".join(recipients)
        title = (f"לשלוח את המייל: {subject}" + (f" ({to})" if to else "")) if hebrew else \
                (f"Send the email: {subject}" + (f" ({to})" if to else ""))
        notes = (f"הטיוטה מחכה ב-{where}" if hebrew else f"The draft is waiting in {where}") + (f": {link}" if link else "")
        try:
            self._family_task(title, None, None, notes, "")
        except ToolError:
            return ""
        self._email_reminded = True
        return " — also added a task to send it (don't add another)"

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
    family_on = notes.family_account is not None and notes.family is not None
    if not family_on:
        tools.pop("email_family", None)
    if notes.restricted:
        tools = {k: v for k, v in tools.items()
                 if k in ("save_note", "add_task", "find_tasks", "update_task", "note_on_task", "draft_whatsapp",
                          "draft_join_instructions", "search_notes", "email_family", "suggest_idea")
                 or (k == "create_event" and family_on)}      # family members' events: the family calendar
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
    IDS = {"type": "array", "items": {"type": "string", "enum": [p.id for p in people]}}  # noqa: N806
    WHO = {"type": "string", "enum": [""] + [p.id for p in people],  # noqa: N806
           "description": "family member id (see add_task)"} if people else string("leave empty")
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
                  also_for={**IDS, "description": "shared task only: the others it is for"},
                  together={"type": "string", "enum": ["", "any", "all"],
                            "description": "shared: any = one is enough, all = each one"},
                  due_date=string("the day AS SAID ('מחר', 'יום רביעי', 'Thursday', 'today') or YYYY-MM-DD for an explicit "
                                  "calendar date ('15 באוקטובר'); empty if no day was said"),
                  due_time=string("HH:MM 24h if a time was mentioned, else empty"),
                  notes=string("extra details, optional"),
                  repeat=string("only if repeating: daily|weekdays|weekly:sun,wed|every:3d|every:2w|monthly:15"),
                  take_turns={"type": "boolean", "description": "repeat: they take turns"}),
              "required": ["title"]},
             "internal", notes.add_task),
        Tool("suggest_idea", "An idea for the Jar app itself (a feature or change), never add_task.",
             {**s(title=string("the idea, short"), details=string("optional")), "required": ["title"]},
             "internal", notes.suggest_idea),
        Tool("draft_join_instructions", "WhatsApp message to someone on how to install and join the Jar app "
             "(real download link + their pairing link + steps). For any memo about sending install / join / "
             "set-up instructions for Jar or 'the app'; don't also call draft_whatsapp.",
             {**s(for_person=FOR,
                  greeting=string("optional short opening line in the speaker's voice"),
                  language={"type": "string", "enum": ["he", "en"], "description": "language of the message"}),
              "required": ["for_person"]},
             "internal", notes.draft_join_instructions),
        Tool("search_notes", "Search the notes the speaker saved before (ideas, information, lesson ideas) for "
             "facts to use in a message or task.",
             {**s(query=string("a few key words")), "required": ["query"]},
             "none", notes.search_notes),
        Tool("draft_whatsapp", "Prepare a WhatsApp message on the speaker's phone; they review it and press "
             "Send themselves (nothing is sent automatically). Use when the memo says to message, text or WhatsApp "
             "someone ('תשלח לסווטה ש…', 'write to Dana on WhatsApp…', 'תכתוב בקבוצה…').",
             {**s(text=string("the complete message, ready to send, in the memo's language, as the speaker (first "
                              "person), with every detail the recipient needs (steps, links, times, places)"),
                  to=string("who it is for, as said; empty if not said. Never invent phone numbers")),
              "required": ["text"]},
             "internal", notes.draft_whatsapp),
        Tool("find_tasks", "Look up EXISTING open tasks by words in them. Use first when the memo changes, "
             "moves, finishes or cancels something already on the list ('move the dentist to Thursday', "
             "'סיימתי לתלות כביסה').",
             {**s(query=string("a few key words of the task, in the memo's language"),
                  for_person=WHO),
              "required": ["query"]},
             "none", notes.find_tasks),
        Tool("update_task", "Change an existing task found with find_tasks: new title, new day/time, another "
             "person, or status done / cancel / reopen. Only the fields you give change.",
             {**s(task_id=string("the id from find_tasks"),
                  title=string("new title, or empty"),
                  due_date=string("new day AS SAID ('יום חמישי', 'מחר') or YYYY-MM-DD, or empty"),
                  due_time=string("new time HH:MM, or empty"),
                  for_person=WHO,
                  status={"type": "string", "enum": ["", "done", "cancel", "reopen", "stop_repeating"],
                          "description": "done = finished; cancel = no longer needed; empty = no change"},
                  repeat=string("make it repeat / change its schedule (as add_task repeat); else empty"),
                  take_turns={"type": "boolean", "description": "repeat: its people take turns"}),
              "required": ["task_id"]},
             "internal", notes.update_task),
        Tool("note_on_task", "Add a note to an existing task (id from find_tasks), or ask about it: ask=true sends "
             "it to the other side, and the task pops up for them until they answer. Answering a question "
             "waiting on the speaker: ask=false.",
             {**s(task_id=string("the id from find_tasks"),
                  text=string("the note or question, complete, in the memo's language"),
                  ask={"type": "boolean", "description": "true = a question that needs an answer"}),
              "required": ["task_id", "text"]},
             "internal", notes.note_on_task),
        Tool("create_event", "Create a calendar event: a meeting, appointment or anything at a set time.",
             {**s(title=string("event title"), date=string("the day AS SAID ('מחר', 'ביום רביעי', 'Thursday') or YYYY-MM-DD for an explicit calendar date"),
                  start_time=string("HH:MM 24h, empty for all-day"),
                  duration_min={"type": "integer", "description": "minutes, default 60"},
                  location=string("optional"), notes=string("optional"),
                  account=ACCOUNT,
                  **({"invite": {**IDS, "description": "family members taking part (invited)"}}
                     if notes.family_account is not None and people else {})),
              "required": ["title", "date"]},
             "internal", notes.create_event),
        Tool("draft_email", "An email DRAFT (not sent; the owner reviews and sends it), when the memo asks "
             "to email or write to someone.",
             {**s(subject=string("email subject in the memo's language"),
                  body=string("the full email text, polite and ready to send, in the memo's language"),
                  to=string("email address(es) ONLY if said explicitly in the memo, else empty"),
                  account=ACCOUNT),
              "required": ["subject", "body"]},
             "internal", notes.draft_email),
        Tool("email_family", "Email family members now (sent). Anyone else: draft_email.",
             {**s(subject=string("subject"), body=string("the email, in the memo's language"),
                  who={**IDS, "description": "empty = everyone"}),
              "required": ["subject", "body"]},
             "internal", notes.email_family),
        Tool("save_lesson_idea", "Save a teaching idea for a class (math or software engineering).",
             {**s(idea=string("the idea, cleaned up"), class_name=string("e.g. 10th grade math, optional"),
                  topic=string("e.g. rational functions, optional")),
              "required": ["idea"]},
             "internal", notes.save_lesson_idea),
        Tool("escalate_deep_work", "Hand a big job (research, long drafting, comparisons, anything needing "
             "the web) to the cloud model. Use when the speaker says 'deep work' / 'עבודה עמוקה' or it "
             "clearly needs research.",
             {**s(request=string("the full request, with all details from the memo"),
                  title=string("short title")),
              "required": ["request"]},
             "internal", notes.escalate_deep_work),
    ]
    return {t.name: t for t in tools}
