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

Your job: decide what the memo asks for and call the right tools to file it. Rules:
- Call at least one tool. One memo can need several (e.g. a task AND a calendar event).
- Write titles and text in the memo's language. Fix obvious transcription errors; keep every detail.
- Resolve relative dates against the recording time below ("tomorrow", "Thursday", "מחר", "ביום חמישי")
  and give dates as YYYY-MM-DD and times as HH:MM (24h). A weekday means the next such day.
- A reminder to do something -> add_task (with due_date/due_time if said).
  Something happening at a set time with other people or a place -> create_event.
  A teaching idea -> save_lesson_idea. "Deep work" / "עבודה עמוקה" or research -> escalate_deep_work.
  Writing to someone -> draft_email (a draft only; never invent email addresses).
- For create_event and draft_email pick the account: "school" for classes, students, parents, staff,
  lessons, grades or the school; "personal" for everything else.
  Anything else -> save_note.
- If the memo is unclear, save it as a note tagged "unsorted".
- After the tools succeed, reply with ONE short sentence saying what you filed. No questions.
  Say only what the tool result says (e.g. don't promise a reminder if it says there is no time).
{family}
Recording time: {when} ({weekday}), timezone {tz}."""

FAMILY_RULES = """
Family (people Jar knows; for add_task use the id in for_person):
{people}
The speaker of this memo is {speaker}. "Remind Yoni…", "תגיד ליוני…", "ask Mom to…" -> add_task with
for_person set to that person; title without their name ("להוציא את הכלב", not "יוני להוציא את הכלב").
"me"/"I"/"לי"/no name -> for_person empty. Words like אבא/אמא/Dad/Mom mean the parent of the speaker.
"""

GUEST = """You are Jar, the family's voice-memo assistant. Each message is the transcript of one short voice memo recorded by {speaker}, a member of {owner}'s family; it may be Hebrew, English or both and may contain transcription errors.

Your job: file the memo with the tools. Rules:
- Call at least one tool. Write in the memo's language; fix obvious transcription errors.
- Resolve relative dates against the recording time below; dates YYYY-MM-DD, times HH:MM (24h).
- Something to do or remember, or a request to someone in the family -> add_task.
  Anything else -> save_note (it is private to the speaker).
- After the tools succeed, reply with ONE short sentence saying what you filed. No questions.
  Say only what the tool result says.
{family}
Recording time: {when} ({weekday}), timezone {tz}."""


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
                       about=(about + " ") if about else "")


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
                 max_rounds: int = 4, timeout: float = 300, about: str = ""):
        self.about = about          # [llm] about: a sentence about the owner, for context
        self.url, self.model = url.rstrip("/"), model
        self.temperature, self.keep_alive = temperature, keep_alive
        self.max_rounds, self.timeout = max_rounds, timeout

    # -- HTTP --
    def _chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({
            "model": self.model, "messages": messages, "tools": tools, "stream": False,
            "think": False,                     # qwen3.x: skip the long hidden reasoning; much faster
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
        tools = registry(notes)
        schemas = [t.schema() for t in tools.values()]
        messages = [
            {"role": "system", "content": system_prompt(notes, recorded_local, tz_name, self.about)},
            {"role": "user", "content": transcript},
        ]
        summary, rounds = "", 0
        for rounds in range(1, self.max_rounds + 1):
            try:
                msg = self._chat(messages, schemas)
            except Exception as e:  # noqa: BLE001
                if not notes.actions:
                    raise          # nothing filed yet: safe to retry the whole memo later
                # Something is already filed; retrying would file it twice. Keep what we have.
                log.warning("  model failed after filing (%s); keeping the %d action(s)", e, len(notes.actions))
                summary = "Filed; the model stopped before its closing summary."
                break
            calls = msg.get("tool_calls") or []
            if not calls:
                summary = _clean(msg.get("content", ""))
                break
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                result = self._execute(tools, fn.get("name", ""), fn.get("arguments", {}))
                log.info("  tool %s -> %s", fn.get("name"), result)
                messages.append({"role": "tool", "content": result, "tool_name": fn.get("name", "")})

        fallback = False
        if not notes.actions:
            # The model never managed a successful tool call: keep the memo, don't lose it.
            fallback = True
            first = " ".join(transcript.split()[:8]) or "Memo"
            notes.save_note(title=first, body=transcript, tags=["unsorted"])
            summary = summary or "Saved as an unsorted note."
        return AgentResult(notes.actions, summary, rounds, round(time.monotonic() - t0, 2), fallback)

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


def _clean(text: str) -> str:
    """Drop any <think>…</think> block and keep the reply short."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    return text.splitlines()[0][:300] if text else ""
