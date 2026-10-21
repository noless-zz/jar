"""The family's own Jar Gmail: sends mail and calendar invitations, to family members only."""

import base64
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from worker.connectors import FamilyGoogle, NotFamily, Result, family_event, gmail_message
from worker.family import Family
from worker.taskstore import TaskStore
from worker.tools import MemoContext, Notes, registry

TZ = ZoneInfo("Asia/Jerusalem")
FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True, "email": "avi@example.com"},
    "dana": {"name": "דנה", "role": "parent", "email": "Dana@Example.com"},
    "yoni": {"name": "יוני", "role": "child", "aliases": ["Yoni"], "email": "yoni@example.com"},
    "maya": {"name": "מאיה", "role": "child", "aliases": ["Maya"]},              # no email
}


class FakeFamilyAccount:
    """Records calls; refuses non-family addresses exactly like FamilyGoogle."""

    def __init__(self, allowed):
        self.real = FamilyGoogle(Path("/nonexistent"), Path(tempfile.mkdtemp()), TZ, allowed)
        self.events, self.sent, self.notes, self.deleted = [], [], [], []

    def create_family_event(self, title, day, start, dur, attendees, location="", notes=""):
        self.events.append((title, day, start, self.real.check(attendees)))
        self.notes.append(notes)
        return Result("the family calendar", "https://calendar/x", f"ev{len(self.events)}")

    def delete_family_event(self, event_id):
        self.deleted.append(event_id)
        return True

    def send(self, to, subject, body):
        self.sent.append((self.real.check(to), subject, body))
        return Result("sent from the family account")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "t", self.tmp / "data")
        self.store = TaskStore(self.tmp / "data" / "tasks.json", self.fam)
        self.acct = FakeFamilyAccount(self.fam.emails())

    def notes(self, speaker, acct=True):
        return Notes(self.tmp / speaker, TZ, MemoContext("abcdef0123456789", datetime(2026, 10, 18, 19, 0, tzinfo=TZ)),
                     store=self.store, family=self.fam, speaker=self.fam.people[speaker],
                     family_account=self.acct if acct else None)


class Connector(Base):
    def test_only_family_addresses(self):
        g = self.acct.real
        self.assertEqual(g.check(["DANA@example.com ", "avi@example.com"]), ["dana@example.com", "avi@example.com"])
        with self.assertRaises(NotFamily):
            g.check(["dana@example.com", "boss@work.com"])
        with self.assertRaises(NotFamily):
            g.check([])

    def test_payloads(self):
        ev = family_event("הצגה", date(2026, 10, 23), "18:00", 90, TZ, ["dana@example.com"], "תיאטרון")
        self.assertEqual(ev["attendees"], [{"email": "dana@example.com"}])
        self.assertEqual(ev["start"]["dateTime"][:16], "2026-10-23T18:00")
        raw = base64.urlsafe_b64decode(gmail_message("", ["a@x.com"], "שלום", "גוף")["raw"]).decode()
        self.assertIn("To: a@x.com", raw)


class Tools(Base):
    def test_event_invites_family(self):
        out = self.notes("avi").create_event("הצגה של יוני", "2026-10-23", "18:00", invite=["dana", "yoni"])
        self.assertIn("invited", out)
        title, day, start, who = self.acct.events[0]
        self.assertEqual(who, ["avi@example.com", "dana@example.com", "yoni@example.com"])

    def test_plain_event_stays_personal(self):
        self.notes("avi").create_event("רופא שיניים", "2026-10-23", "09:00")
        self.assertEqual(self.acct.events, [])                  # no invite: the admin's own calendar / .ics

    def test_child_event_goes_to_family_calendar(self):
        n = self.notes("yoni")
        self.assertIn("create_event", registry(n))
        self.assertNotIn("draft_email", registry(n))
        n.create_event("חזרה להצגה", "2026-10-21", "16:00")
        self.assertEqual(self.acct.events[0][3], ["yoni@example.com"])

    def test_email_family(self):
        out = self.notes("dana").email_family("ארוחת שישי", "מי מביא קינוח?", ["avi", "yoni"])
        self.assertIn("sent", out)
        self.assertEqual(self.acct.sent[0][0], ["avi@example.com", "yoni@example.com"])

    def test_email_whole_family_skips_people_without_email(self):
        self.notes("avi").email_family("טיול", "יוצאים ב-8", [])
        self.assertEqual(self.acct.sent[0][0], ["dana@example.com", "yoni@example.com"])

    def test_without_account_nothing_is_sent(self):
        n = self.notes("avi", acct=False)
        self.assertNotIn("email_family", registry(n))
        self.assertNotIn("invite", registry(n)["create_event"].schema()["function"]["parameters"]["properties"])
        out = n.email_family("x", "y", ["dana"])
        self.assertIn("NOT sent", out)


