"""Areas of responsibility: matching, the move suggestion, approval by the owner or a parent, managing areas."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker import areas as A
from worker import effort
from worker.family import Family
from worker.points import PointsConfig, PointsStore
from worker.taskstore import TaskError, TaskStore, owners

TZ = ZoneInfo("Asia/Jerusalem")
FAMILY_CFG = {
    "noam": {"name": "נועם", "role": "parent", "admin": True},
    "sveta": {"name": "סווטה", "role": "parent"},
    "alona": {"name": "אלונה", "role": "child"},
    "livne": {"name": "ליבנה", "role": "child"},
}
OWNERS = {"kitchen": "noam", "floors": "sveta", "laundry": "alona", "food": "livne"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "t", self.tmp / "data")
        self.points = PointsStore(self.tmp / "data" / "points.json", self.fam, "Asia/Jerusalem", PointsConfig())
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, None, self.points)
        self.p = self.fam.people
        for a in A.STARTER:
            self.store.area_act(self.p["noam"], "add", fields={**a, "owner": OWNERS[a["id"]]})

    def get(self, tid):
        return next(t for t in self.store._read()["tasks"] if t["id"] == tid)


class Matching(Base):
    def test_words(self):
        areas = self.store.areas()
        for text, want in [("לשטוף את הרצפה בסלון", "floors"), ("להוציא כלים מהמדיח", "kitchen"),
                           ("לקפל כביסה", "laundry"), ("נגמר החלב", "food"), ("לעשות קניות בסופר", "food"),
                           ("לסדר את החדר שלי", None), ("לקנות מתנה לסבתא", None),
                           ("לשטוף את הרצפה במטבח", None)]:            # two areas: the AI decides
            self.assertEqual(A.match(text, areas), want, text)

    def test_ai_prompt_and_parse(self):
        prompt = effort.build_prompt("להוריד את הזבל", "", self.p["noam"], [], self.store.areas())
        self.assertIn("floors = floors", prompt)
        out = effort.parse('{"effort": 2, "category": "cleaning", "chore_key": "x", "area": "kitchen"}', "t",
                           ["kitchen", "floors"])
        self.assertEqual(out["area"], "kitchen")
        self.assertNotIn("area", effort.parse('{"effort": 2, "area": "garden"}', "t", ["kitchen"]))


class Suggest(Base):
    def test_unnamed_chore_stays_and_suggests_the_owner(self):
        t = self.store.add(self.p["noam"], "לשטוף את הרצפה", self.p["noam"])
        self.assertEqual((t["assignee"], t["area"], t["area_suggest"]), ("noam", "floors", "sveta"))

    def test_no_suggestion_for_the_owner_or_a_named_person(self):
        own = self.store.add(self.p["sveta"], "לשטוף את הרצפה", self.p["sveta"])
        self.assertNotIn("area_suggest", own)
        named = self.store.add(self.p["noam"], "לשטוף את הרצפה", self.p["alona"])
        self.assertNotIn("area_suggest", named)

    def test_ai_area_when_no_keyword(self):
        t = self.store.add(self.p["alona"], "להוריד את הזבל", self.p["alona"])
        self.assertNotIn("area", t)
        self.store.rate(t["id"], {"effort": 2, "minutes": 3, "category": "kitchen", "chore_key": "trash",
                                  "reason": "", "rated_by": "ai", "no_coins": False, "area": "kitchen"})
        got = self.get(t["id"])
        self.assertEqual((got["area"], got["area_suggest"]), ("kitchen", "noam"))
        self.assertNotIn("area", got["points"])


class Handover(Base):
    def test_owner_approves(self):
        t = self.store.add(self.p["livne"], "לשטוף את הרצפה", self.p["livne"])
        self.store.act(self.p["livne"], t["id"], "handover")
        got = self.get(t["id"])
        self.assertEqual((got["assignee"], got["handover"]["to"]), ("livne", "sveta"))
        self.assertTrue(any(x["id"] == t["id"] for x in self.store.snapshot(self.p["sveta"])["tasks"]))
        with self.assertRaises(TaskError):
            self.store.act(self.p["alona"], t["id"], "handover_accept")      # not hers, not a parent
        self.store.act(self.p["sveta"], t["id"], "handover_accept")
        got = self.get(t["id"])
        self.assertEqual((owners(got), "handover" in got, "area_suggest" in got), (["sveta"], False, False))

    def test_a_parent_approves_but_not_their_own_request(self):
        t = self.store.add(self.p["noam"], "לקפל כביסה", self.p["noam"])
        self.store.act(self.p["noam"], t["id"], "handover")
        with self.assertRaises(TaskError):
            self.store.act(self.p["noam"], t["id"], "handover_accept")       # asked for it himself
        self.store.act(self.p["sveta"], t["id"], "handover_accept")          # the other parent may
        self.assertEqual(owners(self.get(t["id"])), ["alona"])

    def test_decline_keeps_it_and_hides_the_suggestion(self):
        t = self.store.add(self.p["alona"], "לסדר את הכלים", self.p["alona"])
        self.store.act(self.p["alona"], t["id"], "handover")
        self.store.act(self.p["noam"], t["id"], "handover_decline")
        got = self.get(t["id"])
        self.assertEqual((owners(got), got.get("area_suggest"), got.get("handover")), (["alona"], None, None))

    def test_dismiss_the_suggestion(self):
        t = self.store.add(self.p["sveta"], "לעשות קניות", self.p["sveta"])
        self.assertEqual(t["area_suggest"], "livne")
        self.store.act(self.p["sveta"], t["id"], "dismiss_suggest")
        self.assertIsNone(self.get(t["id"]).get("area_suggest"))

    def test_admin_taking_it_needs_no_approval(self):
        t = self.store.add(self.p["alona"], "לשטוף כלים", self.p["alona"])
        self.store.act(self.p["noam"], t["id"], "handover", fields={"to": "noam"})
        self.assertEqual(owners(self.get(t["id"])), ["noam"])

    def test_over_the_api(self):
        import os
        os.environ.setdefault("JAR_DEVICE_TOKEN", "t")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        server.FAMILY, server.TASKS = self.fam, self.store
        c = TestClient(server.app)
        h = lambda who: {"Authorization": "Bearer " + self.fam.token_for(who), "X-Device-Id": "t"}  # noqa: E731
        t = c.post("/v1/tasks", headers=h("livne"), json={"title": "לקפל כביסה"}).json()
        self.assertEqual(t["area_suggest"], "alona")
        self.assertEqual(c.post(f"/v1/tasks/{t['id']}/handover", headers=h("livne")).status_code, 200)
        r = c.post(f"/v1/tasks/{t['id']}/handover_accept", headers=h("alona"))
        self.assertEqual(r.json()["assignee"], "alona")
        r = c.post("/v1/areas", headers=h("sveta"), json={"name": "גינה", "owner": "livne", "keywords": ["גינה"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(c.post(f"/v1/areas/{r.json()['id']}/delete", headers=h("livne")).status_code, 403)
        self.assertEqual(c.post(f"/v1/areas/{r.json()['id']}/delete", headers=h("sveta")).status_code, 200)


class Manage(Base):
    def test_only_parents(self):
        with self.assertRaises(TaskError):
            self.store.area_act(self.p["livne"], "add", fields={"name": "גינה", "owner": "livne"})

    def test_add_edit_delete(self):
        a = self.store.area_act(self.p["sveta"], "add", fields={"name": "גינה", "emoji": "🌱", "owner": "livne",
                                                               "keywords": "להשקות, עציצים, גינה"})
        t = self.store.add(self.p["noam"], "להשקות את העציצים", self.p["noam"])
        self.assertEqual((t["area"], t["area_suggest"]), (a["id"], "livne"))
        self.store.area_act(self.p["noam"], "edit", a["id"], {"owner": "alona"})
        self.assertEqual(self.get(t["id"])["area_suggest"], "alona")
        self.store.area_act(self.p["noam"], "delete", a["id"])
        self.assertNotIn("area", self.get(t["id"]))
        self.assertEqual(len(self.store.areas()), 4)

    def test_new_owner_takes_the_recurring_tasks(self):
        t = self.store.add_series(self.p["noam"], "לשטוף את הרצפות", [self.p["sveta"]], "weekly:sun,wed",
                                  now=datetime(2026, 10, 22, 9, tzinfo=TZ))
        self.assertEqual(self.store._read()["series"][0]["area"], "floors")
        self.store.area_act(self.p["noam"], "edit", "floors", {"owner": "alona"})
        self.assertEqual(self.store._read()["series"][0]["owners"], ["alona"])
        self.assertEqual(owners(self.get(t["id"])), ["alona"])

    def test_snapshot_has_areas(self):
        self.assertEqual([a["id"] for a in self.store.snapshot(self.p["livne"])["areas"]],
                         ["kitchen", "floors", "laundry", "food"])


if __name__ == "__main__":
    unittest.main()
