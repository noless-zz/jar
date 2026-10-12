"""Family members, per-person tokens, the shared task list and its phone API."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.family import Family
from worker.taskstore import TaskError, TaskStore
from worker.tools import MemoContext, Notes, registry

FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True, "aliases": ["Avi", "אבא"]},
    "dana": {"name": "דנה", "role": "parent", "aliases": ["Dana", "אמא"]},
    "yoni": {"name": "יוני", "role": "child", "aliases": ["Yoni"]},
    "maya": {"name": "מאיה", "role": "child", "aliases": ["Maya"]},
}
TZ = ZoneInfo("Asia/Jerusalem")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam, self.tmp / "notes" / "Tasks.md")
        self.p = self.fam.people


class FamilyTokens(Base):
    def test_admin_keeps_server_token_others_get_their_own(self):
        self.assertEqual(self.fam.token_for("avi"), "admin-token-123")
        t = self.fam.token_for("yoni")
        self.assertNotEqual(t, "admin-token-123")
        self.assertEqual(self.fam.token_for("yoni"), t)                  # stable
        again = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        self.assertEqual(again.who(t).id, "yoni")                         # survives restart
        self.assertEqual(again.who("admin-token-123").id, "avi")
        self.assertIsNone(again.who("nope"))
        self.assertIsNone(again.who(""))

    def test_resolve_names(self):
        self.assertEqual(self.fam.resolve("יוני").id, "yoni")
        self.assertEqual(self.fam.resolve("Dana").id, "dana")
        self.assertEqual(self.fam.resolve("maya").id, "maya")
        self.assertIsNone(self.fam.resolve(""))
        self.assertIsNone(self.fam.resolve("Bob"))

    def test_single_user_without_family_section(self):
        f = Family.from_config({}, "tok", self.tmp)
        self.assertEqual(f.who("tok").id, "me")
        self.assertTrue(f.admin.admin)


class Tasks(Base):
    def test_parent_assigns_child_sees_it(self):
        t = self.store.add(self.p["avi"], "להוציא את הכלב", self.p["yoni"], "2026-10-11T17:00")
        self.assertEqual(t["status"], "open")
        self.assertEqual([x["id"] for x in self.store.snapshot(self.p["yoni"])["tasks"]], [t["id"]])
        self.assertEqual(len(self.store.snapshot(self.p["dana"])["tasks"]), 1)   # parents see kids' tasks
        self.assertEqual(len(self.store.snapshot(self.p["maya"])["tasks"]), 0)

    def test_private_self_task_and_child_request(self):
        mine = self.store.add(self.p["avi"], "water in the car")
        self.assertEqual(self.store.snapshot(self.p["dana"])["tasks"], [])      # private to Avi
        req = self.store.add(self.p["maya"], "buy a notebook", self.p["avi"])
        self.assertEqual(req["status"], "requested")
        with self.assertRaises(TaskError):
            self.store.act(self.p["maya"], req["id"], "accept")
        with self.assertRaises(TaskError):
            self.store.act(self.p["avi"], mine["id"], "accept")                 # not a request
        self.assertEqual(self.store.act(self.p["avi"], req["id"], "accept")["status"], "open")

    def test_done_snooze_reopen_delete(self):
        t = self.store.add(self.p["dana"], "call grandma", self.p["yoni"])
        s = self.store.act(self.p["yoni"], t["id"], "snooze", "2026-10-11T20:00")
        self.assertEqual(s["snoozed_until"], "2026-10-11T20:00")
        with self.assertRaises(TaskError):
            self.store.act(self.p["yoni"], t["id"], "snooze", "tomorrow")
        d = self.store.act(self.p["yoni"], t["id"], "done")
        self.assertEqual((d["status"], d["done_by"], d["snoozed_until"]), ("done", "yoni", None))
        self.assertEqual(self.store.act(self.p["yoni"], t["id"], "reopen")["status"], "open")
        with self.assertRaises(TaskError):
            self.store.act(self.p["yoni"], t["id"], "delete")                   # Dana made it
        self.store.act(self.p["dana"], t["id"], "delete")
        self.assertEqual(self.store.snapshot(self.p["dana"])["tasks"], [])
        with self.assertRaises(TaskError) as e:
            self.store.act(self.p["maya"], t["id"], "done")
        self.assertEqual(e.exception.status, 404)

    def test_markdown_is_written_and_old_file_imported(self):
        md = self.tmp / "notes" / "Tasks.md"
        md.parent.mkdir(parents=True)
        md.write_text("# Tasks\n\n- [ ] למלא מים באוטו של דנה ([[Memos/2026-10-10|memo 19:48]])\n"
                      "- [x] old done\n- [ ] grades 📅 2026-10-15 ⏰ 08:00 ([[Memos/x|memo 1]])\n", encoding="utf-8")
        self.assertEqual(self.store.import_markdown(self.p["avi"]), 2)
        tasks = self.store.snapshot(self.p["avi"])["tasks"]
        self.assertEqual([t["title"] for t in tasks], ["למלא מים באוטו של דנה", "grades"])
        self.assertEqual(tasks[1]["due"], "2026-10-15T08:00")
        self.assertTrue((self.tmp / "notes" / "Tasks (before family list).md").exists())
        self.assertEqual(self.store.import_markdown(self.p["avi"]), 0)          # only once
        self.store.add(self.p["avi"], "לקנות חלב", self.p["yoni"])
        text = md.read_text(encoding="utf-8")
        self.assertIn("## יוני", text)
        self.assertIn("- [ ] לקנות חלב — from אבי", text)


class WorkerTool(Base):
    def notes(self, speaker):
        root = self.tmp / "notes" if self.p[speaker].admin else self.tmp / "notes" / "Family" / speaker
        return Notes(root, TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 10, 19, 48, tzinfo=TZ)),
                     store=self.store, family=self.fam, speaker=self.p[speaker])

    def test_task_for_another_person(self):
        n = self.notes("avi")
        out = n.add_task("להוציא את הכלב", due_time="18:00", for_person="yoni")
        self.assertIn("for יוני", out)
        t = self.store.snapshot(self.p["yoni"])["tasks"][0]
        self.assertEqual((t["assignee"], t["created_by"], t["due"]), ("yoni", "avi", "2026-10-11T18:00"))

    def test_time_without_date_and_unknown_person(self):
        n = self.notes("avi")
        n.add_task("call", due_time="20:30")
        self.assertEqual(self.store.snapshot(self.p["avi"])["tasks"][0]["due"], "2026-10-10T20:30")
        from worker.tools import ToolError
        with self.assertRaises(ToolError):
            n.add_task("x", for_person="Bob")

    def test_no_time_is_not_called_a_reminder(self):
        out = self.notes("avi").add_task("למלא מים באוטו של דנה")
        self.assertIn("no time given", out)

    def test_child_gets_only_tasks_and_notes(self):
        n = self.notes("maya")
        self.assertEqual(set(registry(n)), {"save_note", "add_task", "find_tasks", "update_task", "draft_whatsapp",
                                             "draft_join_instructions", "search_notes"})
        self.assertIn("draft_email", registry(self.notes("avi")))
        out = n.add_task("לקנות מחברת", for_person="avi")
        self.assertIn("waits for a parent", out)


class Corrections(Base):
    def notes(self, speaker, memo="abcdef0123456789"):
        return Notes(self.tmp / "notes", TZ, MemoContext(memo, datetime(2026, 10, 10, 19, 48, tzinfo=TZ)),
                     store=self.store, family=self.fam, speaker=self.p[speaker])

    def test_voice_correction_moves_and_finishes_a_task(self):
        n = self.notes("avi")
        n.add_task("תור לרופא שיניים", due_date="2026-10-14", due_time="09:00")
        n.add_task("לקנות חלב")
        found = n.find_tasks("רופא השיניים")                 # prefix "ה" still matches
        self.assertIn("תור לרופא שיניים", found)
        self.assertNotIn("חלב", found)
        tid = self.store.find(self.p["avi"], "רופא")[0]["id"]
        out = n.update_task(tid, due_date="2026-10-15", due_time="10:30")
        self.assertIn("due 2026-10-15 10:30", out)
        self.assertEqual(self.store.find(self.p["avi"], "רופא")[0]["due"], "2026-10-15T10:30")
        n.update_task(tid, status="done")
        self.assertEqual(self.store.find(self.p["avi"], "רופא"), [])
        self.assertIn("no open task", n.find_tasks("רופא"))
        from worker.tools import ToolError
        with self.assertRaises(ToolError):
            n.update_task("nope", status="done")

    def test_reassign_by_child_needs_ok(self):
        t = self.store.add(self.p["yoni"], "לסדר חדר")
        r = self.store.act(self.p["yoni"], t["id"], "edit", fields={"assignee": "maya"})
        self.assertEqual((r["assignee"], r["status"]), ("maya", "requested"))

    def test_refile_replaces_earlier_tasks(self):
        n = self.notes("avi", memo="feedfacefeedface")
        n.add_task("old title")
        self.assertEqual(self.store.forget_memo(self.p["avi"], "feedfacefeedface"), 1)
        self.assertEqual(self.store.snapshot(self.p["avi"])["tasks"], [])


class WhatsApp(Base):
    def test_draft_goes_to_the_speakers_phone(self):
        fam = Family.from_config({**FAMILY_CFG, "dana": {**FAMILY_CFG["dana"], "phone": "+972-50-123-4567"}},
                                 "admin-token-123", self.tmp / "data", {"סבתא": "+972 52 000 0000"})
        st = TaskStore(self.tmp / "data" / "t2.json", fam)
        n = Notes(self.tmp / "notes", TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 11, 9, 0, tzinfo=TZ)),
                  store=st, family=fam, speaker=fam.people["yoni"])
        out = n.draft_whatsapp("אני אחזור בשש", to="אמא")
        self.assertIn("to דנה", out)
        t = st.snapshot(fam.people["yoni"])["tasks"][0]
        self.assertEqual((t["kind"], t["assignee"], t["to"], t["phone"], t["message"]),
                         ("message", "yoni", "דנה", "972501234567", "אני אחזור בשש"))
        self.assertEqual(t["status"], "open")                         # their own draft: no parent OK needed
        n.draft_whatsapp("מה שלומך?", to="סבתא")
        self.assertEqual(st.snapshot(fam.people["yoni"])["tasks"][1]["phone"], "972520000000")
        out = n.draft_whatsapp("hi", to="Bob")                       # unknown: no number invented
        self.assertIn("pick the chat", out)
        self.assertEqual(st.snapshot(fam.people["yoni"])["tasks"][2]["phone"], "")
        self.assertIn("draft_whatsapp", registry(n))


class DayWords(unittest.TestCase):
    def test_days_as_said(self):
        from datetime import date
        from worker.tools import _date
        mon = date(2026, 10, 12)
        for said, want in [("יום רביעי", "2026-10-14"), ("ביום רביעי", "2026-10-14"), ("ברביעי", "2026-10-14"),
                           ("Wednesday", "2026-10-14"), ("מחר", "2026-10-13"), ("tomorrow", "2026-10-13"),
                           ("מחרתיים", "2026-10-14"), ("היום", "2026-10-12"), ("יום שני", "2026-10-19"),
                           ("ביום ראשון", "2026-10-18"), ("שבת", "2026-10-17"), ("2026-11-02", "2026-11-02")]:
            self.assertEqual(str(_date(said, mon)), want, said)
        self.assertIsNone(_date("sometime", mon))
        self.assertIsNone(_date("יום רביעי"))                 # no "today" given: only ISO works

    def test_words_in_the_memo_correct_a_miscounted_date(self):
        from worker.tools import MemoContext, Notes
        tz = ZoneInfo("Asia/Jerusalem")
        n = Notes(Path(tempfile.mkdtemp()), tz, MemoContext("e" * 16, datetime(2026, 10, 12, 13, 0, tzinfo=tz)))
        n.transcript = "קבע לי תור לרופא שיניים ביום רביעי בתשע"
        self.assertEqual(str(n._day("2026-10-15")), "2026-10-14")     # model said Thursday: corrected
        self.assertEqual(str(n._day("2026-10-14")), "2026-10-14")
        n.transcript = "פגישה ב-15 באוקטובר"                            # no weekday said: keep the date
        self.assertEqual(str(n._day("2026-10-15")), "2026-10-15")


class Knowledge(Base):
    def test_join_instructions_have_the_real_links(self):
        n = Notes(self.tmp / "notes", TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 12, 13, 0, tzinfo=TZ)),
                  store=self.store, family=self.fam, speaker=self.p["avi"],
                  join_info=lambda who: {"download": "https://github.com/noless-zz/jar/releases/latest",
                                         "pair_link": f"jar://pair?v=1&t=TOKEN-{who.id}&u=x" if who else ""})
        out = n.get_join_instructions("יוני")
        self.assertIn("releases/latest", out)
        self.assertIn("jar://pair?v=1&t=TOKEN-yoni", out)
        self.assertIn("הדבקת קישור", out)
        self.assertIn("Paste link", n.get_join_instructions("yoni", "en"))
        self.assertIn("ask me for your personal pairing code", n.get_join_instructions("Bob", "en"))
        out = n.draft_join_instructions("yoni")
        self.assertIn("WhatsApp message ready to יוני", out)
        msg = [t for t in self.store.snapshot(self.p["avi"])["tasks"] if t.get("kind") == "message"][0]["message"]
        self.assertTrue(msg.startswith("היי יוני!"))
        self.assertIn("jar://pair?v=1&t=TOKEN-yoni", msg)
        self.assertIn("releases/latest", msg)
        again = n.draft_whatsapp("עוד הודעה", to="yoni")                # second one in the same memo: ignored
        self.assertIn("already prepared", again)
        self.assertEqual(len([t for t in self.store.snapshot(self.p["avi"])["tasks"] if t.get("kind") == "message"]), 1)

    def test_search_notes(self):
        root = self.tmp / "notes"
        (root / "Inbox").mkdir(parents=True)
        (root / "Inbox" / "wifi.md").write_text("# ראוטר\nהסיסמה של הוויפי של האורחים היא jar-guest-2026\n",
                                                encoding="utf-8")
        n = Notes(root, TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 12, 13, 0, tzinfo=TZ)),
                  store=self.store, family=self.fam, speaker=self.p["avi"])
        self.assertIn("jar-guest-2026", n.search_notes("סיסמה ויפי אורחים"))
        self.assertIn("nothing found", n.search_notes("פיצה"))


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
        self.server.FAMILY = self.fam
        self.server.TASKS = self.store
        self.server.TOKEN = "admin-token-123"
        self.c = self.TestClient(self.server.app)
        self.h = lambda pid: {"Authorization": "Bearer " + self.fam.token_for(pid), "X-Device-Id": "t"}

    def test_me_tasks_and_actions(self):
        r = self.c.get("/v1/me", headers=self.h("yoni"))
        self.assertEqual(r.json()["person"]["id"], "yoni")
        self.assertEqual(len(r.json()["family"]), 4)
        r = self.c.post("/v1/tasks", headers=self.h("dana"),
                        json={"title": "לסדר את החדר", "assignee": "yoni", "due": "2026-10-11"})
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()["id"]
        r = self.c.get("/v1/tasks", headers=self.h("yoni"))
        self.assertEqual([t["id"] for t in r.json()["tasks"]], [tid])
        r = self.c.post(f"/v1/tasks/{tid}/snooze", headers=self.h("yoni"), json={"until": "2026-10-11T19:00"})
        self.assertEqual(r.json()["snoozed_until"], "2026-10-11T19:00")
        r = self.c.post(f"/v1/tasks/{tid}/done", headers=self.h("yoni"))
        self.assertEqual(r.json()["status"], "done")
        self.assertEqual(self.c.post(f"/v1/tasks/{tid}/done", headers=self.h("maya")).status_code, 404)
        self.assertEqual(self.c.get("/v1/tasks", headers={"Authorization": "Bearer x"}).status_code, 401)
        self.assertEqual(self.c.post("/v1/tasks", headers=self.h("avi"),
                                     json={"title": "x", "assignee": "bob"}).status_code, 400)

    def test_my_memos_and_refile(self):
        import json as _j
        day = self.server.DATA_DIR / "2026-10-10"
        day.mkdir(parents=True, exist_ok=True)
        for mid, who in (("1111111111111111", "yoni"), ("2222222222222222", "dana")):
            (day / f"{mid}.json").write_text(_j.dumps({"id": mid, "person": who, "status": "done",
                                                        "transcript": "תזכיר לי לקנות חלב", "actions": [],
                                                        "recorded_at": "2026-10-10T10:00:00Z"}), encoding="utf-8")
        r = self.c.get("/v1/memos", headers=self.h("yoni")).json()["memos"]
        self.assertEqual([m["id"] for m in r if m["id"] in ("1111111111111111", "2222222222222222")],
                         ["1111111111111111"])
        r = self.c.post("/v1/memos/1111111111111111/refile", headers=self.h("yoni"),
                        json={"transcript": "תזכיר לי לקנות לחם"})
        self.assertEqual(r.json()["status"], "transcribed", r.text)
        m = _j.loads((day / "1111111111111111.json").read_text(encoding="utf-8"))
        self.assertEqual((m["transcript"], m["edited"], m["original_transcript"]),
                         ("תזכיר לי לקנות לחם", True, "תזכיר לי לקנות חלב"))
        self.assertEqual(self.c.post("/v1/memos/2222222222222222/refile", headers=self.h("yoni")).status_code, 404)
        self.assertEqual(self.c.post("/v1/memos/1111111111111111/refile", headers=self.h("yoni"),
                                     json={"transcript": "  "}).status_code, 400)

    def test_dashboard_login_only_for_admin(self):
        self.assertEqual(self.c.post("/v1/dashboard-login", headers=self.h("dana")).status_code, 403)
        r = self.c.post("/v1/dashboard-login", headers=self.h("avi"))
        self.assertTrue(r.json()["path"].startswith("login?n="))


if __name__ == "__main__":
    unittest.main()
