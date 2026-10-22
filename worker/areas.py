"""Areas of responsibility (תחומי אחריות): the kitchen is Noam's, the floors Sveta's, and so on.

An area: {"id", "name", "emoji", "owner" (family id), "description" (for the AI), "keywords" [...]}.
A new task is matched to an area by its words (keywords, longest match wins), or, when no keyword matches,
by the AI when it rates the task (worker/effort.py). A chore said without naming anyone stays with whoever
said it; when it belongs to someone else's area the task carries "area_suggest" and the app offers to move it.
A move ("handover") waits for the area's owner or a parent to approve it.
"""

from __future__ import annotations

import re

STARTER = [
    {"id": "kitchen", "name": "מטבח", "emoji": "🍳", "owner_hint": ["noam", "נועם"],
     "description": "cleaning and organizing the kitchen: dishes, dishwasher, counters, sink, stove, kitchen cupboards",
     "keywords": ["מטבח", "כלים", "מדיח", "כיור", "שיש", "סירים", "מחבת", "תנור", "כיריים", "dishes", "dishwasher",
                  "kitchen"]},
    {"id": "floors", "name": "רצפות", "emoji": "🧽", "owner_hint": ["sveta", "סווטה"],
     "description": "floors: sweeping, vacuuming, washing and mopping the floors",
     "keywords": ["רצפ", "שואב", "לשאוב", "שאיבה", "מגב", "סמרטוט", "ספונג׳ה", "ספונגה", "לטאטא", "מטאטא", "floor",
                  "vacuum", "mop", "sweep"]},
    {"id": "laundry", "name": "כביסה", "emoji": "👕", "owner_hint": ["alona", "אלונה"],
     "description": "laundry and clothes: washing machine, dryer, hanging, folding, putting clothes in the cupboards",
     "keywords": ["כביס", "לקפל", "קיפול", "בגדים", "גרביים", "מייבש", "לתלות", "laundry", "fold", "clothes"]},
    {"id": "food", "name": "אוכל וקניות", "emoji": "🛒", "owner_hint": ["livne", "ליבנה"],
     "description": "food and shopping (groceries, shopping lists, what's missing in the fridge, meals) and "
                    "general organization of the shared home",
     "keywords": ["קניות", "סופר", "מצרכים", "רשימת קניות", "נגמר", "חסר במקרר", "ארוחה", "לבשל", "groceries",
                  "shopping", "סידור כללי", "לסדר את הבית"]},
]

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def match(text: str, areas: list[dict]) -> str | None:
    """The one area whose keywords appear in the text, or None: none matched, or several did ("לשטוף את הרצפה
    במטבח" — floors or kitchen?), and then the AI decides from the areas' descriptions."""
    low = (text or "").casefold()
    hits = [a["id"] for a in areas
            if any(len(k) >= 2 and k in low for k in (str(kw).strip().casefold() for kw in a.get("keywords") or []))]
    return hits[0] if len(hits) == 1 else None


def clean_keywords(raw) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[,\n،]+", raw)
    out = []
    for k in raw or []:
        k = str(k).strip()[:40]
        if len(k) >= 2 and k not in out:
            out.append(k)
    return out[:40]


def slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:24] or "area"
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid
