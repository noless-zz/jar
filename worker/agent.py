"""The local agent: one memo transcript in, tool calls out, via Ollama's chat API.

The model may call several tools for one memo ("note this and remind me Thursday").
Small local models sometimes misbehave, so every step is defended:
bad JSON arguments, unknown tools and missing fields go back to the model as
errors it can fix, and if it never calls a tool the memo is kept as a note.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from .tools import Notes, Tool, ToolError, registry

log = logging.getLogger("jar.agent")

SYSTEM = """You are Jar, the assistant behind {owner}'s voice-memo pendant. {about}\
Each message is the transcript of one short voice memo they \
recorded; it may be Hebrew, English or both, and may contain transcription errors.

Before calling tools, work out:
1. What does the speaker want to HAPPEN? (a reminder, an appointment, a message someone will read, a change
   to an existing task, a note to keep…)
2. WHO has to do it? (see "Who does it" below)
3. What must the result CONTAIN to be useful on its own? A task title someone understands later; a message the
   recipient can act on without asking back.

Tools:
- A reminder / something to do -> add_task (due_date/due_time if said).
  Something at a set time with other people or a place -> create_event.
  A teaching idea -> save_lesson_idea. "Deep work" / "עבודה עמוקה" or research -> escalate_deep_work.
- Changing, moving, finishing or cancelling a task that already exists ("סיימתי…", "בטל…", "תעביר את…",
  "done with…", "move…") -> find_tasks, then update_task. Never add a second task for it.
