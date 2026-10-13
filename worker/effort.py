"""Effort rating for the points game (docs/POINTS.md): how hard is this task for the person who does it?

When a task is created the local model rates it once (about 3 s, thinking off, JSON):
    {effort 1-10, minutes, category, chore_key, reason}
The rating is stored on the task ("points") and is what the coins are worth; a parent can change it.
Everything that doesn't need the model (WhatsApp drafts, "send the email" tasks, a parent's work day,
the fallback when the AI is away) is decided here by plain rules.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request

CATEGORIES = ("cleaning", "kitchen", "laundry", "pets", "outdoor", "school", "errand", "job", "lesson", "other")
DEFAULT_EFFORT = 3

WORK_DAY_RE = re.compile(r"(יום עבודה|ימי עבודה|work ?day|day at work)", re.I)
SEND_EMAIL_RE = re.compile(r"^\s*(לשלוח את המייל|send the email)", re.I)


class RateError(Exception):
    pass


def no_coins_reason(title: str, kind: str = "task") -> str:
    """Why this task never earns coins ("" = it can): prepared WhatsApp messages and "send the email"
    reminders are Jar's own bookkeeping, not effort."""
    if kind == "message":
        return "WhatsApp message"
    if SEND_EMAIL_RE.match(title or ""):
        return "send-the-email reminder"
    return ""


def is_work_day(title: str, person) -> bool:
    return bool(person is not None and getattr(person, "is_parent", False) and WORK_DAY_RE.search(title or ""))


def describe(person) -> str:
    """Who does it, for the model: age matters, because the same chore is harder for a 9-year-old."""
    age = int(getattr(person, "age", 0) or 0)
    if getattr(person, "is_parent", True):
        return "an adult"
    return f"a {age}-year-old child" if age else "a child"


def fallback_key(title: str) -> str:
    """A stable chore key when the model gave none: the same wording gives the same key."""
    words = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (title or "").casefold())).strip()
    return "t-" + hashlib.sha1(words.encode("utf-8")).hexdigest()[:8]


def clean_key(raw: str, title: str = "") -> str:
    key = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", str(raw or "").lower())).strip("-")[:40]
    return key or fallback_key(title)


def default_rating(title: str = "") -> dict:
    """What a task is worth when nobody (AI or parent) has rated it yet: a small middle value."""
    return {"effort": DEFAULT_EFFORT, "minutes": 15, "category": "other", "chore_key": fallback_key(title),
            "reason": "not rated yet", "rated_by": "default", "no_coins": False}


def rule_rating(title: str, kind: str, person) -> dict | None:
    """Ratings that need no model: no-coin tasks and a parent's work day. None = ask the model."""
    why = no_coins_reason(title, kind)
    if why:
        return {"no_coins": True, "rated_by": "rule", "reason": why}
    if is_work_day(title, person):
        return {"effort": 0, "work_day": True, "minutes": 0, "category": "job", "chore_key": "work-day",
                "reason": "work day", "rated_by": "rule", "no_coins": False}
    return None


# ---------------------------------------------------------------- the model

PROMPT = """You rate how much effort a household task takes for a grown-up, for a family chores game.
Task: "{title}"{notes}
Effort 1-10, by the real time it takes and how unpleasant it is:
1 trivial: up to 5 minutes, no real work
2 easy: a small routine, 5-10 minutes
3 light: 10-20 minutes of simple work
4 a bit of work: 20-30 minutes
5 real work or concentration: 30-45 minutes
Helping someone with a phone, computer or forms is at least 5: it takes patience and always runs longer than planned.
6 about an hour
7 big job: 1-2 hours, or physically hard
8 unpleasant or heavy, even when it is short: anything with human or animal waste or dirt that disgusts (sanitary cleaning, litter, nappies, smelly bins, vomit)
9 most of a morning
10 a whole day of hard work
Rate only what the task says: do not imagine extra steps (stripping, washing, sorting) it doesn't mention. Be realistic about time. Judge a person who does this every day: quick routines take 2-5 minutes (effort 1-2), but a task with several separate steps, or a whole room or home, takes 45-90 minutes (effort 6-7), not 25.
For an adult's errands (insurance, repairs, paperwork, appointments) rate the time and the hassle.
Also give: minutes (typical time), category (one of {categories}), chore_key (2-3 English words, lowercase, hyphens: the same chore always gets the same key, however it is worded), reason (English, at most 12 words).{keys}
Reply with JSON only: {{"effort": 1-10, "minutes": 0, "category": "...", "chore_key": "...", "reason": "..."}}"""


def child_bump(person) -> int:
    """What a child's version of a chore adds to the grown-up rating: 1 point (2 under 10, where it takes
    them longer and tires them sooner). Added here, not asked of the model, which double-counts it."""
    if getattr(person, "is_parent", True):
        return 0
    age = int(getattr(person, "age", 0) or 0)
    return 2 if 0 < age < 10 else 1


