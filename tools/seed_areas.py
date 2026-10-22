"""One-off (2026-10-22): the family's areas of responsibility and their starter recurring tasks.

    python tools/seed_areas.py            dry run
    python tools/seed_areas.py --apply    does it (skips areas and recurring tasks that already exist)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from worker import areas as A  # noqa: E402
from worker import config as config_mod  # noqa: E402
from worker.family import Family  # noqa: E402
from worker.taskstore import TaskStore  # noqa: E402

OWNERS = {"kitchen": "noam", "floors": "sveta", "laundry": "alona", "food": "livne"}
# (area, title, rule, time)
STARTER_TASKS = [
    ("kitchen", "לסדר ולנגב את המטבח", "daily", "21:00"),
    ("floors", "לשטוף את הרצפות", "weekly:sun,wed", ""),
    ("laundry", "לקפל כביסה ולהכניס לארונות", "weekly:mon,thu", "17:00"),
    ("food", "להכין רשימת קניות", "weekly:wed", "17:00"),
    ("food", "לבדוק מה חסר במקרר", "weekly:sun", "17:00"),
]


def main(apply: bool) -> None:
    cfg = config_mod.load()
    fam = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
    store = TaskStore(cfg.data_dir / "tasks.json", fam, cfg.notes_dir / "Tasks.md")
    admin = fam.admin
    have = {a["id"] for a in store.areas()}
    for a in A.STARTER:
        owner = fam.get(OWNERS[a["id"]])
        print(f"area {a['emoji']} {a['name']} -> {owner.name if owner else '?'}"
              + (" (exists, skipped)" if a["id"] in have else ""))
        if apply and a["id"] not in have and owner is not None:
            store.area_act(admin, "add", fields={**a, "owner": owner.id})
    titles = {s["title"] for s in store._read()["series"] if s.get("status") != "ended"}
    for area, title, rule, time in STARTER_TASKS:
        owner = fam.get(OWNERS[area])
        print(f"recurring “{title}” {rule} {time} for {owner.name}" + (" (exists, skipped)" if title in titles else ""))
        if apply and title not in titles:
            t = store.add_series(admin, title, [owner], rule, time, area=area)
            print(f"   first one {t['due']}")
    if not apply:
        print("\n(dry run — add --apply)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
