"""Who is in the family, which phone token belongs to whom, and who may do what.

config.toml:
    [family]
    avi  = { name = "אבי",  role = "parent", admin = true, aliases = ["Avi"] }
    dana = { name = "דנה",  role = "parent", aliases = ["Dana"] }
    yoni = { name = "יוני", role = "child",  aliases = ["Yoni"], age = 12 }   # age is optional
    maya = { name = "מאיה", role = "child",  aliases = ["Maya"], age = 8 }

The admin (whoever owns the PC) keeps using [server] token, so existing phones/pendants keep
working. Everyone else gets their own token, generated once into data/secrets/family_tokens.json.
Without a [family] section there is one person, "me", the admin: the single-user setup from before.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Person:
    id: str
    name: str
    role: str = "parent"          # "parent" or "child"
    admin: bool = False
    aliases: list[str] = field(default_factory=list)
    phone: str = ""               # optional, for "send a WhatsApp to …" (international format, +972…)
    age: int = 0                  # optional: the points game rates a chore harder for a younger child

    @property
    def is_parent(self) -> bool:
        return self.role != "child"

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role, "admin": self.admin}


def _age(value) -> int:
    try:
        return max(0, min(120, int(value)))
    except (TypeError, ValueError):
        return 0


class Family:
    def __init__(self, people: list[Person], admin_token: str, secrets_dir: Path):
        self.people = {p.id: p for p in people}
        self.admin_token = admin_token
        self.tokens_path = secrets_dir / "family_tokens.json"
        if not any(p.admin for p in people) and people:
            people[0].admin = True
        self._tokens: dict[str, str] | None = None

    # ---- construction ----
    @classmethod
    def from_config(cls, raw: dict, admin_token: str, data_dir: Path, contacts: dict | None = None) -> "Family":
        people = []
        for pid, v in (raw or {}).items():
            if not isinstance(v, dict):
                continue
            people.append(Person(id=str(pid).lower(), name=str(v.get("name") or pid),
                                 role="child" if str(v.get("role", "parent")).lower() == "child" else "parent",
                                 admin=bool(v.get("admin", False)),
                                 aliases=[str(a) for a in v.get("aliases", [])],
                                 phone=str(v.get("phone", "")).strip(),
                                 age=_age(v.get("age"))))
        if not people:
            people = [Person("me", "me", "parent", True)]
        fam = cls(people, admin_token, data_dir / "secrets")
        fam.contacts = {str(k): str(v).strip() for k, v in (contacts or {}).items()}
        return fam

    @property
    def admin(self) -> Person:
        return next(p for p in self.people.values() if p.admin)

    def get(self, pid: str | None) -> Person | None:
        return self.people.get((pid or "").lower())

    def resolve(self, name: str) -> Person | None:
        """'Yoni', 'יוני', 'yoni' -> the person; '' / 'me' -> None (caller means the speaker)."""
        n = (name or "").strip().lower()
        if not n or n in ("me", "self", "אני"):
            return None
        for p in self.people.values():
            if n == p.id or n == p.name.lower() or n in (a.lower() for a in p.aliases):
                return p
        return None

    # ---- tokens ----
    def _load_tokens(self) -> dict[str, str]:
        if self._tokens is None:
            try:
                self._tokens = json.loads(self.tokens_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._tokens = {}
        return self._tokens

    def token_for(self, pid: str) -> str:
        p = self.get(pid)
        if p is None:
            raise KeyError(pid)
        if p.admin:
            return self.admin_token
        tokens = self._load_tokens()
        if pid not in tokens:
            tokens[pid] = secrets.token_urlsafe(24)
            self.tokens_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.tokens_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
            os.replace(tmp, self.tokens_path)
        return tokens[pid]

    def who(self, token: str | None) -> Person | None:
        """The person a phone/pendant token belongs to (constant-time compare)."""
        if not token:
            return None
        found = None
        if self.admin_token and hmac.compare_digest(token, self.admin_token):
            found = self.admin
        self._tokens = None              # re-read: pairing may have issued a token since
        for pid, t in self._load_tokens().items():
            if pid in self.people and hmac.compare_digest(token, t):
                found = found or self.people[pid]
        return found

    contacts: dict = {}

    def phone_for(self, name: str) -> tuple[str, str]:
        """(display name, phone) for a WhatsApp recipient: a family member, a [contacts] entry, or
        just the name as said (phone "" = WhatsApp lets you pick the chat). Never guesses a number."""
        n = (name or "").strip()
        p = self.resolve(n)
        if p is not None:
            return p.name, p.phone
        for k, v in self.contacts.items():
            if k.casefold() == n.casefold():
                return k, v
        return n, ""

    def prompt_lines(self) -> str:
        """For the model: who's who, so 'remind Yoni' or 'תגיד לאמא' can be resolved."""
        out = []
        for p in self.people.values():
            names = ", ".join([p.name] + [a for a in p.aliases if a != p.name])
            out.append(f"- {p.id}: {names} ({'child' if p.role == 'child' else 'parent'})")
        return "\n".join(out)