def build_prompt(title: str, notes: str, person, known_keys: list[str] | None = None) -> str:
    notes = (notes or "").strip()
    return PROMPT.format(
        title=(title or "").strip()[:200],
        notes=f"\nNotes: {notes[:300]}" if notes else "",
        categories=", ".join(CATEGORIES),
        keys=(f"\nKnown chore keys (reuse one if it is the same chore): {', '.join(known_keys[:15])}."
              if known_keys else ""))


def parse(raw: str, title: str = "") -> dict | None:
    """The model's JSON as a clean rating, or None when it didn't give an effort."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return None
    try:
        effort = int(round(float(data.get("effort"))))
    except (TypeError, ValueError):
        return None
    try:
        minutes = int(float(data.get("minutes") or 0))
    except (TypeError, ValueError):
        minutes = 0
    category = str(data.get("category") or "").strip().lower()
    return {"effort": max(1, min(10, effort)), "minutes": max(0, min(600, minutes)),
            "category": category if category in CATEGORIES else "other",
            "chore_key": clean_key(data.get("chore_key"), title),
            "reason": str(data.get("reason") or "").strip()[:120], "rated_by": "ai", "no_coins": False}


def chat(ollama_url: str, model: str, prompt: str, num_ctx: int = 8192, keep_alive: str = "10m",
         timeout: float = 45) -> str:
    """One quick JSON answer. num_ctx and keep_alive match the memo agent's, so Ollama doesn't reload
    the model between a memo and a rating."""
    body = json.dumps({"model": model, "stream": False, "think": False, "format": "json",
                       "keep_alive": keep_alive,
                       "options": {"temperature": 0, "seed": 7, "num_ctx": num_ctx},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(ollama_url.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())["message"]["content"]
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        raise RateError(f"the AI isn't available right now ({type(e).__name__})") from e


def rate(ollama_url: str, model: str, title: str, notes: str, person, known_keys: list[str] | None = None,
         parent_effort: "callable | None" = None, num_ctx: int = 8192, keep_alive: str = "10m",
         timeout: float = 45) -> dict:
    """The rating for a task, for the person who does it. Rules first (no model needed), then the model;
    a parent's earlier correction for the same chore key replaces the model's effort (the starting
    point next time). A child's chore gets the adult rating plus child_bump(). Raises RateError when the model is away or gives nothing usable."""
    ruled = rule_rating(title, "task", person)
    if ruled is not None:
        return ruled
    raw = chat(ollama_url, model, build_prompt(title, notes, person, known_keys), num_ctx, keep_alive, timeout)
    rating = parse(raw, title)
    if rating is None:
        raise RateError("the AI didn't give an effort rating")
    bump = child_bump(person)
    if bump:
        rating["effort"] = min(10, rating["effort"] + bump)
        rating["reason"] = (rating["reason"] + f" · +{bump} for a child").strip(" ·")[:140]
    earlier = parent_effort(rating["chore_key"]) if parent_effort else None
    if earlier:
        rating["effort"] = int(earlier)
        rating["reason"] = (rating["reason"] + " · as a parent set before").strip(" ·")[:140]
    return rating


# ---------------------------------------------------------------- lessons: the "what I learned" note

LESSON_PROMPT = """A child wrote a note about what they learned in a lesson at school. Rate the effort the note shows, 1-5:
1 one vague line ("it was ok")
2 says what the topic was
3 one clear sentence about something specific they learned
4 several sentences, in their own words
5 detailed: explains an idea, gives an example, or says what they want to find out next
Do not judge spelling, handwriting or whether it is correct.
Lesson: "{title}"
Note: "{note}"
Reply with JSON only: {{"effort": 1-5}}"""


def lesson_fallback(note: str) -> int:
    """Without the AI: by length (a few words 1-2, a clear sentence 3, a short paragraph 4)."""
    n = len((note or "").strip())
    return 1 if n < 20 else 2 if n < 45 else 3 if n < 130 else 4


def rate_lesson(ollama_url: str, model: str, title: str, note: str, num_ctx: int = 8192,
                keep_alive: str = "10m", timeout: float = 25) -> tuple[int, str]:
    """(effort 1-5, "ai" | "default") for a lesson note; falls back to length when the AI is away."""
    try:
        raw = chat(ollama_url, model, LESSON_PROMPT.format(title=(title or "")[:100], note=(note or "")[:800]),
                   num_ctx, keep_alive, timeout)
        data = json.loads(raw)
        return max(1, min(5, int(round(float(data.get("effort")))))), "ai"
    except (RateError, ValueError, TypeError, AttributeError):
        return lesson_fallback(note), "default"
