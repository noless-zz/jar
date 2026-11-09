"""#26: fix what Jar heard without filing the memo again; parents check the kids' memos; coins for fixes."""

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path

from worker.family import Family
from worker.points import PointsConfig, PointsStore

FAMILY_CFG = {
    "avi": {"name": "אבי", "role": "parent", "admin": True},
    "dana": {"name": "דנה", "role": "parent"},
    "yoni": {"name": "יוני", "role": "child"},
    "maya": {"name": "מאיה", "role": "child"},
}


class MemoFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
        os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())
        from fastapi.testclient import TestClient

        from server import server
        cls.server, cls.TestClient = server, TestClient

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY_CFG, "admin-token-123", self.tmp / "data")
        s = self.server
        s.FAMILY, s.TOKEN = self.fam, "admin-token-123"
        self.points = PointsStore(self.tmp / "points.json", self.fam, cfg=PointsConfig(memo_fix_coins=5, memo_fix_per_day=2))
        self._old_points, s.POINTS = s.POINTS, self.points
        self._old_dir, s.DATA_DIR = s.DATA_DIR, self.tmp / "memos"
        self.day = s.DATA_DIR / "2026-11-09"
        self.day.mkdir(parents=True)
        self.c = self.TestClient(s.app)
        self.h = lambda pid: {"Authorization": "Bearer " + self.fam.token_for(pid), "X-Device-Id": "t"}

    def tearDown(self):
        self.server.POINTS, self.server.DATA_DIR = self._old_points, self._old_dir

    def memo(self, mid, who, text, status="done", at="2026-11-09T10:00:00Z", **extra):
        m = {"id": mid, "person": who, "status": status, "transcript": text, "actions": [], "recorded_at": at} | extra
        (self.day / f"{mid}.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        with wave.open(str(self.day / f"{mid}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 1600)
        return mid

    def meta(self, mid):
        return json.loads((self.day / f"{mid}.json").read_text(encoding="utf-8"))

    def test_fix_keeps_the_original_and_does_not_refile(self):
        mid = self.memo("1" * 16, "yoni", "לקפל כביסה ולפנות יתריות")
        r = self.c.post(f"/v1/memos/{mid}/text", headers=self.h("yoni"), json={"transcript": "לקפל כביסה ולקנות אטריות"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["edited"], r.json()["checked"], r.json()["award"]["coins"]), (True, True, 5))
        m = self.meta(mid)
        self.assertEqual(m["status"], "done")                                  # not queued for the agent again
        self.assertEqual((m["original_transcript"], m["transcript"], m["checked_by"]),
                         ("לקפל כביסה ולפנות יתריות", "לקפל כביסה ולקנות אטריות", "yoni"))
        self.assertEqual((self.day / f"{mid}.txt").read_text(encoding="utf-8").strip(), "לקפל כביסה ולקנות אטריות")
        # fixing it again keeps the first original and pays nothing more
        r = self.c.post(f"/v1/memos/{mid}/text", headers=self.h("yoni"), json={"transcript": "לקפל כביסה ולקנות אטריות אורז"})
        self.assertIsNone(r.json()["award"])
        self.assertEqual(self.meta(mid)["original_transcript"], "לקפל כביסה ולפנות יתריות")

    def test_correct_as_is_counts_as_checked_without_coins(self):
        mid = self.memo("2" * 16, "maya", "להאכיל את החתול")
        r = self.c.post(f"/v1/memos/{mid}/text", headers=self.h("maya"), json={"correct": True})
        self.assertEqual((r.json()["checked"], r.json()["edited"], r.json()["award"]), (True, False, None))
        self.assertNotIn("original_transcript", self.meta(mid))

    def test_who_may_fix(self):
        kid = self.memo("3" * 16, "yoni", "א")
        mom = self.memo("4" * 16, "dana", "ב")
        fix = lambda mid, who: self.c.post(f"/v1/memos/{mid}/text", headers=self.h(who), json={"transcript": "ג"}).status_code  # noqa: E731
        self.assertEqual(fix(kid, "maya"), 404)                                # a sibling can't
        self.assertEqual(fix(mom, "avi"), 404)                                 # a parent can't fix the other parent's
        self.assertEqual(fix(kid, "dana"), 200)                                # a parent can fix a kid's
        self.assertEqual(self.meta(kid)["fixed_by"], "dana")
        self.assertEqual(self.c.get(f"/v1/memos/{kid}/audio", headers=self.h("dana")).headers["content-type"], "audio/wav")
        self.assertEqual(self.c.get(f"/v1/memos/{kid}/audio", headers=self.h("maya")).status_code, 404)

    def test_not_while_filing_and_not_empty(self):
        busy = self.memo("5" * 16, "yoni", "א", status="transcribed")
        self.assertEqual(self.c.post(f"/v1/memos/{busy}/text", headers=self.h("yoni"), json={"transcript": "ב"}).status_code, 409)
        mid = self.memo("6" * 16, "yoni", "א")
        self.assertEqual(self.c.post(f"/v1/memos/{mid}/text", headers=self.h("yoni"), json={"transcript": " "}).status_code, 400)
        self.assertEqual(self.c.post("/v1/memos/zzz/text", headers=self.h("yoni"), json={"correct": True}).status_code, 400)

    def test_daily_cap_and_coins_off_by_default(self):
        ids = [self.memo(c * 16, "yoni", "א") for c in "789"]
        paid = [self.c.post(f"/v1/memos/{i}/text", headers=self.h("yoni"), json={"transcript": "ב"}).json()["award"] for i in ids]
        self.assertEqual([bool(a) for a in paid], [True, True, False])         # memo_fix_per_day = 2
        self.assertIsNone(PointsStore(self.tmp / "p2.json", self.fam).pay_memo_fix("yoni", "a" * 16, "x"))

    def test_review_list_for_parents(self):
        self.memo("a" * 16, "yoni", "לקנות מגבת", at="2026-11-09T09:00:00Z",
                  shadow={"model": "parakeet-he", "text": "לקנות נייר מגבת"})
        self.memo("b" * 16, "maya", "לקפל", at="2026-11-09T11:00:00Z", checked=True)
        self.memo("c" * 16, "dana", "של אמא")
        self.memo("d" * 16, "maya", "עוד", status="received")
        self.assertEqual(self.c.get("/v1/memos/review", headers=self.h("yoni")).status_code, 403)
        r = self.c.get("/v1/memos/review", headers=self.h("dana")).json()
        self.assertEqual([m["id"] for m in r["memos"]], ["a" * 16])
        self.assertEqual((r["memos"][0]["name"], r["memos"][0]["shadow"]), ("יוני", "לקנות נייר מגבת"))
        # my own list shows the other reading and the checked mark
        mine = self.c.get("/v1/memos", headers=self.h("maya")).json()["memos"]
        self.assertTrue(next(m for m in mine if m["id"] == "b" * 16)["checked"])

    def test_bench_takes_a_checked_memo_as_a_human_reference(self):
        from worker import asr_bench
        self.memo("e" * 16, "yoni", "להאכיל את החתול", checked=True)
        got = asr_bench.select(self.day.parent, self.fam)
        self.assertEqual(next(m for m in got if m.id == "e" * 16).human_ref, "להאכיל את החתול")


if __name__ == "__main__":
    unittest.main()