- A question or remark about an existing task ("תשאל את ליבנה אם הוא כבר סידר את החדר", "תגיד לאלונה
  שהשיעורים בעמוד 40", answering a question someone asked about a task) -> find_tasks, then note_on_task
  (ask=true for a question). Not a WhatsApp message and not a new task.
- A NEW to-do said as just an action, without "remind me" — an infinitive or "I need to" ("לקנות סוללות",
  "להכין לוח שנה לסבתא", "לחדש את הביטוח של האוטו של סווטה", "to call the bank") -> add_task, NOT a note.
  It is the speaker's own task, even when it is about someone else's thing (see "Who does it").
- A message to someone (WhatsApp, SMS, "תשלח ל…", "תכתוב ל…", "תגיד ל… בוואטסאפ") -> draft_whatsapp.
  An email ("email", "מייל", formal letters, school staff/parents) -> draft_email (never invent addresses).
  draft_email also adds a "send it" task by itself: do not add one.
- For create_event and draft_email pick the account: "school" for classes, students, parents, staff,
  lessons, grades or the school; "personal" for everything else.
- Anything else -> save_note: only information to keep (an idea, a fact, a list, a thought). If the memo is
  unclear, save it as a note tagged "unsorted".
{messages}
- Write in the memo's language. Fix obvious transcription errors (names especially); keep every detail.
- Days: pass them AS SAID ("מחר", "יום רביעי", "Thursday") — the tools turn them into dates. Use YYYY-MM-DD
  only for an explicit calendar date ("15 באוקטובר"). Times as HH:MM (24h): "בשש בערב" = 18:00.
- After the tools succeed, reply with ONE short sentence saying what you filed. No questions.
  Say only what the tool results say (don't promise a reminder if a result says there is no time).
{family}
Recording time: {when} ({weekday}), timezone {tz}.
Dates of the coming days (use these, don't compute weekdays yourself):
{days}"""

MESSAGE_RULES = """
Messages (draft_whatsapp, draft_email) — write the real message, complete and ready to send:
- It goes to the recipient as-is. Write it as the speaker, in first person, warm and natural.
- If the memo asks to send instructions, details, a link or an explanation, the message must CONTAIN them,
  not "here are the instructions". For installing/joining the Jar app use draft_join_instructions (it writes
  the whole message with the real links). For other facts, search_notes first. Never invent links, numbers,
  addresses or facts.
- Short is fine for simple messages ("אני מגיע בשש"); instructions get numbered steps."""

FAMILY_RULES = """
Family (people Jar knows; use the id in for_person):
{people}
The speaker of this memo is {speaker}. Words like אבא/אמא/Dad/Mom mean the speaker's parent.

Who does it (for_person in add_task):
- Someone else ONLY when the speaker asks or reminds THEM to do it: "תזכיר לליבנה להוציא את הכלב",
  "תגיד לסווטה לקנות חלב", "תבקש מאלונה לסדר", "ask Mom to…", "Livne needs to…" -> for_person = that person.
  Title without their name ("להוציא את הכלב").
- A task the speaker does FOR or ABOUT someone is the speaker's own: "לחדש את הביטוח של האוטו של סווטה"
  (Sveta's car, but the speaker renews it), "לחבר לאלונה את הראש מיטה" (for Alona, done by the speaker),
  "לקנות מתנה לליבנה", "I need to call Mom" -> for_person empty. Keep the person's name in the title.
- "me"/"I"/"לי"/no name -> for_person empty. When unsure, it's the speaker's.
"""

GUEST = """You are Jar, the family's voice-memo assistant. Each message is the transcript of one short voice memo recorded by {speaker}, a member of {owner}'s family; it may be Hebrew, English or both and may contain transcription errors.

Before calling tools, work out what the speaker wants to happen, who has to do it, and what the result must
contain to be useful.

Tools:
- Something to do or remember, or a request to someone in the family -> add_task. A memo that just names an
  action ("להכין לוח שנה לסבתא", "ללמוד למבחן", "לקנות מחברת", "צריך ל…") is a task for the speaker.
  The speaker sees tasks in the app; notes they never see, so when in doubt make it a task.
- Changing, moving, finishing or cancelling an existing task -> find_tasks, then update_task.
- A question or answer about an existing task ("לשאול את אבא אם…", "לענות לאמא ש…") -> find_tasks, then
  note_on_task (ask=true for a question).
- A message to someone (WhatsApp, "תשלח ל…", "תכתוב ל…") -> draft_whatsapp (prepared, they press Send).
- Only information to keep that isn't something to do -> save_note (private; the speaker won't see it in the app).
{messages}
- Write in the memo's language; fix obvious transcription errors.
- Days: pass them AS SAID ("מחר", "יום רביעי") — the tools turn them into dates. Times HH:MM (24h).
- After the tools succeed, reply with ONE short sentence saying what you filed. No questions.
  Say only what the tool results say.
{family}
Recording time: {when} ({weekday}), timezone {tz}.
Dates of the coming days (use these, don't compute weekdays yourself):
{days}"""


HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def day_table(recorded_local: datetime) -> str:
    """Today .. +7 days with English and Hebrew weekday names: 'Wednesday' / 'יום רביעי' -> a date."""
    from datetime import timedelta
    rows = []
    for i in range(8):
        d = (recorded_local + timedelta(days=i)).date()
        tag = " (today, היום)" if i == 0 else " (tomorrow, מחר)" if i == 1 else " (מחרתיים)" if i == 2 else ""
        rows.append(f"  {d:%A} / יום {HE_DAYS[d.weekday()]}: {d.isoformat()}{tag}")
    return "\n".join(rows) + "\n  A weekday that is today means next week's, unless the time is still ahead today."


def system_prompt(notes: Notes, recorded_local: datetime, tz_name: str, about: str = "") -> str:
    fam = ""
    if notes.family is not None and len(notes.family.people) > 1 and notes.speaker is not None:
        sp = notes.speaker
        fam = FAMILY_RULES.format(people=notes.family.prompt_lines(),
                                  speaker=f"{sp.id} ({sp.name}, {'child' if sp.role == 'child' else 'parent'})")
    base = GUEST if notes.restricted else SYSTEM
    owner = notes.family.admin.name if notes.family is not None else "the owner"
    about = (about or "").strip()
    return base.format(when=f"{recorded_local:%Y-%m-%d %H:%M}", weekday=f"{recorded_local:%A}", tz=tz_name,
                       family=fam, speaker=getattr(notes.speaker, "name", ""), owner=owner,
                       about=(about + " ") if about else "", messages=MESSAGE_RULES, days=day_table(recorded_local))


class OllamaUnavailable(Exception):
    """Ollama isn't running or the model isn't pulled: leave the memo for later."""


@dataclass
class AgentResult:
    actions: list[dict]
    summary: str
    rounds: int
    seconds: float
    fallback: bool


class Agent:
    def __init__(self, url: str, model: str, temperature: float = 0.2, keep_alive: str = "10m",
                 max_rounds: int = 4, timeout: float = 300, about: str = "", think: bool = True):
        self.think = think          # [llm] think: let the model reason before calling tools
        self.about = about          # [llm] about: a sentence about the owner, for context
        self.url, self.model = url.rstrip("/"), model
        self.temperature, self.keep_alive = temperature, keep_alive
        self.max_rounds, self.timeout = max_rounds, timeout

    # -- HTTP --
    def _chat(self, messages: list[dict], tools: list[dict], think: bool | None = None) -> dict:
        body = json.dumps({
            "model": self.model, "messages": messages, "tools": tools, "stream": False,
            "think": self.think if think is None else think,   # qwen3.x: reason before choosing tools
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature},
        }).encode()
        req = urllib.request.Request(self.url + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())["message"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 404 or "not found" in detail:
                raise OllamaUnavailable(f"model {self.model} not found — run: ollama pull {self.model}") from e
            if e.code >= 500:
                # Ollama's own problem (out of VRAM, broken model files, an update mid-way…):
                # not the memo's fault, so the memo waits instead of using up its attempts.
                raise OllamaUnavailable(f"Ollama error {e.code}: {detail}") from e
            raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise OllamaUnavailable(f"can't reach Ollama at {self.url} ({e})") from e

    def ping(self) -> str | None:
        """None if Ollama is up and has the model, else a reason."""
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=5) as r:
                names = [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
        except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError) as e:
            return f"can't reach Ollama at {self.url} ({e})"
        wanted = self.model if ":" in self.model else self.model + ":latest"
        return None if wanted in names else f"model {self.model} not pulled (have: {', '.join(names) or 'none'})"

    # -- the loop --
    def run(self, transcript: str, notes: Notes, recorded_local: datetime, tz_name: str,
            meta: dict | None = None) -> AgentResult:
        t0 = time.monotonic()
        notes.transcript = transcript
        tools = registry(notes)
        schemas = [t.schema() for t in tools.values()]
        context = ""
        if notes.store is not None and notes.speaker is not None:
            try:
                near = notes.store.find(notes.speaker, transcript, limit=5)
            except Exception:  # noqa: BLE001
                near = []
            if near:
                name = lambda pid: notes.family.get(pid).name if notes.family and notes.family.get(pid) else pid  # noqa: E731
                context = ("\n\nOpen tasks that may be what this memo is about (if the memo finishes, moves, changes "
                           "or cancels one of them, use update_task with its id instead of adding a new task):\n"
                           + "\n".join(f"- id={t['id']} | {t['title']} | for {name(t['assignee'])}"
                                       + (f" | due {t['due'].replace('T', ' ')}" if t.get("due") else "")
                                       for t in near))
        system = system_prompt(notes, recorded_local, tz_name, self.about) + context
        summary, rounds = self._loop(transcript, system, tools, schemas, notes, self.think)
        if not notes.actions and self.think:
            # Thinking mode sometimes ends with a plain-text answer and no tool call. One more try,
            # without thinking (that mode reliably calls a tool), before falling back to a note.
            log.info("  nothing filed with thinking on; retrying once without it")
            summary, more = self._loop(transcript, system, tools, schemas, notes, False)
            rounds += more

        fallback = False
        if not notes.actions:
            # The model never managed a successful tool call: keep the memo, don't lose it.
            fallback = True
            first = " ".join(transcript.split()[:8]) or "Memo"
            notes.save_note(title=first, body=transcript, tags=["unsorted"])
            summary = summary or "Saved as an unsorted note."
        return AgentResult(notes.actions, summary, rounds, round(time.monotonic() - t0, 2), fallback)

    def _loop(self, transcript: str, system: str, tools: dict, schemas: list, notes: Notes,
              think: bool) -> tuple[str, int]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": transcript}]
        summary, rounds, nudged = "", 0, False
        for rounds in range(1, self.max_rounds + 1):
            try:
                msg = self._chat(messages, schemas, think)
            except Exception as e:  # noqa: BLE001
                if not notes.actions:
                    raise          # nothing filed yet: safe to retry the whole memo later
                # Something is already filed; retrying would file it twice. Keep what we have.
                log.warning("  model failed after filing (%s); keeping the %d action(s)", e, len(notes.actions))
                summary = "Filed; the model stopped before its closing summary."
                break
            calls = msg.get("tool_calls") or _calls_in_text(msg.get("content", ""), tools)
            if not calls:
                if msg.get("content"):
                    log.info("  model answered without a tool: %s", _clean(msg.get("content", ""))[:200])
                if not notes.actions and not nudged and rounds < self.max_rounds:
                    # It only looked things up (or just talked): ask once to actually file the memo.
                    nudged = True
                    messages.append({"role": "assistant", "content": msg.get("content", "")})
                    messages.append({"role": "user", "content":
                                     "Nothing is filed yet. Now call the tool that does what the memo asks "
                                     "(for example draft_whatsapp with the complete message, or add_task)."})
                    continue
                summary = _clean(msg.get("content", ""))
                break
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                result = self._execute(tools, fn.get("name", ""), fn.get("arguments", {}))
                log.info("  tool %s -> %s", fn.get("name"), result)
                messages.append({"role": "tool", "content": result, "tool_name": fn.get("name", "")})
        return summary, rounds

    @staticmethod
    def _execute(tools: dict[str, Tool], name: str, args) -> str:
        tool = tools.get(name)
        if tool is None:
            return f"error: unknown tool '{name}'. Available: {', '.join(tools)}"
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                return "error: arguments must be a JSON object"
        if not isinstance(args, dict):
            return "error: arguments must be a JSON object"
        accepted = set(inspect.signature(tool.handler).parameters)
        clean = {k: v for k, v in args.items() if k in accepted and v is not None}
        missing = [k for k in tool.parameters.get("required", []) if not clean.get(k)]
        if missing:
            return f"error: missing {', '.join(missing)}"
        if "tags" in clean and isinstance(clean["tags"], str):
            clean["tags"] = [t for t in re.split(r"[,\s]+", clean["tags"]) if t]
        try:
            return tool.handler(**clean)
        except ToolError as e:
            return f"error: {e}"
        except Exception as e:  # noqa: BLE001 — report, don't crash the worker
            log.exception("tool %s failed", name)
            return f"error: {type(e).__name__}: {e}"


def _calls_in_text(content: str, tools: dict) -> list[dict]:
    """Tool calls the model wrote as text (<tool_call>{...}</tool_call> or a bare JSON object with
    "name" and "arguments") instead of calling the tool. Only names of real tools are accepted."""
    calls = []
    text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S)
    blobs = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, flags=re.S) or \
        re.findall(r"\{[^{}]*\"name\"\s*:\s*\"[a-z_]+\"[^{}]*\"arguments\"\s*:\s*\{.*?\}\s*\}", text, flags=re.S)
    for b in blobs:
        try:
            obj = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("name") in tools:
            calls.append({"function": {"name": obj["name"], "arguments": obj.get("arguments", {})}})
    return calls


def _clean(text: str) -> str:
    """Drop any <think>…</think> block and keep the reply short."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    return text.splitlines()[0][:300] if text else ""
