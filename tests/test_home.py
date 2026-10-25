"""Home Assistant's "home" identity: the wall panel's view of the family tasks, ticks made for a person,
and what its token may reach (docs/HOME_ASSISTANT.md)."""

import os
import tempfile
import unittest
from pathlib import Path

from worker.family import Family
from worker.points import PointsConfig, PointsStore
from worker.taskstore import TaskError, TaskStore

FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True},
    "dana": {"name": "דנה", "role": "parent"},
    "yoni": {"name": "יוני", "role": "child"},
    "maya": {"name": "מאיה", "role": "child"},
}
RATED = {"effort": 4, "minutes": 20, "category": "cleaning", "chore_key": "tidy", "reason": "t",
         "rated_by": "ai", "no_coins": False}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.points = PointsStore(self.tmp / "data" / "points.json", self.fam, "Asia/Jerusalem", PointsConfig())
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, self.tmp / "Tasks.md", self.points)
        self.p = self.fam.people
        self.home = self.fam.home

    def coins(self, pid):
        return sum(ln["coins"] for ln in self.points._read()["lines"] if ln["person"] == pid and not ln["reversed"])


class Identity(Base):
    def test_token_is_home_not_a_person(self):
        tok = self.fam.home_token()
        self.assertTrue(self.fam.who(tok).is_home)
        self.assertNotIn("home", self.fam.people)
        self.assertNotIn("home", self.fam.prompt_lines())
        self.assertEqual(self.fam.home_token(), tok)              # stable
        new = self.fam.home_token(renew=True)
        self.assertNotEqual(new, tok)
        self.assertIsNone(self.fam.who(tok))                      # the old link stops working
        self.assertTrue(self.fam.who(new).is_home)

    def test_config_cannot_claim_the_home_id(self):
        fam = Family.from_config({**FAMILY_CFG, "home": {"name": "x", "role": "parent"}}, "a", self.tmp / "d2")
        self.assertNotIn("home", fam.people)


class Panel(Base):
    def test_household_tasks_only(self):
        mine = self.store.add(self.p["avi"], "לקבוע תור לרופא", self.p["avi"])          # a parent's own to-do
        kid = self.store.add(self.p["dana"], "לתלות כביסה", self.p["yoni"])
        asked = self.store.add(self.p["avi"], "לקנות חלב", self.p["dana"])              # one parent asks the other
        shared = self.store.add(self.p["dana"], "לסדר את הסלון", [self.p["avi"], self.p["dana"]])
        idea = self.store.add_idea(self.p["yoni"], "כפתור גדול")
        seen = {t["id"] for t in self.store.snapshot(self.home)["tasks"]}
        self.assertEqual(seen, {kid["id"], asked["id"], shared["id"]})
        self.assertNotIn(mine["id"], seen)
        self.assertNotIn(idea["id"], seen)

    def test_tick_counts_for_the_person(self):
        t = self.store.add(self.p["dana"], "לתלות כביסה", self.p["yoni"])
        self.store.rate(t["id"], dict(RATED))
        r = self.store.act_for(t["id"], "done")                    # no "as": the one it is for
        self.assertEqual((r["status"], r["done_by"]), ("done", "yoni"))
        self.assertGreater(self.coins("yoni"), 0)
        self.store.act_for(t["id"], "reopen", "yoni")
        self.assertEqual(self.coins("yoni"), 0)

    def test_each_of_them_needs_a_name(self):
        t = self.store.add(self.p["dana"], "לסדר חדר", [self.p["yoni"], self.p["maya"]], mode="all")
        with self.assertRaises(TaskError):
            self.store.act_for(t["id"], "done")
        r = self.store.act_for(t["id"], "done", "maya")
        self.assertEqual((r["status"], list(r["done_parts"])), ("open", ["maya"]))
        with self.assertRaises(TaskError):
            self.store.act_for(t["id"], "done", "avi")                # not on it
        with self.assertRaises(TaskError):
            self.store.act_for(t["id"], "delete", "maya")             # only ticks

    def test_private_task_is_not_found(self):
        mine = self.store.add(self.p["avi"], "לקבוע תור לרופא", self.p["avi"])
        with self.assertRaises(TaskError):
            self.store.act_for(mine["id"], "done", "avi")

    def test_created_by_home_is_open_and_visible(self):
        t = self.store.add(self.home, "לתלות כביסה", [self.p["maya"]])
        self.assertEqual(t["status"], "open")
        self.assertIn(t["id"], {x["id"] for x in self.store.snapshot(self.home)["tasks"]})
        self.assertIn(t["id"], {x["id"] for x in self.store.snapshot(self.p["maya"])["tasks"]})


