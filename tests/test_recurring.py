"""Recurring tasks (משימות רב פעמיות): rules, occurrences on their day, quiet misses, turns, and Jar ideas."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker import recurring as R
from worker.family import Family
from worker.points import PointsConfig, PointsStore
from worker.taskstore import TaskError, TaskStore, owners

TZ = ZoneInfo("Asia/Jerusalem")
FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True},
    "dana": {"name": "דנה", "role": "parent"},
    "yoni": {"name": "יוני", "role": "child"},
    "maya": {"name": "מאיה", "role": "child"},
}
RATED = {"effort": 3, "minutes": 5, "category": "cleaning", "chore_key": "take-out-trash", "reason": "t",
         "rated_by": "ai", "no_coins": False}


def at(y, m, d, hh=9, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


class Rules(unittest.TestCase):
    def test_parse_and_text(self):
        for raw, text in [("daily", "daily"), ("weekdays", "weekdays"), ("weekly:wed,sun", "weekly:sun,wed"),
                          ("weekly:ראשון,רביעי", "weekly:sun,wed"), ("every:3d", "every:3d"), ("every:1d", "daily"),
                          ("every:2w", "every:2w"), ("monthly:15", "monthly:15"), ("biweekly", "every:2w")]:
            self.assertEqual(R.parse(raw).text(), text, raw)
        for bad in ("", "sometimes", "weekly:xyz", "every:0d", "monthly:40"):
            with self.assertRaises(R.RuleError):
                R.parse(bad)

    def test_next_days(self):
        wk = R.parse("weekly:sun,wed")
        self.assertEqual(R.after(wk, date(2026, 10, 25)), date(2026, 10, 28))     # Sun -> Wed
        self.assertEqual(R.after(wk, date(2026, 10, 28)), date(2026, 11, 1))      # Wed -> Sun
        self.assertEqual(R.after(R.parse("weekdays"), date(2026, 10, 22)), date(2026, 10, 25))  # Thu -> Sun
        m = R.parse("monthly:31")
        self.assertEqual(R.after(m, date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(R.after(m, date(2026, 2, 28)), date(2026, 3, 31))
        self.assertEqual(R.after(R.parse("every:2w"), date(2026, 10, 21)), date(2026, 11, 4))

    def test_first_day(self):
        daily = R.parse("daily")
        self.assertEqual(R.first(daily, at(2026, 10, 21, 19), "20:00"), date(2026, 10, 21))
        self.assertEqual(R.first(daily, at(2026, 10, 21, 21), "20:00"), date(2026, 10, 22))   # 20:00 already passed
        self.assertEqual(R.first(R.parse("weekly:sun"), at(2026, 10, 21)), date(2026, 10, 25))
        self.assertEqual(R.settle(R.parse("weekly"), date(2026, 10, 21)).text(), "weekly:wed")

    def test_labels(self):
        self.assertEqual(R.label(R.parse("weekly:sun,wed"), "20:00"), "כל ראשון ורביעי ב-20:00")
        self.assertEqual(R.label(R.parse("every:2d")), "כל יומיים")
        self.assertEqual(R.label(R.parse("daily"), "", "en"), "every day")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "t", self.tmp / "data")
        self.points = PointsStore(self.tmp / "data" / "points.json", self.fam, "Asia/Jerusalem", PointsConfig())
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, self.tmp / "Tasks.md", self.points)
        self.p = self.fam.people

    def tasks(self, viewer="avi", series_id=None):
        out = self.store.snapshot(self.p[viewer])["tasks"]
        return [t for t in out if series_id is None or t.get("series_id") == series_id]

    def all_tasks(self):
        return self.store._read()["tasks"]

    def coins(self, pid):
        return sum(ln["coins"] for ln in self.points._read()["lines"] if ln["person"] == pid and not ln["reversed"])


class Series(Base):
    def trash(self, **kw):
        kw.setdefault("now", at(2026, 10, 21, 10))                  # a Wednesday
        return self.store.add_series(self.p["dana"], "להוציא את הזבל", [self.p["yoni"]], "weekly:sun,wed",
                                     "20:00", **kw)

    def test_first_occurrence_now_next_on_its_day(self):
        t = self.trash()
        sid = t["series_id"]
        self.assertEqual((t["due"], t["status"], t["assignee"]), ("2026-10-21T20:00", "open", "yoni"))
        self.assertEqual(t["repeat"], "כל ראשון ורביעי ב-20:00")
        self.assertEqual(t["series"]["next_due"], "2026-10-25")
        self.assertEqual(self.store.roll(at(2026, 10, 24, 23)), 0)       # Saturday: nothing yet
        self.assertEqual(self.store.roll(at(2026, 10, 25, 0, 5)), 1)     # Sunday
        live = self.tasks("yoni", sid)
        self.assertEqual([x["due"] for x in live], ["2026-10-25T20:00"])  # Wednesday's (not done) quietly gone
        self.assertEqual([x["status"] for x in self.all_tasks()], ["missed", "open"])
        self.assertEqual(self.store.roll(at(2026, 10, 25, 12)), 0)       # twice the same day: nothing

    def test_done_pays_and_next_comes(self):
        t = self.trash()
        self.store.rate(t["id"], dict(RATED))
        self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual(self.coins("yoni"), 15)
        self.store.roll(at(2026, 10, 25, 7))
        nxt = self.tasks("yoni", t["series_id"])[-1]
        self.assertEqual((nxt["status"], nxt["points"]["effort"]), ("open", 3))   # rated once, for every time
        self.store.act(self.p["yoni"], nxt["id"], "done")
        self.assertEqual(self.coins("yoni"), 30)

    def test_pc_off_for_days_makes_only_the_latest(self):
        t = self.trash()
        self.assertEqual(self.store.roll(at(2026, 11, 5, 8)), 1)        # Thursday after two missed ones
        live = self.tasks("yoni", t["series_id"])
        self.assertEqual([x["due"] for x in live], ["2026-11-04T20:00"])
        self.assertEqual(self.store._read()["series"][0]["next_due"], "2026-11-08")

    def test_turns(self):
        t = self.store.add_series(self.p["dana"], "לפרוק מדיח", [self.p["yoni"], self.p["maya"]], "daily",
                                  rotate=True, now=at(2026, 10, 21))
        self.assertEqual((t["assignee"], owners(t)), ("yoni", ["yoni"]))
        self.assertEqual(t["series"]["next_turn"], "maya")
        self.store.roll(at(2026, 10, 22))
        self.store.roll(at(2026, 10, 23))
        who = [x["assignee"] for x in self.all_tasks()]
        self.assertEqual(who, ["yoni", "maya", "yoni"])

    def test_together_not_turns(self):
        t = self.store.add_series(self.p["dana"], "לסדר חדר", [self.p["yoni"], self.p["maya"]], "weekly:fri",
                                  mode="all", now=at(2026, 10, 21))
        self.assertEqual((owners(t), t["mode"], t["due"]), (["yoni", "maya"], "all", "2026-10-23"))

    def test_child_asking_someone_else_waits_for_a_parent(self):
        t = self.store.add_series(self.p["yoni"], "להאכיל את הכלב", [self.p["maya"]], "daily", now=at(2026, 10, 21))
        self.assertEqual(t["status"], "requested")
        self.store.act(self.p["dana"], t["id"], "accept")
        self.store.roll(at(2026, 10, 22))
        self.assertEqual(self.all_tasks()[-1]["status"], "open")        # approved once, for the whole series
        own = self.store.add_series(self.p["yoni"], "לקרוא", [self.p["yoni"]], "daily", now=at(2026, 10, 21))
        self.assertEqual(own["status"], "open")

    def test_declined_request_ends_the_series(self):
        t = self.store.add_series(self.p["yoni"], "לשטוף כלים", [self.p["maya"]], "daily", now=at(2026, 10, 21))
        self.store.act(self.p["dana"], t["id"], "decline")
        self.assertEqual(self.store.roll(at(2026, 10, 22)), 0)
        self.assertEqual(self.store.snapshot(self.p["dana"])["series"], [])

    def test_after_done(self):
        t = self.store.add_series(self.p["dana"], "להשקות", [self.p["dana"]], "every:3d", after_done=True,
                                  now=at(2026, 10, 21))
        self.assertIsNone(t["series"]["next_due"])
        self.assertEqual(self.store.roll(at(2026, 10, 30)), 0)          # waits for the tick
        self.store.act(self.p["dana"], t["id"], "done", fields={})
        s = self.store._read()["series"][0]
        self.assertEqual(s["next_due"], R.after(R.parse("every:3d"), datetime.now(TZ).date()).isoformat())

    def test_delete_only_this_one(self):
        t = self.trash()
        self.store.act(self.p["dana"], t["id"], "delete")
        self.assertEqual(self.store.roll(at(2026, 10, 25)), 1)          # the series goes on

    def test_stop_pause_resume(self):
        t = self.trash()
        sid = t["series_id"]
        with self.assertRaises(TaskError):
            self.store.series_act(self.p["maya"], sid, "stop")          # not hers to see
        self.store.series_act(self.p["dana"], sid, "pause")
        self.assertEqual(self.store.roll(at(2026, 10, 25)), 0)
        self.store.series_act(self.p["dana"], sid, "stop")
        self.assertEqual(self.tasks("yoni", sid), [])                    # the open one went with it
        self.assertEqual(self.store.snapshot(self.p["dana"])["series"], [])

    def test_child_can_stop_own_but_not_parents(self):
        t = self.trash()
        with self.assertRaises(TaskError):
            self.store.series_act(self.p["yoni"], t["series_id"], "stop")   # Dana gave it to him
        own = self.store.add_series(self.p["yoni"], "לקרוא", [self.p["yoni"]], "daily", now=at(2026, 10, 21))
        self.store.series_act(self.p["yoni"], own["series_id"], "stop")

    def test_edit_series(self):
        t = self.trash()
        out = self.store.series_act(self.p["dana"], t["series_id"], "edit",
                                    {"title": "להוציא זבל ומחזור", "rule": "weekly:mon,thu", "time": "19:00"})
        self.assertEqual(out["label"], "כל שני וחמישי ב-19:00")
        live = self.tasks("yoni", t["series_id"])[0]
        self.assertEqual((live["title"], live["repeat"]), ("להוציא זבל ומחזור", "כל שני וחמישי ב-19:00"))

    def test_parent_rating_carries_to_next(self):
        t = self.trash()
        self.store.set_points(self.p["dana"], t["id"], effort=5)
        self.store.roll(at(2026, 10, 25))
        self.assertEqual(self.all_tasks()[-1]["points"]["effort"], 5)

    def test_markdown_and_snapshot(self):
        self.trash()
        self.assertIn("🔁 כל ראשון ורביעי ב-20:00", (self.tmp / "Tasks.md").read_text(encoding="utf-8"))
        snap = self.store.snapshot(self.p["yoni"])
        self.assertEqual(snap["series"][0]["label"], "כל ראשון ורביעי ב-20:00")
        self.assertEqual(self.store.snapshot(self.p["maya"])["series"], [])

    def test_bad_rule(self):
        with self.assertRaises(TaskError):
            self.store.add_series(self.p["dana"], "x", [self.p["yoni"]], "sometimes")


class MakeRecurring(Base):
    def test_existing_task_becomes_the_first_occurrence(self):
        t = self.store.add(self.p["dana"], "להוציא את הזבל", self.p["yoni"], "2026-10-22T20:00")
        self.store.rate(t["id"], dict(RATED))
        out = self.store.make_recurring(self.p["dana"], t["id"], "weekly:sun,thu", now=at(2026, 10, 22, 7))
        self.assertEqual((out["id"], out["due"], out["repeat"]), (t["id"], "2026-10-22T20:00", "כל ראשון וחמישי ב-20:00"))
        self.assertEqual(out["series"]["next_due"], "2026-10-25")
        self.store.roll(at(2026, 10, 25, 6))
        nxt = self.all_tasks()[-1]
        self.assertEqual((nxt["due"], nxt["assignee"], nxt["points"]["effort"]), ("2026-10-25T20:00", "yoni", 3))

    def test_no_due_starts_today_with_the_new_time(self):
        t = self.store.add(self.p["dana"], "להשקות", self.p["dana"])
        out = self.store.make_recurring(self.p["dana"], t["id"], "daily", "19:00", now=at(2026, 10, 22, 7))
        self.assertEqual(out["due"], "2026-10-22T19:00")

    def test_turns_from_a_shared_task(self):
        t = self.store.add(self.p["dana"], "לפרוק מדיח", [self.p["yoni"], self.p["maya"]], "2026-10-22")
        out = self.store.make_recurring(self.p["dana"], t["id"], "daily", rotate=True, now=at(2026, 10, 22))
        self.assertEqual((out["assignee"], owners(out)), ("yoni", ["yoni"]))
        self.store.roll(at(2026, 10, 23))
        self.assertEqual(self.all_tasks()[-1]["assignee"], "maya")

    def test_rules(self):
        t = self.store.add(self.p["dana"], "x", self.p["yoni"])
        with self.assertRaises(TaskError):
            self.store.make_recurring(self.p["yoni"], t["id"], "daily")             # Dana's, not his to change
        with self.assertRaises(TaskError):
            self.store.make_recurring(self.p["dana"], t["id"], "sometimes")
        self.store.make_recurring(self.p["dana"], t["id"], "daily")
        with self.assertRaises(TaskError):
            self.store.make_recurring(self.p["dana"], t["id"], "daily")             # repeats already
        idea = self.store.add_idea(self.p["yoni"], "רעיון")
        with self.assertRaises(TaskError):
            self.store.make_recurring(self.p["avi"], idea["id"], "daily")


class Ideas(Base):
    def test_idea_lifecycle_and_credit(self):
        t = self.store.add_idea(self.p["yoni"], "משימות רב פעמיות", "כמו להוציא זבל כל יום")
        self.assertEqual((t["kind"], t["assignee"], t["status"]), ("idea", "avi", "requested"))
        self.assertTrue(any(x["id"] == t["id"] for x in self.tasks("maya")))        # the whole family sees it
        seen = next(x for x in self.tasks("yoni") if x["id"] == t["id"])
        self.assertEqual(seen["coins"], 20)                                         # what accepting would pay
        with self.assertRaises(TaskError):
            self.store.act(self.p["dana"], t["id"], "accept")                      # only the admin decides
        self.store.act(self.p["avi"], t["id"], "accept")
        self.assertEqual((self.coins("yoni"), self.coins("avi")), (20, 0))
        self.store.act(self.p["avi"], t["id"], "done")                              # shipped
        self.assertEqual((self.coins("yoni"), self.coins("avi")), (30, 0))
        self.assertEqual(next(x for x in self.tasks("yoni") if x["id"] == t["id"])["coins"], 30)
        self.store.act(self.p["avi"], t["id"], "reopen")
        self.assertEqual(self.coins("yoni"), 20)

    def test_weekly_cap(self):
        for i in range(4):
            t = self.store.add_idea(self.p["maya"], f"רעיון {i}")
            self.store.act(self.p["avi"], t["id"], "accept")
        self.assertEqual(self.coins("maya"), 60)
        self.assertEqual(self.store._read()["tasks"][-1]["idea_credit"], "none")

    def test_decline_with_note_and_duplicate(self):
        a = self.store.add_idea(self.p["yoni"], "לוח שנה")
        b = self.store.add_idea(self.p["maya"], "יומן משפחתי")
        self.store.act(self.p["avi"], b["id"], "decline", fields={"note": "כבר יש, ראי לוח שנה", "duplicate_of": a["id"]})
        got = next(x for x in self.store._read()["tasks"] if x["id"] == b["id"])
        self.assertEqual((got["status"], got["duplicate_of"], got["thread"][0]["text"]),
                         ("declined", a["id"], "כבר יש, ראי לוח שנה"))
        self.assertEqual(self.coins("maya"), 0)

    def test_parent_and_admin_ideas_earn_nothing(self):
        mine = self.store.add_idea(self.p["avi"], "לבנות תליון")
        self.assertEqual(mine["status"], "open")
        d = self.store.add_idea(self.p["dana"], "תזכורת לתרופות")
        self.store.act(self.p["avi"], d["id"], "accept")
        self.assertEqual(self.coins("dana"), 0)

    def test_no_coins_for_building_it(self):
        t = self.store.add_idea(self.p["yoni"], "מצב לילה")
        self.assertEqual(self.store.unrated(), [])
        self.store.act(self.p["avi"], t["id"], "accept")
        self.store.act(self.p["avi"], t["id"], "done")
        self.assertEqual(self.coins("avi"), 0)

    def test_only_suggester_edits_and_delete_takes_back(self):
        t = self.store.add_idea(self.p["yoni"], "רעיון")
        with self.assertRaises(TaskError):
            self.store.act(self.p["maya"], t["id"], "edit", fields={"title": "x"})
        self.store.act(self.p["avi"], t["id"], "accept")
        self.store.act(self.p["avi"], t["id"], "done")
        self.store.act(self.p["avi"], t["id"], "delete")
        self.assertEqual(self.coins("yoni"), 0)


class VoiceTools(Base):
    def notes(self, who):
        from worker.tools import MemoContext, Notes
        return Notes(self.tmp / who, TZ, MemoContext("abcdef0123456789", at(2026, 10, 21, 13)), store=self.store,
                     family=self.fam, speaker=self.p[who])

    def test_add_task_with_repeat(self):
        n = self.notes("dana")
        out = n.add_task("להוציא את הזבל", due_time="20:00", for_person="yoni", repeat="weekly:sun,wed")
        self.assertIn("🔁 every Sunday and Wednesday at 20:00", out)
        self.assertEqual(n.actions[0]["tool"], "add_task")
        s = self.store._read()["series"][0]
        self.assertEqual((s["owners"], s["rule"], s["time"], s["memo_id"]), (["yoni"], "weekly:sun,wed", "20:00",
                                                                             "abcdef0123456789"))

    def test_weekly_with_a_day(self):
        self.notes("dana").add_task("לשטוף את האוטו", due_date="יום שישי", repeat="weekly")
        self.assertEqual(self.store._read()["series"][0]["rule"], "weekly:fri")

    def test_turns_by_voice(self):
        out = self.notes("dana").add_task("לפרוק מדיח", for_person="yoni", also_for=["maya"], repeat="daily",
                                          take_turns=True)
        self.assertIn("taking turns", out)

    def test_days_as_said_beat_the_models_guess(self):
        n = self.notes("dana")
        n.transcript = "כל ראשון ורביעי ליבנה צריך להוציא את הזבל בשמונה בערב"
        n.add_task("להוציא את הזבל", due_time="20:00", for_person="yoni", repeat="weekly:mon,wed")
        self.assertEqual(self.store._read()["series"][0]["rule"], "weekly:sun,wed")

    def test_spoken_weekdays(self):
        from worker.tools import spoken_weekdays
        self.assertEqual(spoken_weekdays("כל ראשון ורביעי"), {6, 2})
        self.assertEqual(spoken_weekdays("בימי שני וחמישי בערב"), {0, 3})
        self.assertEqual(spoken_weekdays("כל יום שישי"), {4})
        self.assertEqual(spoken_weekdays("כל שני ימים להשקות"), set())
        self.assertEqual(spoken_weekdays("כל יום להוציא את הכלב"), set())
        self.assertEqual(spoken_weekdays("הראשון שמגיע"), set())

    def test_turns_leave_out_the_speaker_unless_named(self):
        n = self.notes("dana")
        n.add_task("לפרוק מדיח", also_for=["yoni", "maya"], repeat="daily", take_turns=True)
        self.assertEqual(self.store._read()["series"][0]["owners"], ["yoni", "maya"])
        n.add_task("לבשל", for_person="dana", also_for=["yoni"], repeat="daily", take_turns=True)
        self.assertEqual(self.store._read()["series"][1]["owners"], ["dana", "yoni"])

    def test_bad_repeat_is_explained(self):
        from worker.tools import ToolError
        with self.assertRaises(ToolError):
            self.notes("dana").add_task("x", repeat="whenever")

    def test_stop_and_find(self):
        n = self.notes("dana")
        n.add_task("להוציא את הזבל", for_person="yoni", repeat="daily")
        found = n.find_tasks("זבל")
        self.assertIn("🔁 recurring", found)
        tid = self.tasks("dana")[0]["id"]
        out = n.update_task(tid, status="stop_repeating")
        self.assertIn("stopped", out)
        self.assertEqual(self.store._read()["series"][0]["status"], "ended")

    def test_cancel_said_as_stop_ends_the_series(self):
        n = self.notes("dana")
        n.add_task("להוציא את הזבל", for_person="yoni", repeat="daily")
        tid = self.tasks("dana")[0]["id"]
        n.transcript = "תפסיק להזכיר לליבנה להוציא את הזבל כל יום, כבר לא צריך"
        n.update_task(tid, status="cancel")
        self.assertEqual(self.store._read()["series"][0]["status"], "ended")

    def test_cancel_just_today_keeps_the_series(self):
        n = self.notes("dana")
        n.add_task("להוציא את הזבל", for_person="yoni", repeat="daily")
        tid = self.tasks("dana")[0]["id"]
        n.transcript = "היום לא צריך להוציא את הזבל"
        n.update_task(tid, status="cancel")
        self.assertEqual(self.store._read()["series"][0]["status"], "active")

    def test_suggest_idea(self):
        n = self.notes("yoni")
        out = n.suggest_idea("מצב לילה", "שיהיה כהה בלילה")
        self.assertIn("💡", out)
        t = self.store._read()["tasks"][0]
        self.assertEqual((t["kind"], t["assignee"], t["notes"]), ("idea", "avi", "שיהיה כהה בלילה"))


class Api(Base):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.server, cls.TestClient = server, TestClient

    def client(self, who):
        self.server.FAMILY, self.server.TASKS = self.fam, self.store
        return self.TestClient(self.server.app), {"Authorization": "Bearer " + self.fam.token_for(who),
                                                  "X-Device-Id": "t"}

    def test_recurring_and_idea_over_the_api(self):
        c, h = self.client("dana")
        r = c.post("/v1/tasks", headers=h, json={"title": "להוציא זבל", "assignees": ["yoni", "maya"],
                                                 "repeat": {"rule": "daily", "time": "20:00", "rotate": True}})
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertTrue(body["series_id"] and body["series"]["rotate"])
        snap = c.get("/v1/tasks", headers=h).json()
        self.assertEqual(len(snap["series"]), 1)
        r = c.post(f"/v1/series/{body['series_id']}/edit", headers=h, json={"rule": "weekly:sun"})
        self.assertEqual(r.json()["label"], "כל ראשון ב-20:00")
        r = c.post(f"/v1/series/{body['series_id']}/stop", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        r = c.post("/v1/tasks", headers=h, json={"title": "x", "repeat": {"rule": "sometimes"}})
        self.assertEqual(r.status_code, 400)
        t = c.post("/v1/tasks", headers=h, json={"title": "לסדר", "assignee": "yoni"}).json()
        r = c.post(f"/v1/tasks/{t['id']}/repeat", headers=h, json={"rule": "weekly:fri", "time": "10:00"})
        self.assertEqual((r.status_code, r.json()["repeat"]), (200, "כל שישי ב-10:00"), r.text)
        c, h = self.client("yoni")
        r = c.post("/v1/tasks", headers=h, json={"kind": "idea", "title": "מצב כהה"})
        self.assertEqual((r.status_code, r.json()["kind"], r.json()["assignee"]), (201, "idea", "avi"))


if __name__ == "__main__":
    unittest.main()
