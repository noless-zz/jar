"""Several people did a task together: it's done and its coins are split between them (#21)."""

import unittest

from worker.taskstore import TaskError
from tests.test_shared import RATED, Base


class DoneTogether(Base):
    def one(self, who="dana", by="dana", effort=4):
        t = self.store.add(self.p[by], "להזמין גז ולהתקין", [self.p[who]])
        self.store.rate(t["id"], dict(RATED, effort=effort))
        return t

    def test_split_evenly(self):
        t = self.one()                                          # 20 coins
        r = self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["dana", "avi"]})
        self.assertEqual((r["status"], r["done_with"]), ("done", ["dana", "avi"]))
        self.assertEqual((self.coins("dana"), self.coins("avi")), (10, 10))
        self.assertEqual(r["award"]["split"], 2)
        self.assertEqual(self.get(t["id"], "avi")["coins"], 10)

    def test_comma_string_and_remainder_to_the_first(self):
        t = self.one(effort=3)                                  # 15 coins between two: 8 + 7
        self.store.act(self.p["dana"], t["id"], "done", None, {"as": "dana,avi"})
        self.assertEqual((self.coins("dana"), self.coins("avi")), (8, 7))
        lines = [ln for ln in self.points._read()["lines"] if not ln["reversed"]]
        self.assertTrue(all(ln["split"] == 2 for ln in lines))

    def test_retried_tick_pays_once(self):
        t = self.one()
        self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["dana", "avi"]})
        self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["avi", "dana"]})
        self.assertEqual((self.coins("dana"), self.coins("avi")), (10, 10))
        self.assertEqual(len(self.points._read()["lines"]), 2)

    def test_change_who_did_it_after_done(self):
        t = self.one()
        self.store.act(self.p["dana"], t["id"], "done")         # Dana took it all
        self.assertEqual(self.coins("dana"), 20)
        r = self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["dana", "avi"]})
        self.assertEqual((self.coins("dana"), self.coins("avi")), (10, 10))
        self.assertEqual(r["done_with"], ["dana", "avi"])
        self.assertIn(t["id"], [x["id"] for x in self.store.snapshot(self.p["avi"])["tasks"]])  # Avi sees it now
        self.store.act(self.p["avi"], t["id"], "done", None, {"as": ["dana"]})   # back to Dana alone
        self.assertEqual((self.coins("dana"), self.coins("avi")), (20, 0))
        self.assertNotIn("done_with", self.get(t["id"], "dana"))

    def test_three_people(self):
        t = self.one(who="yoni", effort=4)
        self.store.act(self.p["avi"], t["id"], "done", None, {"as": ["dana", "yoni", "maya"]})
        self.assertEqual([self.coins(i) for i in ("dana", "yoni", "maya", "avi")], [7, 7, 6, 0])
        self.assertEqual(self.get(t["id"])["ticked_by"], "avi")

    def test_reopen_takes_back_from_all(self):
        t = self.one()
        self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["dana", "avi"]})
        r = self.store.act(self.p["dana"], t["id"], "reopen")
        self.assertEqual((self.coins("dana"), self.coins("avi")), (0, 0))
        self.assertNotIn("done_with", r)

    def test_rating_change_keeps_the_split(self):
        t = self.one()
        self.store.act(self.p["dana"], t["id"], "done", None, {"as": ["dana", "avi"]})
        self.store.set_points(self.p["avi"], t["id"], effort=6)     # 30 coins
        self.assertEqual((self.coins("dana"), self.coins("avi")), (15, 15))

    def test_child_with_a_helper(self):
        t = self.one(who="yoni", by="dana")
        self.store.act(self.p["yoni"], t["id"], "done", None, {"as": ["yoni", "maya"]})
        self.assertEqual((self.coins("yoni"), self.coins("maya")), (10, 10))

    def test_child_cannot_split_without_being_in_it(self):
        t = self.one(who="yoni", by="dana")
        with self.assertRaises(TaskError) as e:
            self.store.act(self.p["yoni"], t["id"], "done", None, {"as": ["maya", "dana"]})
        self.assertEqual(e.exception.status, 403)

    def test_not_for_each_of_them_tasks(self):
        t = self.shared("all")
        with self.assertRaises(TaskError):
            self.store.act(self.p["avi"], t["id"], "done", None, {"as": ["yoni", "maya"]})

    def test_unknown_person(self):
        t = self.one()
        with self.assertRaises(TaskError):
            self.store.act(self.p["avi"], t["id"], "done", None, {"as": ["dana", "nobody"]})


if __name__ == "__main__":
    unittest.main()
