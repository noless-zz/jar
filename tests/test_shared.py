"""Shared (family) tasks: several people, "any" (one of them is enough) or "all" (each of them)."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.family import Family
from worker.points import PointsConfig, PointsStore
from worker.taskstore import TaskError, TaskStore, owners, shared_mode
from worker.tools import MemoContext, Notes

FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True, "aliases": ["Avi"]},
    "dana": {"name": "דנה", "role": "parent", "aliases": ["Dana"]},
    "yoni": {"name": "יוני", "role": "child", "aliases": ["Yoni"]},
    "maya": {"name": "מאיה", "role": "child", "aliases": ["Maya"]},
}
TZ = ZoneInfo("Asia/Jerusalem")
RATED = {"effort": 4, "minutes": 20, "category": "cleaning", "chore_key": "tidy-living-room", "reason": "t",
         "rated_by": "ai", "no_coins": False}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.points = PointsStore(self.tmp / "data" / "points.json", self.fam, "Asia/Jerusalem", PointsConfig())
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, self.tmp / "Tasks.md", self.points)
        self.p = self.fam.people

    def shared(self, mode, who=("yoni", "maya"), by="dana"):
        t = self.store.add(self.p[by], "לסדר את הסלון", [self.p[i] for i in who], mode=mode)
        self.store.rate(t["id"], dict(RATED))
        return t

    def coins(self, pid):
        return sum(ln["coins"] for ln in self.points._read()["lines"] if ln["person"] == pid and not ln["reversed"])

    def get(self, tid, viewer="avi"):
        return next(x for x in self.store.snapshot(self.p[viewer])["tasks"] if x["id"] == tid)


class Shape(Base):
    def test_fields_and_old_clients(self):
        t = self.shared("all")
        self.assertEqual((t["assignee"], t["assignees"], t["mode"]), ("yoni", ["yoni", "maya"], "all"))
        self.assertEqual((owners(t), shared_mode(t)), (["yoni", "maya"], "all"))
        one = self.store.add(self.p["dana"], "x", [self.p["yoni"], self.p["yoni"]], mode="all")
        self.assertNotIn("assignees", one)                      # one person: a plain task
        self.assertEqual(shared_mode(one), "any")

    def test_everyone_on_it_sees_it(self):
        t = self.store.add(self.p["avi"], "לקנות מתנה", [self.p["dana"], self.p["avi"]])
        for pid in ("avi", "dana"):
            self.assertIn(t["id"], [x["id"] for x in self.store.snapshot(self.p[pid])["tasks"]])
        self.assertEqual(self.store.snapshot(self.p["yoni"])["tasks"], [])
        k = self.shared("any")
        self.assertIn(k["id"], [x["id"] for x in self.store.snapshot(self.p["maya"])["tasks"]])

    def test_child_sharing_with_others_needs_ok(self):
        t = self.store.add(self.p["yoni"], "לסדר את הסלון", [self.p["yoni"], self.p["maya"]])
        self.assertEqual(t["status"], "requested")

    def test_markdown_lists_it_under_each(self):
        self.shared("all")
        md = (self.tmp / "Tasks.md").read_text(encoding="utf-8")
        self.assertEqual(md.count("לסדר את הסלון"), 2)
        self.assertIn("each of us", md)


class AnyMode(Base):
    def test_first_one_finishes_it_and_is_paid(self):
        t = self.shared("any")
        r = self.store.act(self.p["maya"], t["id"], "done")
        self.assertEqual((r["status"], r["done_by"]), ("done", "maya"))
        self.assertEqual((self.coins("maya"), self.coins("yoni")), (20, 0))
        self.assertEqual(self.get(t["id"], "maya")["coins"], 20)
        self.store.act(self.p["maya"], t["id"], "reopen")
        self.assertEqual(self.coins("maya"), 0)

    def test_parent_ticking_pays_the_first(self):
        t = self.shared("any")
        self.store.act(self.p["dana"], t["id"], "done")
        self.assertEqual(self.coins("yoni"), 20)


class AllMode(Base):
    def test_each_part_then_done(self):
        t = self.shared("all")
        r = self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual(r["status"], "open")
        self.assertEqual(list(r["done_parts"]), ["yoni"])
        self.assertEqual(r["award"]["coins"], 20)
        again = self.store.act(self.p["yoni"], t["id"], "done")            # retried tick
        self.assertFalse(again["award"]["new"])
        mine = self.get(t["id"], "yoni")
        self.assertTrue(mine["paid"])
        self.assertFalse(self.get(t["id"], "maya").get("paid"))
        r = self.store.act(self.p["maya"], t["id"], "done")
        self.assertEqual((r["status"], r["done_by"]), ("done", "maya"))
        self.assertEqual((self.coins("yoni"), self.coins("maya")), (20, 20))

    def test_undo_my_part_only(self):
        t = self.shared("all")
        self.store.act(self.p["yoni"], t["id"], "done")
        r = self.store.act(self.p["yoni"], t["id"], "reopen")
        self.assertEqual((r["status"], r.get("done_parts")), ("open", {}))
        self.assertEqual(self.coins("yoni"), 0)

    def test_reopen_whole_task_takes_back_from_all(self):
        t = self.shared("all")
        self.store.act(self.p["yoni"], t["id"], "done")
        self.store.act(self.p["maya"], t["id"], "done")
        self.store.act(self.p["dana"], t["id"], "reopen")
        self.assertEqual((self.coins("yoni"), self.coins("maya")), (0, 0))
        self.assertNotIn("done_parts", self.get(t["id"]))

    def test_parent_ticks_for_everyone_left(self):
        t = self.shared("all")
        self.store.act(self.p["yoni"], t["id"], "done")
        r = self.store.act(self.p["dana"], t["id"], "done")
        self.assertEqual(r["status"], "done")
        self.assertEqual((self.coins("yoni"), self.coins("maya")), (20, 20))

    def test_rating_change_repays_each(self):
        t = self.shared("all")
        self.store.act(self.p["yoni"], t["id"], "done")
        self.store.act(self.p["maya"], t["id"], "done")
        self.store.set_points(self.p["dana"], t["id"], effort=6)
        self.assertEqual((self.coins("yoni"), self.coins("maya")), (30, 30))

    def test_edit_owners_and_mode(self):
        t = self.shared("all")
        self.store.act(self.p["maya"], t["id"], "done")
        r = self.store.act(self.p["dana"], t["id"], "edit", fields={"assignees": ["yoni"]})
        self.assertEqual(self.coins("maya"), 0)                  # taken off: her part's coins go back
        self.assertNotIn("assignees", r)
        r = self.store.act(self.p["dana"], t["id"], "edit", fields={"assignees": ["yoni", "maya"], "mode": "any"})
        self.assertEqual((r["assignees"], r["mode"]), (["yoni", "maya"], "any"))
        with self.assertRaises(TaskError):
            self.store.act(self.p["dana"], t["id"], "edit", fields={"assignees": ["bob"]})

    def test_taking_off_the_last_one_left_finishes_it(self):
        t = self.shared("all")
        self.store.act(self.p["yoni"], t["id"], "done")
        r = self.store.act(self.p["dana"], t["id"], "edit", fields={"assignees": ["yoni", "dana"]})
        self.assertEqual(r["status"], "open")
        r = self.store.act(self.p["dana"], t["id"], "edit", fields={"assignees": ["yoni", "maya"]})
        self.assertEqual(r["status"], "open")


class Voice(Base):
    def test_memo_makes_a_shared_task(self):
        n = Notes(self.tmp / "notes", TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 18, 19, 0, tzinfo=TZ)),
                  store=self.store, family=self.fam, speaker=self.p["avi"])
        out = n.add_task("לסדר את הסלון", for_person="yoni", also_for=["maya"], together="all")
        self.assertIn("each of them", out)
        t = self.store.snapshot(self.p["avi"])["tasks"][0]
        self.assertEqual((t["assignees"], t["mode"]), (["yoni", "maya"], "all"))
        from worker.tools import ToolError
        with self.assertRaises(ToolError):
            n.add_task("x", for_person="yoni", also_for=["bob"])


class ApiShared(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.server, cls.TestClient = server, TestClient

    def test_create_with_several(self):
        self.server.FAMILY, self.server.TASKS, self.server.TOKEN = self.fam, self.store, "admin-token-123"
        c = self.TestClient(self.server.app)
        h = {"Authorization": "Bearer " + self.fam.token_for("dana"), "X-Device-Id": "t"}
        r = c.post("/v1/tasks", headers=h, json={"title": "ארוחת שישי", "assignees": ["yoni", "maya"], "mode": "all"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["assignees"], r.json()["mode"]), (["yoni", "maya"], "all"))
        r = c.post("/v1/tasks", headers=h, json={"title": "x", "assignees": ["yoni", "bob"]})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
