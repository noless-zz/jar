"""Unit tests: python -m unittest discover -s tests   (run from the jar folder)"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.agent import Agent
from worker.memos import MemoFile, pending
from worker.tools import MemoContext, Notes, slug

TZ = ZoneInfo("Asia/Jerusalem")
WHEN = datetime(2026, 10, 10, 10, 41, tzinfo=TZ)  # a Saturday


def make_notes(root: Path) -> Notes:
    return Notes(root, TZ, MemoContext("a8481493440a567b", WHEN))


class FakeAgent(Agent):
    """Replays scripted model replies instead of calling Ollama."""

    def __init__(self, replies):
        super().__init__("http://unused", "fake")
        self.replies, self.seen = list(replies), []

    def _chat(self, messages, tools, think=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else {"content": "Done."}


def call(name, **args):
    return {"function": {"name": name, "arguments": args}}


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.n = make_notes(self.dir)

    def test_slug_keeps_hebrew_and_drops_illegal(self):
        self.assertEqual(slug('רעיון: "פונקציות" / שיעור?'), "רעיון פונקציות שיעור")
        self.assertEqual(slug("   "), "untitled")

    def test_note_file_has_front_matter_and_link(self):
        self.n.save_note("Warm-up on asymptotes", "Start with a graph puzzle", ["math", "#10th grade"])
        f = next((self.dir / "Inbox").glob("*.md"))
        text = f.read_text(encoding="utf-8")
        self.assertIn("tags: [math, 10th-grade]", text)
        self.assertIn("[[Memos/2026-10-10|memo 10:41]]", text)
        self.assertTrue(f.name.startswith("2026-10-10 1041 Warm-up"))

    def test_task_line(self):
        self.n.add_task("Submit grades", "2026-10-15", "8:00")
        line = (self.dir / "Tasks.md").read_text(encoding="utf-8").splitlines()[-1]
        self.assertTrue(line.startswith("- [ ] Submit grades 📅 2026-10-15 ⏰ 08:00"))

    def test_bad_date_is_reported_to_model(self):
        r = Agent._execute({"add_task": __import__("worker.tools", fromlist=["registry"]).registry(self.n)["add_task"]},
                           "add_task", {"title": "x", "due_date": "someday soon"})
        self.assertTrue(r.startswith("error: due_date"))

    def test_event_ics_is_utc_and_valid(self):
        self.n.create_event("Parent meeting", "2026-10-15", "18:30", 45, "Room 4")
        ics = next((self.dir / "Calendar").glob("*.ics")).read_text(encoding="utf-8")
        self.assertIn("DTSTART:20261015T153000Z", ics)   # 18:30 Israel summer time = 15:30 UTC
        self.assertIn("DTEND:20261015T161500Z", ics)
        self.assertIn("LOCATION:Room 4", ics)
        raw = next((self.dir / "Calendar").glob("*.ics")).read_bytes()
        self.assertTrue(raw.startswith(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))   # RFC 5545 line endings

    def test_all_day_event(self):
        self.n.create_event("School trip", "2026-10-20")
        ics = next((self.dir / "Calendar").glob("*.ics")).read_text(encoding="utf-8")
        self.assertIn("DTSTART;VALUE=DATE:20261020", ics)

    def test_daily_log_lists_actions(self):
        self.n.add_task("Buy chalk")
        self.n.log_memo(4200, "phone-01", "Buy chalk", "en", "Added a task.")
        log = (self.dir / "Memos/2026-10-10.md").read_text(encoding="utf-8")
        self.assertIn("## 10:41 · 4.2 s · phone-01 · en", log)
        self.assertIn("> Buy chalk", log)
        self.assertIn("[[Tasks.md]]", log)


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.n = make_notes(self.dir)

    def test_two_tools_in_one_memo(self):
        a = FakeAgent([{"content": "", "tool_calls": [
            call("add_task", title="Submit grades", due_date="2026-10-15", due_time="08:00"),
            call("save_lesson_idea", idea="Graph puzzle opener", class_name="10th grade")]},
            {"content": "Added a task and a lesson idea."}])
        r = a.run("remind me ... and lesson idea ...", self.n, WHEN, "Asia/Jerusalem")
        self.assertEqual([x["tool"] for x in r.actions], ["add_task", "save_lesson_idea"])
        self.assertFalse(r.fallback)
        self.assertEqual(r.summary, "Added a task and a lesson idea.")
        self.assertIn("2026-10-10 10:41 (Saturday)", a.seen[0][0]["content"])

    def test_string_arguments_and_errors_are_fed_back(self):
        a = FakeAgent([
            {"content": "", "tool_calls": [{"function": {"name": "make_coffee", "arguments": {}}},
                                           {"function": {"name": "add_task", "arguments": "{}"}}]},
            {"content": "", "tool_calls": [{"function": {"name": "add_task",
                                                         "arguments": json.dumps({"title": "Call mom"})}}]},
            {"content": "<think>hmm</think>Added a task."}])
        r = a.run("call mom", self.n, WHEN, "Asia/Jerusalem")
        tool_msgs = [m["content"] for m in a.seen[1] if m["role"] == "tool"]
        self.assertTrue(tool_msgs[0].startswith("error: unknown tool"))
        self.assertEqual(tool_msgs[1], "error: missing title")
        self.assertEqual(len(r.actions), 1)
        self.assertEqual(r.summary, "Added a task.")

    def test_no_tool_call_falls_back_to_unsorted_note(self):
        a = FakeAgent([{"content": "Sure! I will remember that."}])
        r = a.run("something about the yard", self.n, WHEN, "Asia/Jerusalem")
        self.assertTrue(r.fallback)
        note = next((self.dir / "Inbox").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("tags: [unsorted]", note)
        self.assertIn("something about the yard", note)

    def test_tags_as_string_are_split(self):
        a = FakeAgent([{"content": "", "tool_calls": [call("save_note", title="t", body="b", tags="a, b")]}])
        a.run("x", self.n, WHEN, "Asia/Jerusalem")
        self.assertIn("tags: [a, b]", next((self.dir / "Inbox").glob("*.md")).read_text(encoding="utf-8"))


class FlakyAgent(FakeAgent):
    """First reply works, then Ollama breaks (like the 0.40 symlink bug)."""

    def _chat(self, messages, tools, think=None):
        if self.seen:
            from worker.agent import OllamaUnavailable
            raise OllamaUnavailable("Ollama error 500: untrusted mount point")
        return super()._chat(messages, tools)


class AgentFailureTest(unittest.TestCase):
    def test_failure_after_filing_keeps_the_action(self):
        n = make_notes(Path(tempfile.mkdtemp()))
        a = FlakyAgent([{"content": "", "tool_calls": [call("save_note", title="t", body="b")]}])
        r = a.run("x", n, WHEN, "Asia/Jerusalem")
        self.assertEqual(len(r.actions), 1)
        self.assertFalse(r.fallback)

    def test_failure_before_filing_is_raised(self):
        from worker.agent import OllamaUnavailable

        class Down(FakeAgent):
            def _chat(self, messages, tools, think=None):
                raise OllamaUnavailable("down")
        with self.assertRaises(OllamaUnavailable):
            Down([]).run("x", make_notes(Path(tempfile.mkdtemp())), WHEN, "Asia/Jerusalem")

    def test_ollama_500_means_wait_not_fail(self):
        import io
        import urllib.error
        from unittest import mock
        from worker.agent import OllamaUnavailable
        err = urllib.error.HTTPError("http://x/api/chat", 500, "err", {}, io.BytesIO(b'{"error":"untrusted mount point"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(OllamaUnavailable):
                Agent("http://x", "m")._chat([], [])


class MemoStoreTest(unittest.TestCase):
    def test_pending_ignores_done_and_half_written(self):
        d = Path(tempfile.mkdtemp())
        day = d / "memos/2026-10-10"
        day.mkdir(parents=True)
        for i, status in enumerate(["received", "done", "transcribed"]):
            (day / f"{i:016x}.wav").write_bytes(b"x")
            (day / f"{i:016x}.json").write_text(json.dumps(
                {"id": f"{i:016x}", "status": status, "recorded_at": f"2026-10-10T0{3 - i}:00:00Z"}))
        (day / "broken.json").write_text("{")
        got = [m.id for m in pending(d)]
        self.assertEqual(got, ["0000000000000002", "0000000000000000"])   # oldest recording first

    def test_update_is_atomic_and_keeps_fields(self):
        d = Path(tempfile.mkdtemp())
        p = d / "x.json"
        p.write_text(json.dumps({"id": "x", "status": "received", "sha256": "abc"}))
        m = MemoFile(p, json.loads(p.read_text()))
        m.update(status="done", transcript="שלום")
        saved = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(saved["sha256"], "abc")
        self.assertEqual(saved["transcript"], "שלום")
        self.assertFalse((d / "x.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()


class ContextBudget(unittest.TestCase):
    """The instructions and tool list must fit in the model's context with room for the memo and the
    model's reasoning; past it Ollama silently drops the memo (it happened: 10/26 in the AI test)."""

    def test_prompt_and_tools_fit(self):
        import json
        import tempfile
        from datetime import datetime
        from pathlib import Path
        from zoneinfo import ZoneInfo

        from worker.agent import Agent, system_prompt
        from worker.family import Family
        from worker.taskstore import TaskStore
        from worker.tools import MemoContext, Notes, registry
        tz = ZoneInfo("Asia/Jerusalem")
        cfg = {"a": {"name": "נועם", "role": "parent", "admin": True}, "b": {"name": "סווטה", "role": "parent"},
               "c": {"name": "ליבנה", "role": "child"}, "d": {"name": "אלונה", "role": "child"}}
        tmp = Path(tempfile.mkdtemp())
        fam = Family.from_config(cfg, "t", tmp)
        n = Notes(tmp / "n", tz, MemoContext("e" * 16, datetime(2026, 10, 12, 13, 0, tzinfo=tz)), accounts={},
                  store=TaskStore(tmp / "t.json", fam), family=fam, speaker=fam.admin,
                  family_account=object())                 # the biggest tool list: family account on too
        self.assertIn("email_family", registry(n))
        text = system_prompt(n, datetime(2026, 10, 12, 13, 0, tzinfo=tz), "Asia/Jerusalem", "x" * 200)
        text += json.dumps([t.schema() for t in registry(n).values()], ensure_ascii=False)
        tokens = len(text) / 2.5                          # pessimistic for Hebrew-heavy text
        agent = Agent("http://x", "m")
        self.assertLess(tokens, agent.num_ctx * 0.7, f"~{tokens:.0f} tokens of {agent.num_ctx}")
