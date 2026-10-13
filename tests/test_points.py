"""The points game: effort rating, the coin ledger, the task hooks, the leaderboard and its API."""

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from worker import effort
from worker.family import Family, Person
from worker.points import PointsConfig, PointsStore
from worker.taskstore import TaskError, TaskStore, done_time

FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True, "aliases": ["Avi"]},
    "dana": {"name": "דנה", "role": "parent", "aliases": ["Dana"]},
    "yoni": {"name": "יוני", "role": "child", "aliases": ["Yoni"], "age": 12},
    "maya": {"name": "מאיה", "role": "child", "aliases": ["Maya"], "age": 8},
}
TZ = ZoneInfo("Asia/Jerusalem")
CALIBRATION_WORDS = ("toilet", "dog", "laundry", "dishwasher", "bed", "grandma", "calendar", "שירותים", "כלב")


def iso(y, m, d, h=12, mi=0):
    """A local Jerusalem time as the UTC string the ledger stores."""
    return datetime(y, m, d, h, mi, tzinfo=TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rating(effort_=4, key="hang-laundry", rated_by="ai", **extra):
    return {"effort": effort_, "minutes": 20, "category": "laundry", "chore_key": key, "reason": "test",
            "rated_by": rated_by, "no_coins": False, **extra}


class EffortRating(unittest.TestCase):
    def test_parse_clamps_and_cleans(self):
        r = effort.parse('Sure: {"effort": 15, "minutes": "20", "category": "Kitchen", '
                         '"chore_key": "Load The Dishwasher!", "reason": "ok"}', "x")
        self.assertEqual((r["effort"], r["minutes"], r["category"], r["chore_key"], r["rated_by"]),
                         (10, 20, "kitchen", "load-the-dishwasher", "ai"))
        r = effort.parse('{"effort": 0.4, "category": "gardening", "chore_key": "???"}', "לתלות כביסה")
        self.assertEqual((r["effort"], r["category"]), (1, "other"))
        self.assertTrue(r["chore_key"].startswith("t-"))                  # stable key from the wording
        self.assertEqual(r["chore_key"], effort.fallback_key("לתלות כביסה!"))
        self.assertIsNone(effort.parse('{"minutes": 5}'))
        self.assertIsNone(effort.parse("not json"))

    def test_rules_need_no_model(self):
        parent, child = Person("a", "A", "parent"), Person("c", "C", "child")
        self.assertTrue(effort.rule_rating("WhatsApp → סבתא", "message", parent)["no_coins"])
        self.assertTrue(effort.rule_rating("לשלוח את המייל: ביטוח", "task", parent)["no_coins"])
        self.assertTrue(effort.rule_rating("Send the email: lease", "task", parent)["no_coins"])
        wd = effort.rule_rating("יום עבודה", "task", parent)
        self.assertTrue(wd["work_day"] and not wd["no_coins"])
        self.assertIsNone(effort.rule_rating("יום עבודה", "task", child))      # work days are for grown-ups
        self.assertIsNone(effort.rule_rating("לתלות כביסה", "task", parent))

    def test_prompt_knows_who_and_never_names_the_test_chores(self):
        kid = effort.build_prompt("לתלות כביסה", "", Person("c", "C", "child", age=9), ["hang-laundry", "wash-car"])
        self.assertIn("for a grown-up", kid)             # the model rates the adult version; the code adds the child's bump
        self.assertIn("hang-laundry, wash-car", kid)
        adult = effort.build_prompt("לשלם חשבון", "אונליין", Person("a", "A", "parent"))
        self.assertIn("Notes: אונליין", adult)
        self.assertIn("insurance, repairs, paperwork", adult)
        for word in CALIBRATION_WORDS:                       # the model must judge, not copy
            self.assertNotIn(word, effort.PROMPT.lower())
        self.assertLess(len(effort.PROMPT), 2200)

    def test_a_child_gets_the_adult_rating_plus_a_bump(self):
        reply = '{"effort": 3, "minutes": 15, "category": "laundry", "chore_key": "hang-laundry", "reason": "ok"}'
        with mock.patch.object(effort, "chat", return_value=reply):
            for age, expect in ((0, 4), (9, 5), (12, 4)):
                r = effort.rate("http://x", "m", "לתלות כביסה", "", Person("c", "C", "child", age=age), [])
                self.assertEqual(r["effort"], expect, age)
            self.assertEqual(effort.rate("http://x", "m", "לתלות כביסה", "", Person("a", "A", "parent"), [])["effort"], 3)
        with mock.patch.object(effort, "chat", return_value=reply.replace('"effort": 3', '"effort": 9')):
            self.assertEqual(effort.rate("http://x", "m", "x", "", Person("c", "C", "child", age=8), [])["effort"], 10)

    def test_a_parents_earlier_correction_is_the_starting_point(self):
        reply = '{"effort": 4, "minutes": 20, "category": "laundry", "chore_key": "hang-laundry", "reason": "ok"}'
        with mock.patch.object(effort, "chat", return_value=reply) as chat:
            who = Person("c", "C", "child", age=9)
            r = effort.rate("http://x", "m", "לתלות כביסה", "", who, [], lambda key: None)
            self.assertEqual(r["effort"], 6)    # 4 from the model + 2 for a child under 10
            r = effort.rate("http://x", "m", "לתלות כביסה", "", who, [], lambda key: 6 if key == "hang-laundry" else None)
            self.assertEqual((r["effort"], r["rated_by"]), (6, "ai"))
            self.assertIn("parent", r["reason"])
            self.assertEqual(chat.call_count, 2)
        with mock.patch.object(effort, "chat", side_effect=AssertionError("no model for a rule")):
            self.assertTrue(effort.rate("http://x", "m", "לשלוח את המייל: x", "", who)["no_coins"])

    def test_model_trouble_raises(self):
        with mock.patch.object(effort, "chat", return_value="I can't"):
            with self.assertRaises(effort.RateError):
                effort.rate("http://x", "m", "משהו", "", Person("a", "A", "parent"))

    def test_lessons_fall_back_to_length_when_the_ai_is_away(self):
        with mock.patch.object(effort, "chat", side_effect=effort.RateError("down")):
            self.assertEqual(effort.rate_lesson("u", "m", "t", "קצר מאוד"), (1, "default"))
            self.assertEqual(effort.rate_lesson("u", "m", "t", "למדתי שמשוואה ריבועית יכולה להיות עם שני פתרונות"), (3, "default"))
        with mock.patch.object(effort, "chat", return_value='{"effort": 9}'):
            self.assertEqual(effort.rate_lesson("u", "m", "t", "x" * 40), (5, "ai"))
        with mock.patch.object(effort, "chat", return_value="garbage"):
            self.assertEqual(effort.rate_lesson("u", "m", "t", "x" * 40)[1], "default")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.points = PointsStore(self.tmp / "data" / "points.json", self.fam, "Asia/Jerusalem",
                                  PointsConfig(work_day_coins=30))
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, None, self.points)
        self.p = self.fam.people

    def task_for(self, who="yoni", title="לתלות כביסה", by="dana", points=None, **kw):
        t = self.store.add(self.p[by], title, self.p[who], **kw)
        if points is not None:
            self.assertTrue(self.store.rate(t["id"], points))
        return t

    def lines(self, active_only=True):
        ls = self.points._read()["lines"]
        return [x for x in ls if not x.get("reversed")] if active_only else ls