class Api(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.server, cls.TestClient = server, TestClient

    def setUp(self):
        super().setUp()
        s = self.server
        s.FAMILY, s.TASKS, s.POINTS, s.TOKEN = self.fam, self.store, self.points, "admin-token-123"
        s.HOME_LINK = self.tmp / "data" / "secrets" / "home_assistant.json"
        self.c = self.TestClient(s.app)
        self.h = {"Authorization": "Bearer " + self.fam.home_token(), "X-Device-Id": "ha"}

    def test_reaches_only_the_task_list(self):
        self.assertEqual(self.c.get("/v1/tasks", headers=self.h).status_code, 200)
        self.assertEqual(self.c.get("/v1/points", headers=self.h).status_code, 200)
        self.assertEqual(self.c.get("/v1/memos", headers=self.h).status_code, 403)
        self.assertEqual(self.c.post("/v1/invite", headers=self.h, json={"person": "yoni"}).status_code, 403)
        self.assertEqual(self.c.post("/v1/settings", headers=self.h, json={}).status_code, 403)

    def test_create_and_tick(self):
        r = self.c.post("/v1/tasks", headers=self.h, json={"title": "לתלות כביסה"})
        self.assertEqual(r.status_code, 400)                       # must say for whom
        r = self.c.post("/v1/tasks", headers=self.h, json={"title": "לתלות כביסה", "assignee": "maya"})
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()["id"]
        r = self.c.post(f"/v1/tasks/{tid}/done", headers=self.h, json={"as": "maya"})
        self.assertEqual((r.status_code, r.json()["done_by"]), (200, "maya"))
        self.assertEqual(self.c.post(f"/v1/tasks/{tid}/delete", headers=self.h, json={}).status_code, 403)

    def test_link(self):
        bad = self.c.post("/v1/home/link", headers=self.h, json={"url": "nope", "token": "x"})
        self.assertEqual(bad.status_code, 400)
        r = self.c.post("/v1/home/link", headers=self.h,
                        json={"url": "https://ha.example.ts.net/", "token": "t" * 40})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.server.home_link()["url"], "https://ha.example.ts.net")
        admin = {"Authorization": "Bearer admin-token-123", "X-Device-Id": "p"}
        self.assertTrue(self.c.get("/v1/home", headers=admin).json()["linked"])
        kid = {"Authorization": "Bearer " + self.fam.token_for("yoni"), "X-Device-Id": "p"}
        self.assertEqual(self.c.post("/v1/home/link", headers=kid, json={}).status_code, 403)
        self.c.post("/v1/home/link", headers=self.h, json={"url": "", "token": ""})
        self.assertEqual(self.server.home_link(), {})


class Voice(Base):
    """The `home` tool: a memo switches something in the house through Home Assistant's Assist."""

    class FakeHouse:
        def __init__(self, reply=None, error=None):
            self.reply, self.error, self.sent = reply, error, []

        def command(self, text):
            self.sent.append(text)
            if self.error:
                raise self.error
            return self.reply

    def notes(self, house, speaker="avi"):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from worker.tools import MemoContext, Notes
        tz = ZoneInfo("Asia/Jerusalem")
        return Notes(self.tmp / "notes", tz, MemoContext("abcdef0123456789", datetime(2026, 10, 25, 20, 0, tzinfo=tz)),
                     store=self.store, family=self.fam, speaker=self.p[speaker], home=house)

    def test_parse(self):
        from worker.home import parse
        r = parse({"response": {"response_type": "action_done", "speech": {"plain": {"speech": "Turned off the lights"}},
                                "data": {"success": [{"name": "Kitchen lights", "id": "light.kitchen_lights"}],
                                         "failed": []}}})
        self.assertEqual((r.ok, r.speech, r.changed), (True, "Turned off the lights", ["Kitchen lights"]))
        r = parse({"response": {"response_type": "error", "speech": {"plain": {"speech": "No device called x"}},
                                "data": {"code": "no_intent_match"}}})
        self.assertFalse(r.ok)
        r = parse({"response": {"response_type": "action_done", "data": {"success": [],
                                                                        "failed": [{"name": "Boiler"}]}}})
        self.assertFalse(r.ok)
        self.assertIn("Boiler", r.speech)

    def test_tool_only_when_linked_and_for_everyone(self):
        from worker.tools import registry
        self.assertNotIn("home", registry(self.notes(None)))
        self.assertIn("home", registry(self.notes(self.FakeHouse())))
        self.assertIn("home", registry(self.notes(self.FakeHouse(), speaker="yoni")))   # the kids too

    def test_done_and_logged(self):
        from worker.home import Reply
        house = self.FakeHouse(Reply(True, "Turned off the lights", ["Kitchen lights"]))
        n = self.notes(house)
        out = n.control_home("turn off the kitchen lights")
        self.assertTrue(out.startswith("ok:"), out)
        self.assertEqual(house.sent, ["turn off the kitchen lights"])
        self.assertEqual(n.actions[0]["tool"], "home")
        self.assertIn("Turned off", (self.tmp / "notes" / "Home.md").read_text(encoding="utf-8"))

    def test_failure_goes_back_to_the_model(self):
        from worker.home import Reply
        n = self.notes(self.FakeHouse(Reply(False, "No area called garage", [])))
        self.assertTrue(n.control_home("turn on the garage light").startswith("not done"))
        n = self.notes(self.FakeHouse(error=RuntimeError("timeout")))
        self.assertIn("timeout", n.control_home("turn on the light"))


if __name__ == "__main__":
    unittest.main()