if __name__ == "__main__":
    unittest.main()


class EventDetails(Base):
    """Every event says who asked and what they said; a vague one gets an "add details or delete" task."""

    def test_description_says_who_and_what(self):
        n = self.notes("yoni")
        n.transcript = "תוסיף ליומן חזרה להצגה ביום רביעי בארבע"
        n.create_event("חזרה להצגה", "2026-10-21", "16:00")
        desc = self.acct.notes[0]
        self.assertIn("לבקשת יוני", desc)
        self.assertIn("18/10 19:00", desc)
        self.assertIn(n.transcript, desc)
        self.assertEqual(n.actions[0]["event_id"], "ev1")

    def test_notes_kept_above_the_footer(self):
        n = self.notes("avi")
        n.family_event("ארוחת שישי", "2026-10-23", "all", "19:00", notes="אצל סבתא")
        self.assertTrue(self.acct.notes[0].startswith("אצל סבתא\n\n"))

    def test_clear_event_gets_no_followup(self):
        n = self.notes("yoni")
        out = n.family_event("לילה לבן של יוני", "2026-11-03", ["yoni"])
        self.assertNotIn("no details", out)
        self.assertEqual(self.store.snapshot(self.fam.people["yoni"])["tasks"], [])

    def test_vague_event_asks_the_creator(self):
        n = self.notes("yoni")
        n.transcript = "תוסיף למחר אירוע לכולם"
        out = n.family_event("אירוע משפחתי", "2026-10-19", "all")
        self.assertIn("no details", out)
        tasks = self.store.snapshot(self.fam.people["yoni"])["tasks"]
        self.assertEqual(len(tasks), 1)
        t = tasks[0]
        self.assertEqual((t["assignee"], t["created_by"], t["status"]), ("yoni", "yoni", "open"))
        self.assertIn("אירוע משפחתי", t["title"])
        self.assertEqual(t["due"], "2026-10-18T20:00")
        self.assertEqual(t["event"]["id"], "ev1")
        self.assertTrue(t["points"]["no_coins"])
        self.assertEqual([a["tool"] for a in n.actions], ["family_event", "add_task"])

    def test_vague_words(self):
        n = self.notes("avi")
        for title in ("אירוע", "אירוע משפחתי", "אירוע לכולם", "Family event", "פגישה מחר", "אירוע למחר"):
            self.assertTrue(n._vague_event(title), title)
        for title in ("יום הולדת לסבתא", "רופא שיניים", "הצגה", "לילה לבן"):
            self.assertFalse(n._vague_event(title), title)
        self.assertFalse(n._vague_event("אירוע", notes="מסיבת הפתעה"))

    def test_deleting_the_task_deletes_the_event(self):
        n = self.notes("yoni")
        n.family_event("אירוע", "2026-10-19", "all")
        t = self.store.snapshot(self.fam.people["yoni"])["tasks"][0]
        self.assertEqual(self.store.events_to_delete(), [])
        self.store.act(self.fam.people["yoni"], t["id"], "delete")
        self.assertEqual([x["id"] for x in self.store.events_to_delete()], [t["id"]])
        self.store.event_removed(t["id"])
        self.assertEqual(self.store.events_to_delete(), [])
