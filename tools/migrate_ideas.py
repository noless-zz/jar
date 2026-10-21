"""One-off (2026-10-21): turn Livne's app ideas, filed as ordinary tasks for Noam, into Jar ideas (kind "idea").

    python tools/migrate_ideas.py            dry run: says what it would do
    python tools/migrate_ideas.py --apply    does it (safe to run again: nothing is paid twice)

What it does, per idea: kind "idea", no coins for building it; coins Noam was paid for it are taken back; the one
who suggested it gets the idea credit ([points] idea_coins when accepted — dated when it was filed — and
idea_shipped_bonus when shipped — dated when it was done). Runs alongside the server: both use the same lock files.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from worker import config as config_mod  # noqa: E402
from worker.family import Family  # noqa: E402
from worker.points import PointsConfig, PointsStore  # noqa: E402
from worker.taskstore import TaskStore  # noqa: E402

# id -> what it becomes: "shipped" (built already), "accepted" (being built), "new" (waits for the admin)
IDEAS = {
    "c5aaff032d": "shipped",    # להוסיף אפשרות למשימות משפחתיות
    "b7e1464f79": "shipped",    # להוסיף אפשרות ללוח שנה משפחתי באפליקציה
    "4a0ec0857c": "accepted",   # משימות רב פעמיות (built 2026-10-21; tap 🚀 once app 1.3.0 is out)
    "faa716a766": "new",        # ...להוסיף תיאור משימה כדי שלא יהיה אפשר לעשות משימות שלא באמת משימות
}


def main(apply: bool) -> None:
    cfg = config_mod.load()
    raw = tomllib.loads((cfg.root / "config.toml").read_text(encoding="utf-8")) \
        if (cfg.root / "config.toml").exists() else {}
    fam = Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir, cfg.contacts)
    points = PointsStore(cfg.data_dir / "points.json", fam, cfg.timezone, PointsConfig.from_raw(raw.get("points")))
    store = TaskStore(cfg.data_dir / "tasks.json", fam, cfg.notes_dir / "Tasks.md", points)
    admin = fam.admin.id
    tasks = {t["id"]: t for t in store._read()["tasks"]}
    for tid, stage in IDEAS.items():
        t = tasks.get(tid)
        if t is None:
            print(f"{tid}: not found (purged?) — skipped")
            continue
        paid = [ln for ln in points._read()["lines"] if ln.get("task_id") == tid and not ln.get("reversed")
                and ln.get("person") == admin and ln.get("kind") == "task"]
        print(f"{tid} “{t['title'][:50]}” by {t['created_by']}: {t.get('kind', 'task')}/{t['status']} -> idea/{stage}"
              + (f"; take back {sum(ln['coins'] for ln in paid)} coins from {admin}" if paid else ""))
        if not apply:
            continue
        with store._locked():
            data = store._read()
            x = next(y for y in data["tasks"] if y["id"] == tid)
            x["kind"] = "idea"
            x["assignee"] = admin
            x["points"] = {"no_coins": True, "rated_by": "rule", "reason": "Jar idea"}
            x["status"] = {"shipped": "done", "accepted": "open", "new": "requested"}[stage]
            if stage != "shipped":
                x["done_at"] = x["done_by"] = None
            x["migrated"] = "2026-10-21 tasks -> ideas"
            store._write(data)
            t = dict(x)
        if paid:
            points.reverse(tid, "became a Jar idea (no coins for building it)", admin)
        if stage in ("accepted", "shipped"):
            a = points.credit_idea(t, "accepted", t.get("created_at"))
            print(f"   idea credit to {t['created_by']}: {a['coins'] if a else 0}")
        if stage == "shipped":
            b = points.credit_idea(t, "shipped", t.get("done_at") or t.get("created_at"))
            print(f"   shipped bonus to {t['created_by']}: {b['coins'] if b else 0}")
    if not apply:
        print("\n(dry run — add --apply to do it)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