class Coins(Base):
    def test_done_pays_the_assignee_once(self):
        t = self.task_for(points=rating(6))
        r = self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual((r["award"]["coins"], r["award"]["new"], r["award"]["week_total"]), (30, True, 30))
        self.assertEqual(r["award"]["breakdown"]["E"], 6)
        again = self.store.act(self.p["yoni"], t["id"], "done")                  # a retried tick
        self.assertFalse(again["award"]["new"])
        self.assertEqual([(x["person"], x["coins"]) for x in self.lines()], [("yoni", 30)])
        # a parent ticking a child's task: the child still gets the coins
        t2 = self.task_for(points=rating(2, "make-bed"))
        self.store.act(self.p["dana"], t2["id"], "done")
        self.assertEqual(sorted(x["person"] for x in self.lines()), ["yoni", "yoni"])

    def test_reopen_delete_and_reassign_take_the_coins_back(self):
        a, b, c = (self.task_for(points=rating(4, f"k{i}")) for i in range(3))
        for t in (a, b, c):
            self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual(sum(x["coins"] for x in self.lines()), 60)
        self.store.act(self.p["yoni"], a["id"], "reopen")
        self.store.act(self.p["dana"], b["id"], "delete")
        self.store.act(self.p["dana"], c["id"], "edit", fields={"assignee": "maya"})
        self.assertEqual(self.lines(), [])
        self.assertEqual(len(self.lines(active_only=False)), 3)                  # kept, marked reversed
        self.assertEqual(self.lines(False)[0]["reversed_why"], "reopened")
        r = self.store.act(self.p["yoni"], a["id"], "done")                      # done again: paid again
        self.assertEqual(r["award"]["coins"], 20)

    def test_unrated_is_paid_at_the_default_and_a_parent_can_fix_it(self):
        t = self.task_for(points=None)
        self.assertEqual(self.store.snapshot(self.p["yoni"])["tasks"][0]["coins"], 0)       # not rated yet
        r = self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual(r["award"]["coins"], 15)
        self.assertEqual(r["points"]["rated_by"], "default")
        fixed = self.store.set_points(self.p["dana"], t["id"], effort=8)
        self.assertEqual((fixed["coins"], fixed["paid"]), (40, True))
        self.assertEqual([x["coins"] for x in self.lines()], [40])                           # old line reversed
        self.assertEqual(len(self.lines(False)), 2)

    def test_no_coin_tasks(self):
        m = self.store.add(self.p["avi"], "WhatsApp → סבתא", self.p["avi"], kind="message", message="היי")
        e = self.store.add(self.p["avi"], "לשלוח את המייל: ביטוח", self.p["avi"])
        for t in (m, e):
            self.assertTrue(t["points"]["no_coins"])
            self.assertIsNone(self.store.act(self.p["avi"], t["id"], "done").get("award"))
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.store.unrated(), [])                                          # nothing for the model to rate
        with self.assertRaises(TaskError) as cm:
            self.store.set_points(self.p["avi"], m["id"], effort=5)
        self.assertEqual(cm.exception.status, 409)

    def test_snapshot_shows_coins(self):
        t = self.task_for(points=rating(5))
        shown = self.store.snapshot(self.p["yoni"])["tasks"][0]
        self.assertEqual(shown["coins"], 25)
        self.assertNotIn("paid", shown)
        self.store.act(self.p["yoni"], t["id"], "done")
        shown = self.store.snapshot(self.p["dana"])["tasks"][0]
        self.assertEqual((shown["coins"], shown["paid"]), (25, True))

    def test_only_parents_set_what_a_task_is_worth_and_it_is_remembered(self):
        t = self.task_for(points=rating(4))
        with self.assertRaises(TaskError) as cm:
            self.store.set_points(self.p["yoni"], t["id"], effort=10)
        self.assertEqual(cm.exception.status, 403)
        for bad in (0, 11, "x"):
            with self.assertRaises(TaskError) as cm:
                self.store.set_points(self.p["dana"], t["id"], effort=bad)
            self.assertEqual(cm.exception.status, 400)
        r = self.store.set_points(self.p["dana"], t["id"], effort=7)
        self.assertEqual((r["points"]["effort"], r["points"]["rated_by"], r["coins"]), (7, "parent", 35))
        self.assertEqual(self.points.parent_effort("hang-laundry"), 7)
        self.assertIn("hang-laundry", self.points.known_keys())
        self.store.set_points(self.p["dana"], t["id"], no_coins=True)
        self.assertEqual(self.store.snapshot(self.p["yoni"])["tasks"][0]["coins"], 0)
        self.assertEqual(self.points.parent_effort("hang-laundry"), 7)                      # no_coins is per task
        with self.assertRaises(TaskError):                                                  # maya can't see yoni's task
            self.store.set_points(self.p["avi"], "nope", effort=3)

    def test_the_model_only_rates_what_nobody_rated(self):
        a = self.task_for(title="א")
        b = self.task_for(title="ב", points=rating(9, "k"))
        self.assertEqual([t["id"] for t in self.store.unrated()], [a["id"]])
        self.assertFalse(self.store.rate(b["id"], rating(1)))                                # a parent's / earlier rating stays
        self.assertTrue(self.store.rate(a["id"], rating(2)))
        self.assertEqual(self.store.unrated(), [])

    def test_reassigning_an_open_task_rates_it_again_for_the_new_person(self):
        ai = self.task_for(points=rating(4, rated_by="ai"))
        by_parent = self.task_for(title="ב", points=rating(7, "x", rated_by="parent"))
        for t in (ai, by_parent):
            self.store.act(self.p["dana"], t["id"], "edit", fields={"assignee": "maya"})
        ids = [t["id"] for t in self.store.unrated()]
        self.assertEqual(ids, [ai["id"]])

    def test_an_offline_tick_is_paid_at_the_time_it_was_made(self):
        t = self.task_for(points=rating(2, "a"))
        two_days = time.time() - 2 * 86400
        r = self.store.act(self.p["yoni"], t["id"], "done", fields={"at": two_days})
        expect = datetime.fromtimestamp(two_days, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual((r["done_at"], self.lines()[0]["at"]), (expect, expect))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue(done_time(time.time() + 86400).startswith(now))                      # the future: now
        self.assertTrue(done_time(time.time() - 40 * 86400).startswith(now))                 # too old: now
        self.assertTrue(done_time(None).startswith(now))
        self.assertTrue(done_time("junk").startswith(now))

    def test_a_work_day_is_a_fixed_base_once_a_day(self):
        t = self.store.add(self.p["avi"], "יום עבודה", self.p["avi"])
        self.assertEqual(self.store.snapshot(self.p["avi"])["tasks"][0]["coins"], 30)
        r = self.store.act(self.p["avi"], t["id"], "done")
        self.assertEqual((r["award"]["coins"], r["award"]["breakdown"]), (30, {"fixed": 30}))
        self.assertIsNone(self.points.pay_work_day("avi"))                                  # today's is logged
        self.assertEqual(self.points.pay_work_day("dana")["coins"], 30)
        self.assertEqual({x["kind"] for x in self.lines()}, {"work_day"})
        t2 = self.store.add(self.p["avi"], "work day", self.p["avi"])
        self.assertIsNone(self.store.act(self.p["avi"], t2["id"], "done").get("award"))     # the same day twice

    def test_lessons_pay_for_the_note_and_parents_see_it(self):
        r = self.store.add_lesson(self.p["yoni"], "מתמטיקה", "למדתי שמשוואה ריבועית יש לה שני פתרונות", 3)
        self.assertEqual((r["coins"], r["status"], r["kind"]), (15, "done", "lesson"))
        self.assertEqual([t["id"] for t in self.store.snapshot(self.p["dana"])["tasks"]], [r["id"]])
        self.assertEqual(self.store.snapshot(self.p["maya"])["tasks"], [])
        board = self.points.board(self.p["dana"])
        self.assertEqual([(x["name"], x["note"][:4]) for x in board["lessons"]], [("יוני", "למדת")])
        self.assertEqual(self.points.board(self.p["maya"])["lessons"], [])
        for _ in range(2):
            self.store.add_lesson(self.p["yoni"], "", "עוד משהו שלמדתי היום בשיעור", 2)
        with self.assertRaises(TaskError) as cm:
            self.store.add_lesson(self.p["yoni"], "", "הרביעי ביום", 2)
        self.assertEqual(cm.exception.status, 429)


class Board(Base):
    def pay(self, who, coins_effort, at, key="k", by="dana", title="משימה", tid=None):
        task = {"id": tid or f"{who}{at}{key}{coins_effort}", "assignee": who, "created_by": by, "title": title,
                "points": rating(coins_effort, key)}
        return self.points.pay(task, at)

    def test_week_runs_sunday_to_saturday(self):
        wb = lambda y, m, d: tuple(x.isoformat() for x in self.points.week_bounds(datetime(y, m, d, 12, tzinfo=TZ)))  # noqa: E731
        self.assertEqual(wb(2026, 10, 14), ("2026-10-11", "2026-10-17"))      # Wednesday
        self.assertEqual(wb(2026, 10, 11), ("2026-10-11", "2026-10-17"))      # Sunday starts it
        self.assertEqual(wb(2026, 10, 17), ("2026-10-11", "2026-10-17"))      # Saturday ends it
        self.points.cfg.week_start = "monday"
        self.assertEqual(wb(2026, 10, 14), ("2026-10-12", "2026-10-18"))

    def test_this_week_and_all_time(self):
        self.pay("yoni", 4, iso(2026, 10, 12))                               # 20, this week
        self.pay("yoni", 2, iso(2026, 10, 13), key="b")                      # 10, this week
        self.pay("yoni", 10, iso(2026, 10, 7), key="c")                      # 50, last week
        self.pay("maya", 3, iso(2026, 10, 14), key="d")                      # 15
        now = datetime(2026, 10, 14, 20, tzinfo=TZ)
        b = self.points.board(self.p["dana"], now)
        rows = {x["id"]: x for x in b["people"]}
        self.assertEqual((rows["yoni"]["week"], rows["yoni"]["all_time"], rows["yoni"]["tasks_week"]), (30, 80, 2))
        self.assertEqual((rows["maya"]["week"], rows["avi"]["week"]), (15, 0))
        self.assertEqual([x["id"] for x in b["people"]][:2], ["yoni", "maya"])               # by this week
        self.assertEqual(b["week"], {"start": "2026-10-11", "end": "2026-10-17"})
        self.assertEqual(rows["yoni"]["best"]["coins"], 20)
        self.assertEqual(b["config"], {"work_day_coins": 30, "announce": "sat 20:00"})

    def test_streak_counts_days_with_a_parent_given_task(self):
        for d in (11, 12, 13):
            self.pay("yoni", 3, iso(2026, 10, d), key=f"s{d}")
        self.pay("yoni", 3, iso(2026, 10, 9), key="old")                      # a gap: not part of it
        self.pay("maya", 3, iso(2026, 10, 13), key="own", by="maya")          # her own task: no streak
        rows = {x["id"]: x for x in self.points.board(self.p["dana"], datetime(2026, 10, 13, 20, tzinfo=TZ))["people"]}
        self.assertEqual((rows["yoni"]["streak"], rows["maya"]["streak"]), (3, 0))
        rows = {x["id"]: x for x in self.points.board(self.p["dana"], datetime(2026, 10, 14, 9, tzinfo=TZ))["people"]}
        self.assertEqual(rows["yoni"]["streak"], 3)                          # yesterday still counts
        rows = {x["id"]: x for x in self.points.board(self.p["dana"], datetime(2026, 10, 15, 9, tzinfo=TZ))["people"]}
        self.assertEqual(rows["yoni"]["streak"], 0)

    def test_reversed_lines_count_for_nothing(self):
        self.pay("yoni", 4, iso(2026, 10, 12), tid="t1")
        self.points.reverse("t1", "reopened")
        rows = {x["id"]: x for x in self.points.board(self.p["dana"], datetime(2026, 10, 14, tzinfo=TZ))["people"]}
        self.assertEqual((rows["yoni"]["week"], rows["yoni"]["all_time"]), (0, 0))

    def test_ledgers_hide_titles_you_may_not_see(self):
        self.pay("avi", 5, iso(2026, 10, 12), title="סוד של אבי", by="avi", tid="p1")        # his own, private
        self.pay("yoni", 5, iso(2026, 10, 12), title="של יוני", tid="y1")                    # a child's
        self.pay("avi", 3, iso(2026, 10, 13), title="מדענית", by="dana", tid="p2")           # dana gave it to avi
        now = datetime(2026, 10, 14, tzinfo=TZ)
        titles = lambda viewer, who: {x["task_id"]: x["title"] for x in self.points.board(viewer, now)["ledgers"][who]}  # noqa: E731
        self.assertEqual(titles(self.p["dana"], "avi"), {"p1": None, "p2": "מדענית"})
        self.assertEqual(titles(self.p["avi"], "avi"), {"p1": "סוד של אבי", "p2": "מדענית"})
        self.assertEqual(titles(self.p["dana"], "yoni"), {"y1": "של יוני"})                  # parents see the kids'
        self.assertEqual(titles(self.p["maya"], "yoni"), {"y1": None})                        # siblings don't
        self.assertEqual(titles(self.p["yoni"], "yoni"), {"y1": "של יוני"})

    def test_saturday_winner_and_most_improved(self):
        for wk in range(3):                                                                  # three earlier weeks
            day = datetime(2026, 9, 20, tzinfo=TZ) + timedelta(days=7 * wk)
            self.pay("yoni", 10, iso(day.year, day.month, day.day), key=f"y{wk}")            # 50 a week
            self.pay("maya", 4 + wk, iso(day.year, day.month, day.day), key=f"m{wk}")        # 20, 25, 30 a week
        self.pay("yoni", 10, iso(2026, 10, 13), key="now1")                                  # 50: no better than before
        self.pay("maya", 10, iso(2026, 10, 13), key="now2")                                  # 50: double her usual
        s = self.points.summary(now=datetime(2026, 10, 17, 20, tzinfo=TZ))
        self.assertEqual(sorted(s["winners"]), ["maya", "yoni"])                             # a tie is shared
        self.assertEqual(s["top"], 50)
        self.assertEqual(s["most_improved"]["id"], "maya")
        self.assertEqual((s["most_improved"]["pct"], s["most_improved"]["before"]), (100, 25))
        self.assertEqual((s["week_start"], s["week_end"]), ("2026-10-11", "2026-10-17"))

    def test_nobody_wins_a_week_with_no_coins(self):
        s = self.points.summary(now=datetime(2026, 10, 17, 20, tzinfo=TZ))
        self.assertEqual((s["winners"], s["top"], s["most_improved"]), ([], 0, None))
        self.pay("yoni", 3, iso(2026, 10, 12))                                               # 15 < 20: too little to call it improvement
        self.assertIsNone(self.points.summary(now=datetime(2026, 10, 17, 20, tzinfo=TZ))["most_improved"])

    def test_config_from_raw(self):
        c = PointsConfig.from_raw({"work_day_coins": "45", "week_start": "Monday", "daily_cap": "x", "announce": "fri 19:00"})
        self.assertEqual((c.work_day_coins, c.week_start, c.daily_cap, c.announce), (45, "monday", 150, "fri 19:00"))
        self.assertEqual(PointsConfig.from_raw(None).work_day_coins, 30)


class PointsApi(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.server, cls.TestClient = server, TestClient

    def setUp(self):
        super().setUp()
        self.server.FAMILY, self.server.POINTS, self.server.TASKS = self.fam, self.points, self.store
        self.server.TOKEN = "admin-token-123"
        self.c = self.TestClient(self.server.app)
        self.h = lambda pid: {"Authorization": "Bearer " + self.fam.token_for(pid), "X-Device-Id": "t"}

    def test_done_returns_the_award_and_the_board_shows_it(self):
        t = self.task_for(points=rating(6))
        r = self.c.post(f"/v1/tasks/{t['id']}/done", headers=self.h("yoni"), json={"at": time.time() - 60})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["award"]["coins"], r.json()["award"]["week_total"]), (30, 30))
        b = self.c.get("/v1/points", headers=self.h("dana")).json()
        self.assertEqual({x["id"] for x in b["people"]}, {"avi", "dana", "yoni", "maya"})
        self.assertEqual(b["people"][0]["id"], "yoni")
        self.assertEqual(b["ledgers"]["yoni"][0]["coins"], 30)
        self.assertEqual(self.c.get("/v1/points").status_code, 401)
        tasks = self.c.get("/v1/tasks", headers=self.h("yoni")).json()["tasks"]
        self.assertEqual((tasks[0]["coins"], tasks[0]["paid"]), (30, True))

    def test_parent_slider_endpoint(self):
        t = self.task_for(points=rating(4))
        url = f"/v1/tasks/{t['id']}/points"
        self.assertEqual(self.c.post(url, headers=self.h("yoni"), json={"effort": 10}).status_code, 403)
        self.assertEqual(self.c.post(url, headers=self.h("dana"), json={"effort": 12}).status_code, 400)
        r = self.c.post(url, headers=self.h("dana"), json={"effort": 9})
        self.assertEqual((r.status_code, r.json()["coins"]), (200, 45))
        r = self.c.post(url, headers=self.h("dana"), json={"no_coins": True})
        self.assertEqual(r.json()["coins"], 0)
        self.assertEqual(self.c.post(f"/v1/tasks/nope/points", headers=self.h("dana"), json={"effort": 3}).status_code, 404)

    def test_lessons_endpoint(self):
        with mock.patch.object(effort, "chat", side_effect=effort.RateError("down")):
            r = self.c.post("/v1/lessons", headers=self.h("yoni"),
                            json={"title": "היסטוריה", "learned": "למדתי על מהפכת התעשייה ואיך היא שינתה את העבודה"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["coins"], r.json()["award"]["new"], r.json()["points"]["rated_by"]), (15, True, "default"))
        with mock.patch.object(effort, "chat", return_value='{"effort": 5}'):
            r = self.c.post("/v1/lessons", headers=self.h("maya"), json={"learned": "x" * 30})
        self.assertEqual(r.json()["coins"], 25)
        self.assertEqual(self.c.post("/v1/lessons", headers=self.h("dana"), json={"learned": "x" * 30}).status_code, 403)
        self.assertEqual(self.c.post("/v1/lessons", headers=self.h("yoni"), json={"learned": "קצר"}).status_code, 400)
        b = self.c.get("/v1/points", headers=self.h("dana")).json()
        self.assertEqual(len(b["lessons"]), 2)

    def test_work_day_button(self):
        self.assertEqual(self.c.post("/v1/points/work-day", headers=self.h("yoni")).status_code, 403)
        r = self.c.post("/v1/points/work-day", headers=self.h("avi"))
        self.assertEqual((r.status_code, r.json()["award"]["coins"]), (200, 30))
        self.assertEqual(self.c.post("/v1/points/work-day", headers=self.h("avi")).status_code, 409)


if __name__ == "__main__":
    unittest.main()
