"""Control the house from a memo, through Home Assistant (docs/HOME_ASSISTANT.md).

Jar's Home Assistant integration gives Jar the address of Home Assistant and a token of a Home Assistant user
made for Jar; the server stores them in data/secrets/home_assistant.json. The `home` tool sends the request,
rewritten by the model in plain English, to Home Assistant's own built-in Assist ("turn off the kitchen lights",
"set the living room AC to 24", "is the boiler on"). Home Assistant matches the names and areas itself and only
touches what is exposed to Assist (Settings → Voice assistants → Expose), so nothing about the house goes into
Jar's prompt and the family decides there what a memo may switch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("jar.home")

AGENT = "conversation.home_assistant"      # the built-in agent: fast, local, no LLM on Home Assistant's side


@dataclass
class Reply:
    ok: bool
    speech: str
    changed: list[str]


class HomeAssistant:
    def __init__(self, link_path: Path, timeout: float = 10):
        self.link_path = link_path
        self.timeout = timeout

    def link(self) -> dict:
        try:
            v = json.loads(self.link_path.read_text(encoding="utf-8"))
            return v if v.get("url") and v.get("token") else {}
        except (OSError, ValueError):
            return {}

    @property
    def configured(self) -> bool:
        return bool(self.link())

    def command(self, text: str) -> Reply:
        """One request to Home Assistant's Assist, in English. Raises on a network or auth problem."""
        import requests
        link = self.link()
        if not link:
            raise RuntimeError("Home Assistant isn't connected to Jar")
        r = requests.post(link["url"].rstrip("/") + "/api/conversation/process",
                          headers={"Authorization": "Bearer " + link["token"]},
                          json={"text": text, "language": "en", "agent_id": AGENT}, timeout=self.timeout)
        if r.status_code == 401:
            raise RuntimeError("Home Assistant refused Jar's token: set up the Jar integration in Home Assistant again")
        r.raise_for_status()
        return parse(r.json())


def parse(body: dict) -> Reply:
    """Home Assistant's conversation reply -> did it work, what it said, which devices it changed."""
    resp = (body or {}).get("response") or {}
    speech = (((resp.get("speech") or {}).get("plain") or {}).get("speech") or "").strip()
    data = resp.get("data") or {}
    changed = [x.get("name") or x.get("id") or "" for x in (data.get("success") or []) if isinstance(x, dict)]
    failed = [x.get("name") or x.get("id") or "" for x in (data.get("failed") or []) if isinstance(x, dict)]
    ok = resp.get("response_type") in ("action_done", "query_answer") and not failed
    if failed:
        speech = (speech + " " if speech else "") + "Failed: " + ", ".join(f for f in failed if f)
    return Reply(ok, speech or ("done" if ok else "Home Assistant didn't understand"), [c for c in changed if c])
