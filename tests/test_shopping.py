"""Shopping lists: one per family member (what they will buy), filled by the family, by memos and by
Home Assistant (worker/shopping.py)."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.family import Family
from worker.shopping import ShoppingError, ShoppingStore, norm
from worker.taskstore import TaskStore
from worker.tools import MemoContext, Notes, ToolError, registry

FAMILY_CFG = {
    "noam": {"name": "נועם", "role": "parent", "admin": True, "aliases": ["אבא"]},
    "sveta": {"name": "סווטה", "role": "parent", "aliases": ["אמא"]},
    "livne": {"name": "ליבנה", "role": "child"},
    "alona": {"name": "אלונה", "role": "child"},
}
TZ = ZoneInfo("Asia/Jerusalem")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.p = self.fam.people
        self.food_owner = "livne"
        self.shop = ShoppingStore(self.tmp / "data" / "shopping.json", self.fam, lambda: self.food_owner)


class Store(Base):
    def test_request_goes_to_the_buyer(self):
        [i] = self.shop.add(self.p["livne"], "אפוקסי", self.p["noam"])
        self.assertEqual((i["buyer"], i["requested_by"], i["status"]), ("noam", "livne", "open"))

    def test_no_buyer_goes_to_the_food_owner_else_the_speaker(self):
        [i] = self.shop.add(self.p["noam"], "חלב")
        self.assertEqual(i["buyer"], "livne")
        self.food_owner = None
        [i] = self.shop.add(self.p["sveta"], "לחם")
        self.assertEqual(i["buyer"], "sveta")

    def test_no_doubles_on_one_list(self):
        a = self.shop.add(self.p["noam"], ["חלב", "ביצים"])
        b = self.shop.add(self.p["sveta"], ["החלב"], notes="3%")
        self.assertEqual(b[0]["id"], a[0]["id"])
        self.assertIn("3%", b[0]["notes"])
        self.assertEqual(len(self.shop.snapshot()["items"]), 2)

    def test_bought_and_back(self):
        [i] = self.shop.add(self.p["noam"], "חלב")
        r = self.shop.act(self.p["alona"], i["id"], "bought")
        self.assertEqual((r["status"], r["bought_by"]), ("bought", "alona"))
        self.assertEqual(self.shop.snapshot()["items"][0]["status"], "bought")     # still visible today
        self.assertEqual(self.shop.act(self.p["alona"], i["id"], "unbought")["status"], "open")

    def test_who_may_remove(self):
        [i] = self.shop.add(self.p["livne"], "אפוקסי", self.p["noam"])
        with self.assertRaises(ShoppingError):
            self.shop.act(self.p["alona"], i["id"], "delete")                       # not hers
        self.shop.act(self.p["livne"], i["id"], "delete")
        self.assertEqual(self.shop.snapshot()["items"], [])

    def test_find_and_norm(self):
        self.shop.add(self.p["livne"], ["אפוקסי שקוף", "חלב"], self.p["noam"])
        self.assertEqual(norm("The Milk!"), "milk")
        self.assertEqual([i["title"] for i in self.shop.find("האפוקסי")], ["אפוקסי שקוף"])

    def test_home_ticks_for_the_buyer(self):
        [i] = self.shop.add(self.fam.home, "סוללות", self.p["noam"])
        self.assertEqual(i["requested_by"], "home")
        self.assertEqual(self.shop.act_for(i["id"], "bought")["bought_by"], "noam")
        with self.assertRaises(ShoppingError):
            self.shop.act_for(i["id"], "delete")


class Memo(Base):
    def notes(self, speaker):
        store = TaskStore(self.tmp / "data" / "tasks.json", self.fam)
        return Notes(self.tmp / "notes", TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 25, 20, 0, tzinfo=TZ)),
                     store=store, family=self.fam, speaker=self.p[speaker], shopping=self.shop)

    def test_tool_for_everyone(self):
        self.assertIn("shopping", registry(self.notes("alona")))
        self.assertIn("shopping", registry(self.notes("noam")))

    def test_ask_dad_to_buy(self):
        n = self.notes("livne")
        out = n.shopping_list(add=["אפוקסי"], buyer="noam")
        self.assertIn("נועם", out)
        [i] = self.shop.snapshot()["items"]
        self.assertEqual((i["title"], i["buyer"], i["requested_by"], i["memo_id"]),
                         ("אפוקסי", "noam", "livne", "abcdef0123456789"))
        self.assertEqual(n.actions[0]["tool"], "shopping")

    def test_bought_by_words(self):
        self.shop.add(self.p["livne"], "אפוקסי", self.p["noam"])
        out = self.notes("noam").shopping_list(bought=["האפוקסי"])
        self.assertIn("✓", out)
        self.assertEqual(self.shop.snapshot()["items"][0]["status"], "bought")
        self.assertIn("not on", self.notes("noam").shopping_list(bought=["טונה"]))

    def test_needs_something(self):
        with self.assertRaises(ToolError):
            self.notes("noam").shopping_list()


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
        s.FAMILY, s.SHOPPING, s.TOKEN = self.fam, self.shop, "admin-token-123"
        self.c = self.TestClient(s.app)

    def h(self, who):
        tok = self.fam.home_token() if who == "home" else self.fam.token_for(who)
        return {"Authorization": "Bearer " + tok, "X-Device-Id": "t"}

    def test_add_list_tick(self):
        r = self.c.post("/v1/shopping", headers=self.h("livne"), json={"items": ["אפוקסי"], "buyer": "noam"})
        self.assertEqual(r.status_code, 201, r.text)
        iid = r.json()["items"][0]["id"]
        snap = self.c.get("/v1/shopping", headers=self.h("alona")).json()
        self.assertEqual((snap["items"][0]["buyer"], snap["default_buyer"]), ("noam", "livne"))
        r = self.c.post(f"/v1/shopping/{iid}/bought", headers=self.h("noam"))
        self.assertEqual(r.json()["status"], "bought")
        self.assertEqual(self.c.post("/v1/shopping", headers=self.h("noam"), json={"items": ["x"], "buyer": "bob"})
                         .status_code, 400)

    def test_home(self):
        r = self.c.post("/v1/shopping", headers=self.h("home"), json={"items": ["סוללות"], "buyer": "sveta"})
        iid = r.json()["items"][0]["id"]
        self.assertEqual(self.c.post(f"/v1/shopping/{iid}/bought", headers=self.h("home"), json={}).json()["bought_by"],
                         "sveta")
        self.assertEqual(self.c.post(f"/v1/shopping/{iid}/delete", headers=self.h("home"), json={}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
