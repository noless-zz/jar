"""A parent ticks a task for whoever really did it ({"as": person}): they get the credit and the coins (#17)."""

import unittest

from worker.taskstore import TaskError
from tests.test_shared import RATED, Base


class DoneFor(Base):
    def one(self, who="yoni", by="avi"):
        t = self.store.add(self.p[by], "לסדר את החדר", [self.p[who]])
        self.store.rate(t["id"], dict(RATED))
        return t

    def test_credit_the_one_it_was_for(self):
        t = self.one()
        r = self.store.act(self.p["avi"], t["id"], "done", None, {"as": "yoni"})
        self.assertEqual((r["status"], r["done_by"], r["ticked_by"]), ("done", "yoni", "avi"))
        self.assertEqual((self.coins("yoni"), self.coins("avi")), (20, 0))

    def test_someone_not_on_it_did_it(self):
        t = self.one("yoni")
        r = self.store.act(self.p["avi"], t["id"], "done", None, {"as": "maya"})
        self.assertEqual(r["done_by"], "maya")
        self.assertEqual((self.coins("maya"), self.coins("yoni")), (20, 0))
        again = self.store.act(self.p["avi"], t["id"], "done", None, {"as": "maya"})   # a retried tick
        self.assertEqual(again["done_by"], "maya")
        self.assertEqual((self.coins("maya"), self.coins("yoni")), (20, 0))

    def test_my_own_task_done_by_someone_else(self):
        t = self.one("avi")
        self.store.act(self.p["avi"], t["id"], "done", None, {"as": "dana"})
        self.assertEqual(self.coins("avi"), 0)
        self.assertGreater(self.coins("dana"), 0)

    def test_shared_any_picks_the_right_one(self):
        t = self.shared("any")                                  # yoni first, maya second
        self.store.act(self.p["avi"], t["id"], "done", None, {"as": "maya"})
        self.assertEqual((self.coins("maya"), self.coins("yoni")), (20, 0))

    def test_shared_all_ticks_only_their_part(self):
        t = self.shared("all")
        r = self.store.act(self.p["avi"], t["id"], "done", None, {"as": "maya"})
        self.assertEqual((r["status"], list(r["done_parts"])), ("open", ["maya"]))
        self.assertEqual((self.coins("maya"), self.coins("yoni")), (20, 0))
        with self.assertRaises(TaskError) as e:                 # not on it: whose part would it be?
            self.store.act(self.p["avi"], t["id"], "done", None, {"as": "dana"})
        self.assertEqual(e.exception.status, 400)

    def test_reopen_takes_the_credit_back(self):
        t = self.one()
        self.store.act(self.p["avi"], t["id"], "done", None, {"as": "maya"})
        r = self.store.act(self.p["avi"], t["id"], "reopen")
        self.assertNotIn("ticked_by", r)
        self.assertEqual(self.coins("maya"), 0)

    def test_only_a_parent_and_a_real_person(self):
        t = self.one("yoni", by="avi")
        with self.assertRaises(TaskError) as e:
            self.store.act(self.p["yoni"], t["id"], "done", None, {"as": "maya"})
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(TaskError) as e:
            self.store.act(self.p["avi"], t["id"], "done", None, {"as": "nobody"})
        self.assertEqual(e.exception.status, 400)
        r = self.store.act(self.p["yoni"], t["id"], "done", None, {"as": "yoni"})   # "as" myself = a plain tick
        self.assertEqual(r["done_by"], "yoni")
        self.assertNotIn("ticked_by", r)


if __name__ == "__main__":
    unittest.main()
