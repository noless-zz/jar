"""Quick replies for a task's notes and questions: the local model suggests short messages to send.

Used by the phone app's ✨ button (POST /v1/tasks/{id}/suggest). Nothing is sent by itself: the person
picks one, can change it, and sends it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class SuggestError(Exception):
    pass


PROMPT = """You help a family member write a short note on a shared family task in the Jar app.
Task: "{title}"{due}. It's {assignee}'s to do; {creator} asked for it.
{thread}
The note is written by {me}.{waiting}
Suggest {n} different short messages {me} could send now (each under 20 words), in the conversation's
language ({lang}), friendly and natural for a family; for a child keep it simple. Vary them: e.g. a direct
answer, a question back, an update. Use only facts from the task and the notes; never invent times,
places or promises beyond what's written.
Reply with JSON only: {{"replies": ["...", "..."]}}"""


def _lang(texts: list[str]) -> str:
    joined = " ".join(texts)
    if re.search(r"[֐-׿]", joined):
        return "Hebrew"
    if re.search(r"[Ѐ-ӿ]", joined):
        return "Russian"
    return "English"


def build_prompt(task: dict, me: str, names: dict[str, str], n: int = 3) -> str:
    name = lambda pid: names.get(pid, pid)  # noqa: E731
    lines = [f"- {name(c['by'])}{' (question)' if c.get('ask') else ''}: {c['text']}" for c in task.get("thread", [])[-12:]]
    thread = ("Notes so far, oldest first:\n" + "\n".join(lines)) if lines else "No notes yet."
    waiting = ""
    if task.get("waiting_on") == me:
        waiting = " There is a question waiting for their answer: answer it."
    elif not lines:
        waiting = " Nothing was said yet: suggest a useful question or update about the task."
    due = f" (due {task['due']})" if task.get("due") else ""
    lang = _lang([task.get("title", "")] + [c["text"] for c in task.get("thread", [])])
    return PROMPT.format(title=task.get("title", ""), due=due, assignee=name(task.get("assignee", "")),
                         creator=name(task.get("created_by", "")), thread=thread, me=name(me),
                         waiting=waiting, n=n, lang=lang)


def parse(raw: str, n: int = 3) -> list[str]:
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return []
    out = []
    for r in (data.get("replies") if isinstance(data, dict) else data) or []:
        r = str(r).strip().strip('"').strip()
        if r and r not in out:
            out.append(r[:300])
    return out[:n]


def suggest(ollama_url: str, model: str, task: dict, me: str, names: dict[str, str], n: int = 3,
            timeout: float = 60) -> list[str]:
    body = json.dumps({"model": model, "stream": False, "think": False, "format": "json",
                       "options": {"temperature": 0.7},
                       "messages": [{"role": "user", "content": build_prompt(task, me, names, n)}]}).encode()
    req = urllib.request.Request(ollama_url.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = json.loads(r.read().decode())["message"]["content"]
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        raise SuggestError(f"the AI isn't available right now ({type(e).__name__})") from e
    replies = parse(content, n)
    if not replies:
        raise SuggestError("the AI didn't come up with a reply; try again")
    return replies
