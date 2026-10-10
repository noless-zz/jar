"""Calendar/email: payloads for Graph + Google, and account routing with fallbacks."""

import base64
import email
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.connectors import (NotConnected, Result, gmail_draft, google_event, graph_draft,
                               graph_event)
from worker.tools import MemoContext, Notes

TZ = ZoneInfo("Asia/Jerusalem")
WHEN = datetime(2026, 10, 10, 16, 30, tzinfo=TZ)


class PayloadTest(unittest.TestCase):
    def test_graph_timed_event_in_utc(self):
        b = graph_event("Parent meeting", date(2026, 10, 15), "18:30", 45, TZ, "Room 4", "bring grades")
        self.assertEqual(b["start"], {"dateTime": "2026-10-15T15:30:00", "timeZone": "UTC"})
        self.assertEqual(b["end"], {"dateTime": "2026-10-15T16:15:00", "timeZone": "UTC"})
        self.assertEqual(b["location"], {"displayName": "Room 4"})
        self.assertNotIn("attendees", b)          # phase 1: never invites anyone

    def test_graph_winter_time(self):
        b = graph_event("x", date(2026, 12, 1), "09:00", 60, TZ)   # Israel winter = UTC+2
        self.assertEqual(b["start"]["dateTime"], "2026-12-01T07:00:00")

    def test_graph_all_day(self):
        b = graph_event("Trip", date(2026, 10, 20), None, 60, TZ)
        self.assertTrue(b["isAllDay"])
        self.assertEqual(b["end"]["dateTime"], "2026-10-21T00:00:00")

    def test_google_event(self):
        b = google_event("Staff meeting", date(2026, 10, 15), "14:00", 60, TZ)
        self.assertEqual(b["start"], {"dateTime": "2026-10-15T14:00:00+03:00", "timeZone": "Asia/Jerusalem"})
        self.assertEqual(google_event("Trip", date(2026, 10, 20), None, 60, TZ)["end"], {"date": "2026-10-21"})

    def test_drafts(self):
        g = graph_draft(["a@b.com"], "Hi", "שלום")
        self.assertEqual(g["toRecipients"], [{"emailAddress": {"address": "a@b.com"}}])
        raw = gmail_draft(["a@b.com"], "שאלה", "שלום, מה שלומך?")["message"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)),
                                       policy=email.policy.default)
        self.assertEqual(msg["To"], "a@b.com")
        self.assertEqual(msg["Subject"], "שאלה")
        self.assertIn("שלום, מה שלומך?", msg.get_content())


class FakeConn:
    name = "Fake"

    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def create_event(self, *a):
        self.calls.append(("event", a))
        if self.fail:
            raise self.fail
        return Result("Outlook calendar", "https://outlook.live.com/x")

    def create_draft(self, *a):
        self.calls.append(("draft", a))
        if self.fail:
            raise self.fail
        return Result("Gmail drafts (school)", "https://mail.google.com/y")


def notes(accounts):
    return Notes(Path(tempfile.mkdtemp()), TZ, MemoContext("a8481493440a567b", WHEN), accounts=accounts)


class RoutingTest(unittest.TestCase):
    def test_event_goes_to_connected_calendar(self):
        personal = FakeConn()
        n = notes({"personal": personal, "school": None})
        r = n.create_event("Dentist", "2026-10-14", "09:00", 30, account="personal")
        self.assertTrue(r.startswith("ok"))
        self.assertEqual(personal.calls[0][1][:4], ("Dentist", date(2026, 10, 14), "09:00", 30))
        self.assertEqual(n.actions[0]["link"], "https://outlook.live.com/x")
        self.assertFalse(list((n.root / "Calendar").glob("*.ics")) if (n.root / "Calendar").exists() else [])

    def test_unconnected_account_falls_back_to_ics(self):
        n = notes({"school": FakeConn(fail=NotConnected("Google: not signed in"))})
        r = n.create_event("Staff meeting", "2026-10-15", "14:00", account="school")
        self.assertIn("saved as .ics: Google: not signed in", r)
        self.assertEqual(len(list((n.root / "Calendar").glob("*.ics"))), 1)

    def test_api_error_still_keeps_the_event(self):
        n = notes({"personal": FakeConn(fail=RuntimeError("Graph 503"))})
        r = n.create_event("x", "2026-10-15", account="personal")
        self.assertIn("Graph 503", r)
        self.assertEqual(len(list((n.root / "Calendar").glob("*.ics"))), 1)

    def test_draft_to_school_gmail_only_with_explicit_address(self):
        school = FakeConn()
        n = notes({"school": school})
        n.draft_email("Field trip", "Hello...", to="Dana, dana@example.org", account="school")
        self.assertEqual(school.calls[0][1][0], ["dana@example.org"])   # names without @ are dropped
        self.assertIn("in Gmail drafts (school)", n.actions[0]["summary"])

    def test_draft_without_account_is_a_note(self):
        n = notes({})
        n.draft_email("Hi", "Body", account="personal")
        self.assertEqual(len(list((n.root / "Email drafts").glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
