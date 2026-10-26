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
        self.assertEqual(set(registry(n)), {"save_note", "add_task", "find_tasks", "update_task", "note_on_task",
                                             "draft_whatsapp", "draft_join_instructions", "search_notes",
                                             "suggest_idea"})
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

    def test_question_by_voice(self):
        t = self.store.add(self.p["dana"], "לסדר את החדר", self.p["yoni"])
        out = self.notes("dana").note_on_task(t["id"], "סידרת כבר את הארון?", ask=True)
        self.assertIn("question to", out)
        self.assertEqual(self.store.snapshot(self.p["yoni"])["tasks"][0]["waiting_on"], "yoni")
        self.notes("yoni").note_on_task(t["id"], "כן, הכל מסודר")
        self.assertIsNone(self.store.snapshot(self.p["yoni"])["tasks"][0]["waiting_on"])

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

    def test_email_draft_comes_with_a_send_task(self):
        n = Notes(self.tmp / "notes", TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 11, 9, 0, tzinfo=TZ)),
                  accounts={}, store=self.store, family=self.fam, speaker=self.p["avi"])
        out = n.draft_email("אסיפת הורים", "שלום, ...", to="ruth@example.com", account="school")
        self.assertIn("task to send it", out)
        tasks = self.store.snapshot(self.p["avi"])["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual((tasks[0]["assignee"], tasks[0].get("kind", "task")), ("avi", "task"))
        self.assertIn("לשלוח את המייל: אסיפת הורים", tasks[0]["title"])
        self.assertIn("already exists", n.add_task("לשלוח את המייל לרות"))     # the model adding its own: skipped
        self.assertEqual(len(self.store.snapshot(self.p["avi"])["tasks"]), 1)

    def test_join_message_uses_the_public_page(self):
        from worker import join
        link = "jar://pair?v=1&t=SECRET&u=http%3A%2F%2F192.168.1.5%3A8080&u=https%3A%2F%2Fpc.ts.net"
        page = join.join_url(["http://192.168.1.5:8080", "https://pc.ts.net"], link)
        self.assertEqual(page, "https://pc.ts.net/v1/join#v=1&t=SECRET&u=http%3A%2F%2F192.168.1.5%3A8080&u=https%3A%2F%2Fpc.ts.net")
        self.assertEqual(join.join_url(["http://192.168.1.5:8080"], link), "")
        msg = join.message("ליבנה", join.DOWNLOAD, link, page)
        self.assertIn(page, msg)
        self.assertNotIn("jar://", msg)
        self.assertNotIn("Tailscale", msg)
        self.assertIn("jar://pair", join.message("ליבנה", join.DOWNLOAD, link, ""))    # no public address
        self.assertNotIn("SECRET", join.page())


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

    def test_delete_what_a_memo_made(self):
        """My memos → delete one item: the task and the note go now, the family event is left to the worker."""
        import json as _j
        from types import SimpleNamespace
        from worker.__main__ import Worker
        notes = self.tmp / "notes"
        self.server.NOTES_DIR = notes
        tid = self.c.post("/v1/tasks", headers=self.h("dana"), json={"title": "לקנות חלב", "assignee": "dana"}).json()["id"]
        note = notes / "Family" / "דנה" / "Inbox" / "2026-10-10 1000 רעיון.md"
        note.parent.mkdir(parents=True)
        note.write_text("x", encoding="utf-8")
        day = self.server.DATA_DIR / "2026-10-11"
        day.mkdir(parents=True, exist_ok=True)
        mid = "3333333333333333"
        acts = [{"tool": "add_task", "summary": "task", "task_id": tid, "file": "Tasks.md"},
                {"tool": "save_note", "summary": "note", "file": "Inbox/2026-10-10 1000 רעיון.md"},
                {"tool": "family_event", "summary": "event", "file": "Calendar.md", "event_id": "ev1"},
                {"tool": "update_task", "summary": "moved", "task_id": tid}]
        (day / f"{mid}.json").write_text(_j.dumps({"id": mid, "person": "dana", "status": "done", "actions": acts,
                                                    "recorded_at": "2026-10-11T10:00:00Z"}), encoding="utf-8")
        memo = next(m for m in self.c.get("/v1/memos", headers=self.h("dana")).json()["memos"] if m["id"] == mid)
        self.assertEqual([i["deletable"] for i in memo["items"]], [True, True, True, False])
        self.assertEqual(memo["actions"], ["task", "note", "event", "moved"])       # older apps still get the lines

        r = self.c.post(f"/v1/memos/{mid}/items/0/delete", headers=self.h("dana"))
        self.assertTrue(r.json()["items"][0]["removed"], r.text)
        self.assertNotIn(tid, [t["id"] for t in self.c.get("/v1/tasks", headers=self.h("dana")).json()["tasks"]])
        self.c.post(f"/v1/memos/{mid}/items/1/delete", headers=self.h("dana"))
        self.assertFalse(note.exists())
        r = self.c.post(f"/v1/memos/{mid}/items/2/delete", headers=self.h("dana")).json()["items"][2]
        self.assertEqual((r["removing"], r["removed"]), (True, False))
        self.assertEqual(self.c.post(f"/v1/memos/{mid}/items/3/delete", headers=self.h("dana")).status_code, 409)
        self.assertEqual(self.c.post(f"/v1/memos/{mid}/items/0/delete", headers=self.h("yoni")).status_code, 404)

        # The worker removes the event from the family calendar and marks it.
        gone = []
        fake = SimpleNamespace(cfg=SimpleNamespace(data_dir=self.server.DATA_ROOT), accounts={},
                               family_account=SimpleNamespace(delete_family_event=gone.append))
        self.assertEqual(Worker.memo_item_deletes(fake), 1)
        self.assertEqual(gone, ["ev1"])
        m = _j.loads((day / f"{mid}.json").read_text(encoding="utf-8"))
        self.assertTrue(m["actions"][2]["removed"])
        self.assertNotIn("removing", m["actions"][2])
        self.assertFalse(list((self.server.DATA_ROOT / "deletes").glob("*.json")))

    def test_delete_a_whole_memo(self):
        """My memos → delete the memo: its tasks (done too), note, logs and the recording itself all go."""
        import json as _j
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo
        from worker.__main__ import Worker
        notes = self.tmp / "notes2"
        self.server.NOTES_DIR = notes
        mid = "4444444444444444"
        open_t = self.store.add(self.fam.get("dana"), "לקנות מיסו", memo_id=mid)["id"]
        done_t = self.store.add(self.fam.get("dana"), "לקנות וואקמה", memo_id=mid)["id"]
        self.store.act(self.fam.get("dana"), done_t, "done")
        other = self.store.add(self.fam.get("dana"), "משהו אחר")["id"]
        root = notes / "Family" / "דנה"
        (root / "Inbox").mkdir(parents=True)
        (root / "Inbox" / "n.md").write_text("x", encoding="utf-8")
        (root / "Memos").mkdir()
        (root / "Memos" / "2026-10-12.md").write_text(
            "# Memos 2026-10-12\n\n## 13:00 · 3.0 s · phone · he\n> קודם\n\n- (no action)\n\n"
            "## 14:00 · 5.0 s · phone · he\n> לקנות מיסו\n\n- task\n\n", encoding="utf-8")
        day = self.server.DATA_DIR / "2026-10-12"
        day.mkdir(parents=True, exist_ok=True)
        for suffix in (".wav", ".txt"):
            (day / f"{mid}{suffix}").write_text("x", encoding="utf-8")
        (day / f"{mid}.json").write_text(_j.dumps({"id": mid, "person": "dana", "status": "done", "device_id": "phone",
            "duration_ms": 5000, "recorded_at": "2026-10-12T11:00:00Z", "transcript": "לקנות מיסו",
            "actions": [{"tool": "add_task", "summary": "task", "file": "Tasks.md"},
                        {"tool": "save_note", "summary": "note", "file": "Inbox/n.md"}]}), encoding="utf-8")
        self.assertEqual(self.c.post(f"/v1/memos/{mid}/delete", headers=self.h("yoni")).status_code, 404)
        r = self.c.post(f"/v1/memos/{mid}/delete", headers=self.h("dana"))
        self.assertEqual(r.json()["tasks"], 2, r.text)
        ids = [t["id"] for t in self.c.get("/v1/tasks", headers=self.h("dana")).json()["tasks"]]
        self.assertNotIn(open_t, ids)
        self.assertNotIn(done_t, ids)
        self.assertIn(other, ids)
        self.assertFalse((root / "Inbox" / "n.md").exists())
        self.assertNotIn(mid, [m["id"] for m in self.c.get("/v1/memos", headers=self.h("dana")).json()["memos"]])

        fake = SimpleNamespace(cfg=SimpleNamespace(data_dir=self.server.DATA_ROOT, notes_dir=notes), accounts={},
                               family_account=None, family=self.fam, tz=ZoneInfo("Asia/Jerusalem"))
        fake.delete_whole_memo = lambda mp, m: Worker.delete_whole_memo(fake, mp, m)
        Worker.memo_item_deletes(fake)
        self.assertFalse(any((day / f"{mid}{x}").exists() for x in (".wav", ".txt", ".json")))
        log = (root / "Memos" / "2026-10-12.md").read_text(encoding="utf-8")
        self.assertIn("קודם", log)
        self.assertNotIn("לקנות מיסו", log)

    def test_dashboard_login_only_for_admin(self):
        self.assertEqual(self.c.post("/v1/dashboard-login", headers=self.h("dana")).status_code, 403)
        r = self.c.post("/v1/dashboard-login", headers=self.h("avi"))
        self.assertTrue(r.json()["path"].startswith("login?n="))

    def test_invite_from_the_admins_phone(self):
        self.server._URLS.update(at=9e18, urls=["http://192.168.1.5:8080", "https://pc.ts.net"])
        try:
            funnel = {"Tailscale-Funnel-Request": "?1"}
            r = self.c.post("/v1/invite", headers={**self.h("avi"), **funnel}, json={"person": "yoni"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["public"])
            self.assertIn("https://pc.ts.net/v1/join#v=1&t=" + self.fam.token_for("yoni"), r.json()["text"])
            self.assertEqual(self.c.post("/v1/invite", headers=self.h("dana"), json={"person": "yoni"}).status_code, 403)
            self.assertEqual(self.c.post("/v1/invite", headers=self.h("avi"), json={"person": "bob"}).status_code, 400)
            page = self.c.get("/v1/join", headers=funnel)
            self.assertEqual(page.status_code, 200)
            self.assertIn("intent://pair?", page.text)
        finally:
            self.server._URLS.update(at=0.0, urls=[])

    def test_admin_looks_after_the_pc_from_the_phone(self):
        root = self.server.DATA_ROOT
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "logs" / "worker.log").write_text("\n".join(f"line {i}" for i in range(300)), encoding="utf-8")
        r = self.c.get("/v1/admin/status", headers=self.h("avi"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("supervisor", r.json())
        self.assertEqual(self.c.get("/v1/admin/status", headers=self.h("dana")).status_code, 403)
        r = self.c.get("/v1/admin/log?name=worker&lines=20", headers=self.h("avi"))
        self.assertEqual(r.json()["text"].splitlines()[-1], "line 299")
        self.assertEqual(len(r.json()["text"].splitlines()), 20)
        self.assertEqual(self.c.get("/v1/admin/log?name=../config", headers=self.h("avi")).status_code, 400)
        r = self.c.post("/v1/admin/command", headers=self.h("avi"), json={"cmd": "update"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(__import__("json").loads((root / "supervisor-cmd.json").read_text())["cmd"], "update")
        (root / "supervisor-cmd.json").unlink()
        self.c.post("/v1/admin/command", headers=self.h("avi"), json={"cmd": "eval"})
        self.assertTrue((root / "eval" / "run").exists())
        (root / "eval" / "run").unlink()
        self.assertEqual(self.c.post("/v1/admin/command", headers=self.h("yoni"), json={"cmd": "restart"}).status_code, 403)
        self.assertEqual(self.c.post("/v1/admin/command", headers=self.h("avi"), json={"cmd": "rm"}).status_code, 400)

    def test_invite_over_the_internet_uses_the_public_address_it_came_in_on(self):
        import time as _t
        self.server._URLS.update(at=_t.time(), urls=[])          # discovery failed on the PC
        try:
            h = {**self.h("avi"), "Tailscale-Funnel-Request": "?1", "Host": "pc.tail1.ts.net"}
            r = self.c.post("/v1/invite", headers=h, json={"person": "yoni"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn("https://pc.tail1.ts.net/v1/join#v=1&t=", r.json()["text"])
            self.assertEqual(self.c.post("/v1/invite", headers=self.h("avi"), json={"person": "yoni"}).status_code, 503)
        finally:
            self.server._URLS.update(at=0.0, urls=[])

    def test_notes_and_questions_on_a_task(self):
        r = self.c.post("/v1/tasks", headers=self.h("dana"), json={"title": "לסדר את החדר", "assignee": "yoni"})
        tid = r.json()["id"]
        r = self.c.post(f"/v1/tasks/{tid}/notes", headers=self.h("yoni"), json={"text": "גם את הארון?", "ask": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["waiting_on"], "dana")                  # the question goes to who asked
        self.assertEqual(self.c.post(f"/v1/tasks/{tid}/notes", headers=self.h("maya"),
                                     json={"text": "x"}).status_code, 404)  # another child can't see it
        r = self.c.post(f"/v1/tasks/{tid}/notes", headers=self.h("dana"), json={"text": "כן, גם הארון"})
        self.assertIsNone(r.json()["waiting_on"])                         # answered
        self.assertEqual([n["by"] for n in r.json()["thread"]], ["yoni", "dana"])
        r = self.c.patch(f"/v1/tasks/{tid}/notes/2", headers=self.h("dana"), json={"text": "כן, והמגירות"})
        self.assertEqual(r.json()["thread"][1]["text"], "כן, והמגירות")
        self.assertEqual(self.c.patch(f"/v1/tasks/{tid}/notes/2", headers=self.h("yoni"),
                                      json={"text": "x"}).status_code, 403)  # not your note
        r = self.c.post(f"/v1/tasks/{tid}/notes", headers=self.h("dana"), json={"text": "עד מתי?", "ask": True})
        self.assertEqual(r.json()["waiting_on"], "yoni")
        mine = self.c.post("/v1/tasks", headers=self.h("dana"), json={"title": "שלי"}).json()["id"]
        self.assertEqual(self.c.post(f"/v1/tasks/{mine}/notes", headers=self.h("dana"),
                                     json={"text": "?", "ask": True}).status_code, 400)

    def test_quick_replies_prompt_and_parsing(self):
        from worker import replies
        t = {"title": "לסדר את החדר", "assignee": "yoni", "created_by": "dana", "waiting_on": "yoni",
             "thread": [{"id": 1, "by": "dana", "text": "עד מתי?", "ask": True}]}
        prompt = replies.build_prompt(t, "yoni", {"yoni": "יוני", "dana": "דנה"})
        self.assertIn("Hebrew", prompt)
        self.assertIn("answer it", prompt)
        self.assertIn("דנה (question): עד מתי?", prompt)
        self.assertEqual(replies.parse('{"replies": ["עד שמונה", "עד מחר", "עד שמונה"]}'), ["עד שמונה", "עד מחר"])
        self.assertEqual(replies.parse('Sure! {"replies": ["ok"]}'), ["ok"])
        self.assertEqual(replies.parse("nonsense"), [])

    def test_internet_requests_only_reach_the_phone_api(self):
        funnel = {"Tailscale-Funnel-Request": "?1"}
        self.assertEqual(self.c.get("/", headers=funnel).status_code, 404)
        self.assertEqual(self.c.get("/pair", headers=funnel).status_code, 404)
        self.assertEqual(self.c.get("/v1/health", headers=funnel).status_code, 200)
        r = self.c.get("/v1/me", headers={**self.h("yoni"), **funnel})
        self.assertEqual(r.status_code, 200)
        self.assertIn("urls", r.json())

    def test_wrong_tokens_are_throttled_per_address(self):
        self.server._FAILS.clear()
        # Funnel traffic arrives from 127.0.0.1 with the real address appended last.
        bad = lambda ip: {"Authorization": "Bearer nope", "X-Forwarded-For": f"1.2.3.{ip}, 203.0.113.9"}  # noqa: E731
        for i in range(20):
            self.assertEqual(self.c.get("/v1/me", headers=bad(i)).status_code, 401)
        self.assertEqual(self.c.get("/v1/me", headers=bad(99)).status_code, 429)   # spoofed first entry doesn't help
        self.server._FAILS.clear()
        self.assertEqual(self.c.get("/v1/me", headers=self.h("yoni")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
