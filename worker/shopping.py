"""Shopping lists: one per family member, holding the things that person is going to buy.

"Dad, buy epoxy" from Livne -> on Noam's list, requested by Livne. Something to buy without saying who buys it
-> the list of whoever owns the food & shopping area (worker/areas.py), else the speaker's own list.
Nobody earns coins for an item; a shopping trip that is a task ("לעשות קניות בסופר") earns as before.

data/shopping.json: {"rev", "items": [{id, title, notes, buyer, requested_by, status: open|bought,
created_at, updated_at, bought_at, bought_by, memo_id}]}. Bought items stay visible for two days (crossed out),
and are dropped after two weeks.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .family import Family, Person
from .filelock import locked

ACTIONS = ("bought", "unbought", "delete", "edit")
KEEP_BOUGHT = timedelta(days=2)
FORGET_BOUGHT = timedelta(days=14)


class ShoppingError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def norm(text: str) -> str:
    """For matching "חלב" with "חלב 3%" and "the milk": lower case, no punctuation, no Hebrew ה prefix."""
    words = re.sub(r"[^\w\s]", " ", (text or "").casefold()).split()
    return " ".join(w[1:] if w.startswith("ה") and len(w) > 2 else w for w in words if w not in ("the", "a", "an"))


class ShoppingStore:
    def __init__(self, path: Path, family: Family, default_buyer: Callable[[], str | None] | None = None):
        self.path, self.family = path, family
        self.lock_path = path.with_suffix(".lock")
        self._default_buyer = default_buyer or (lambda: None)

    # ---- storage ----
    @contextmanager
    def _locked(self):
        with locked(self.lock_path, lambda: ShoppingError(503, "the shopping list is busy, try again")):
            yield

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {"rev": 0, "items": []}
        data.setdefault("items", [])
        return data

    def _write(self, data: dict) -> None:
        cutoff = datetime.now(timezone.utc) - FORGET_BOUGHT
        data["items"] = [i for i in data["items"]
                         if i.get("status") != "bought" or (_when(i.get("bought_at")) or cutoff) > cutoff]
        data["rev"] = int(data.get("rev", 0)) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- rules ----
    def default_buyer(self, speaker: Person | None = None) -> Person:
        """Whoever buys when nobody was named: the food & shopping area's owner, else the speaker."""
        who = self.family.get(self._default_buyer() or "")
        return who or speaker or self.family.admin

    def _may_change(self, actor: Person, item: dict) -> bool:
        return actor.is_parent or actor.id in (item.get("buyer"), item.get("requested_by"))

    # ---- API ----
    def snapshot(self, viewer: Person | None = None) -> dict:
        """Everyone's lists (the family shops for each other): open items, and what was bought in the last
        two days. Oldest first within a list."""
        data = self._read()
        now = datetime.now(timezone.utc)
        items = [i for i in data["items"] if i.get("status") == "open"
                 or (_when(i.get("bought_at")) or now) > now - KEEP_BOUGHT]
        items.sort(key=lambda i: (i.get("status") == "bought", i.get("created_at") or ""))
        return {"rev": data.get("rev", 0), "items": items, "default_buyer": self.default_buyer(viewer).id}

    def add(self, creator: Person, titles: list[str] | str, buyer: Person | None = None, notes: str = "",
            memo_id: str | None = None) -> list[dict]:
        """One item per title on the buyer's list. An item already open on that list isn't added twice
        (the existing one comes back, with a note of who asked again)."""
        if isinstance(titles, str):
            titles = [titles]
        titles = [t.strip()[:120] for t in titles if t and t.strip()]
        if not titles:
            raise ShoppingError(400, "what to buy is missing")
        if len(titles) > 30:
            raise ShoppingError(400, "too many items at once")
        who = buyer or self.default_buyer(creator if not getattr(creator, "is_home", False) else None)
        out = []
        with self._locked():
            data = self._read()
            for title in titles:
                same = next((i for i in data["items"] if i.get("status") == "open" and i.get("buyer") == who.id
                             and norm(i["title"]) == norm(title)), None)
                if same is not None:
                    if notes and notes.strip() not in (same.get("notes") or ""):
                        same["notes"] = ((same.get("notes") or "") + "\n" + notes.strip()).strip()[:500]
                        same["updated_at"] = _now()
                    out.append(same)
                    continue
                item = {"id": uuid.uuid4().hex[:10], "title": title, "notes": (notes or "").strip()[:500],
                        "buyer": who.id, "requested_by": creator.id, "status": "open",
                        "created_at": _now(), "updated_at": _now(), "bought_at": None, "bought_by": None,
                        "memo_id": memo_id}
                data["items"].append(item)
                out.append(item)
            self._write(data)
        return out

    def act(self, actor: Person, item_id: str, action: str, fields: dict | None = None) -> dict:
        if action not in ACTIONS:
            raise ShoppingError(400, f"unknown action {action}")
        f = fields or {}
        with self._locked():
            data = self._read()
            item = next((i for i in data["items"] if i["id"] == item_id), None)
            if item is None:
                raise ShoppingError(404, "no such item")
            if action == "bought":
                if item["status"] != "bought":
                    item.update(status="bought", bought_at=_now(), bought_by=actor.id)
            elif action == "unbought":
                item.update(status="open", bought_at=None, bought_by=None)
            elif action == "delete":
                if not self._may_change(actor, item):
                    raise ShoppingError(403, "only a parent, the buyer or whoever asked for it can remove it")
                data["items"].remove(item)
                self._write(data)
                return dict(item, status="deleted")
            elif action == "edit":
                if not self._may_change(actor, item):
                    raise ShoppingError(403, "only a parent, the buyer or whoever asked for it can change it")
                if str(f.get("title") or "").strip():
                    item["title"] = str(f["title"]).strip()[:120]
                if "notes" in f:
                    item["notes"] = str(f.get("notes") or "").strip()[:500]
                if f.get("buyer"):
                    who = self.family.get(str(f["buyer"]))
                    if who is None:
                        raise ShoppingError(400, f"no such family member: {f['buyer']}")
                    item["buyer"] = who.id
            item["updated_at"] = _now()
            self._write(data)
            return item

    def forget_memo(self, memo_id: str) -> int:
        """Deleting a memo: the shopping items it put on a list go too."""
        with self._locked():
            data = self._read()
            keep = [i for i in data["items"] if i.get("memo_id") != memo_id]
            n = len(data["items"]) - len(keep)
            if n:
                data["items"] = keep
                self._write(data)
        return n

    def act_for(self, item_id: str, action: str, person_id: str = "") -> dict:
        """Home Assistant ticks an item as bought for a person (default: the item's buyer)."""
        if action not in ("bought", "unbought"):
            raise ShoppingError(403, "Home Assistant can only tick or untick items")
        item = next((i for i in self._read()["items"] if i["id"] == item_id), None)
        if item is None:
            raise ShoppingError(404, "no such item")
        who = self.family.get(person_id or item["buyer"])
        if who is None:
            raise ShoppingError(400, f"no such family member: {person_id}")
        return self.act(who, item_id, action)

    def find(self, query: str, buyer: str | None = None) -> list[dict]:
        """Open items whose words match (for "קניתי את האפוקסי")."""
        q = set(norm(query).split())
        if not q:
            return []
        out = []
        for i in self._read()["items"]:
            if i.get("status") != "open" or (buyer and i.get("buyer") != buyer):
                continue
            words = set(norm(i["title"]).split())
            if q & words:
                out.append((len(q & words), i))
        out.sort(key=lambda x: -x[0])
        return [i for _, i in out]
