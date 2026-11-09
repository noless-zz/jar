"""ASR bench: Hebrew scoring maths, memo selection, references, and a run with a fake transcriber."""

import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from worker import asr_bench as B
from worker.family import Family
from worker.transcribe import language_for, normalize

FAMILY = {"noam": {"name": "נועם", "role": "parent", "admin": True},
          "alona": {"name": "אלונה", "role": "child"}}


class Scoring(unittest.TestCase):
    def test_hebrew_normalization(self):
        self.assertEqual(B.norm_text("שָׁלוֹם, עולם!"), "שלומ עולמ")
        self.assertEqual(B.norm_text("צה״ל ו-ג׳ירפה"), "צהל ו גירפה")
        self.assertEqual(B.norm_text("Jar  קניות"), "jar קניות")

    def test_ops_and_rates(self):
        r = B.score("לקנות חלב ולחם בסופר", "לקנות חלב בסופר")
        self.assertEqual((r["S"], r["D"], r["I"]), (0, 1, 0))
        self.assertAlmostEqual(r["wer"], 0.25)
        self.assertAlmostEqual(r["del"], 0.25)
        r = B.score("להוציא את הכלב", "להוציא את הכלבים עכשיו")
        self.assertEqual((r["S"], r["D"], r["I"]), (1, 0, 1))
        self.assertEqual(B.score("", "")["words"], 0)

    def test_aggregate_is_word_weighted(self):
        a = B.aggregate([dict(B.score("א ב ג ד", "א ב ג ד"), seconds=1, audio_s=4),
                         dict(B.score("ה ו", ""), seconds=1, audio_s=2)])
        self.assertAlmostEqual(a["wer"], 2 / 6)
        self.assertAlmostEqual(a["rtf"], 2 / 6)


class Audio(unittest.TestCase):
    def test_normalize(self):
        quiet = (np.sin(np.linspace(0, 50, 16000)) * 0.05 + 0.01).astype(np.float32)
        out = normalize(quiet)
        self.assertAlmostEqual(float(np.mean(out)), 0.0, places=3)
        self.assertAlmostEqual(float(np.max(np.abs(out))), 0.5, places=2)       # capped at 10x
        loud = np.array([0.8, -0.7], dtype=np.float32)
        self.assertAlmostEqual(float(np.max(np.abs(normalize(loud)))), 0.75, places=2)   # only DC removed

    def test_ivrit_runs_in_hebrew(self):
        self.assertEqual(language_for("ivrit-ai/whisper-large-v3-turbo-ct2", ""), "he")
        self.assertIsNone(language_for("large-v3-turbo", ""))
        self.assertEqual(language_for("ivrit-ai/x", "en"), "en")


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fam = Family.from_config(FAMILY, "t", self.tmp / "data")
        memos = self.tmp / "data" / "memos" / "2026-10-20"
        memos.mkdir(parents=True)

        def memo(mid, person, text, edited=False, original="", at="2026-10-20T10:00:00Z"):
            with wave.open(str(memos / f"{mid}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 32000)                           # 2 s
            m = {"id": mid, "person": person, "recorded_at": at, "transcript": text}
            if edited:
                m.update(edited=True, original_transcript=original)
            (memos / f"{mid}.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        memo("aaa", "noam", "לקנות חלב ולחם", True, "לקנות חלב", "2026-10-20T08:00:00Z")
        memo("bbb", "alona", "לקפל כביסה", at="2026-10-20T09:00:00Z")
        memo("ccc", "noam", "תזכורת לרופא", at="2026-10-20T11:00:00Z")
        (memos / "ddd.json").write_text("{}", encoding="utf-8")                # no audio: skipped

    def test_selection_order(self):
        got = B.select(self.tmp / "data" / "memos", self.fam, limit=10)
        self.assertEqual([m.id for m in got], ["aaa", "bbb", "ccc"])           # corrected, then the kid, then newest
        self.assertEqual(got[0].human_ref, "לקנות חלב ולחם")
        self.assertEqual(got[0].production, "לקנות חלב")
        self.assertAlmostEqual(got[0].audio_s, 2.0)
        self.assertEqual([m.id for m in B.select(self.tmp / "data" / "memos", self.fam, person="alona")], ["bbb"])

    def test_run_with_fake_models(self):
        heard = {"base": {"aaa": "לקנות חלב", "bbb": "לקפל", "ccc": "תזכורת לרופא"},
                 "ivrit-gentle": {"aaa": "לקנות חלב ולחם", "bbb": "לקפל כביסה", "ccc": "תזכורת לרופא"},
                 "ivrit-large": {"aaa": "לקנות חלב ולחם", "bbb": "לקפל כביסה", "ccc": "תזכורת לרופא"}}

        class Fake:
            def __init__(self, c):
                self.c = c

            def transcribe(self, wav):
                return SimpleNamespace(text=heard[self.c.key][wav.stem])

            def close(self):
                pass
        cfg = SimpleNamespace(data_dir=self.tmp / "data", family=FAMILY, token="t", contacts=None)
        B.MIN_WORDS = 1
        rep = B.run(cfg, keys=["base", "ivrit-gentle"], make=lambda c, cfg: Fake(c))
        s = rep["summary"]
        self.assertEqual(set(s), {"base", "ivrit-gentle", "ivrit-large"})
        self.assertAlmostEqual(s["base"]["human"]["del"], 1 / 3)               # dropped "ולחם"
        self.assertEqual(s["ivrit-gentle"]["human"]["wer"], 0)
        self.assertEqual(s["base"]["auto"]["words"], 4)                         # bbb + ccc vs the auto reference
        self.assertEqual(s["ivrit-large"]["auto"].get("words", 0), 0)          # never scored against itself
        md = (self.tmp / "data" / "eval" / "asr" / "report.md").read_text(encoding="utf-8")
        self.assertIn("ASR bench: 3 memos (1 hand-corrected)", md)
        self.assertIn("ivrit-gentle", rep["recommendation"])

    def test_gemini_reference(self):
        """Gemini fills the reference for uncorrected memos, is cached, and is scored on the corrected one."""
        heard = {"base": {"aaa": "לקנות חלב", "bbb": "לקפל", "ccc": "תזכורת לרופא"},
                 "ivrit-large": {"aaa": "לקנות חלב ולחם", "bbb": "משהו אחר", "ccc": "משהו אחר"}}
        gemini = {"aaa": "לקנות חלב ולחם", "bbb": "לקפל כביסה", "ccc": "תזכורת לרופא"}
        calls = []

        def post(url, headers, body):
            calls.append(body)
            self.assertIn("gemini-3.5-transcribe", url)
            self.assertNotIn("key=", url)                                    # key in the header, not the URL
            self.assertIn("audioTranscriptionConfig", body["generationConfig"])
            self.assertIn("אלונה", body["generationConfig"]["audioTranscriptionConfig"]["customVocabulary"])
            mid = next(k for k in gemini if k not in [c.get("_done") for c in calls[:-1]])
            calls[-1]["_done"] = mid
            return 200, {"candidates": [{"content": {"parts": [{"text": gemini[mid]}]}}]}

        class Fake:
            def __init__(self, c):
                self.c = c

            def transcribe(self, wav):
                return SimpleNamespace(text=heard[self.c.key][wav.stem])

            def close(self):
                pass
        (self.tmp / "data" / "secrets").mkdir(parents=True)
        (self.tmp / "data" / "secrets" / "gemini_key.txt").write_text("k\n", encoding="utf-8")
        cfg = SimpleNamespace(data_dir=self.tmp / "data", family=FAMILY, token="t", contacts=None, vocabulary="")
        B.MIN_WORDS = 4                         # too few corrected words (3) to decide; Gemini's 4 are enough
        rep = B.run(cfg, keys=["base"], make=lambda c, cfg: Fake(c), cloud_post=post)
        self.assertEqual(len(calls), 3)
        self.assertEqual(rep["cloud"]["refs"], 2)                             # bbb + ccc; aaa has a human ref
        self.assertEqual(rep["cloud"]["vs_human"]["wer"], 0)                  # Gemini matched the corrected memo
        s = rep["summary"]
        self.assertAlmostEqual(s["base"]["cloud"]["del"], 1 / 4)              # dropped "כביסה"
        self.assertEqual(s["ivrit-large"]["cloud"]["words"], 4)               # scored too, not the reference now
        self.assertEqual(s["base"]["auto"].get("words", 0), 0)
        self.assertTrue(rep["recommendation"].startswith("base"))
        self.assertIn("Gemini", rep["recommendation"])
        md = (self.tmp / "data" / "eval" / "asr" / "report.md").read_text(encoding="utf-8")
        self.assertIn("**Gemini:** לקפל כביסה", md)
        B.run(cfg, keys=["base"], make=lambda c, cfg: Fake(c), cloud_post=post)
        self.assertEqual(len(calls), 3)                                       # second run: all from the cache

    def test_gemini_bad_key_stops_early(self):
        (self.tmp / "data" / "secrets").mkdir(parents=True)
        (self.tmp / "data" / "secrets" / "gemini_key.txt").write_text("bad", encoding="utf-8")
        calls = []

        def post(url, headers, body):
            calls.append(1)
            return 400, {"error": {"message": "API key not valid"}}
        from worker import cloud_ref
        memos = B.select(self.tmp / "data" / "memos", self.fam)
        cfg = SimpleNamespace(data_dir=self.tmp / "data", vocabulary="")
        st = cloud_ref.references(memos, cfg, self.fam, self.tmp / "out", post=post)
        self.assertEqual(len(calls), 1)
        self.assertIn("API key not valid", st["error"])
        self.assertFalse(any(m.cloud_ref for m in memos))

    def test_gemini_daily_quota_stops_at_once(self):
        (self.tmp / "data" / "secrets").mkdir(parents=True)
        (self.tmp / "data" / "secrets" / "gemini_key.txt").write_text("k", encoding="utf-8")
        calls = []

        def post(url, headers, body):
            calls.append(1)
            return 429, {"error": {"message": "Quota exceeded for metric: generate_content_free_tier_requests, "
                                              "limit: 25 ... requests per day limit exceeded on Free Tier."}}
        from worker import cloud_ref
        memos = B.select(self.tmp / "data" / "memos", self.fam)
        st = cloud_ref.references(memos, SimpleNamespace(data_dir=self.tmp / "data", vocabulary=""), self.fam,
                                  self.tmp / "out", post=post)
        self.assertEqual(len(calls), 1)                                       # no retries, no other memos
        self.assertEqual(st["failed"], 1)


class CloudParsing(unittest.TestCase):
    def test_text_from_shapes(self):
        from worker.cloud_ref import text_from
        self.assertEqual(text_from({"candidates": [{"content": {"parts": [{"text": " שלום "}]}}]}), "שלום")
        self.assertEqual(text_from({"candidates": [{"content": {"parts": [
            {"audioTranscription": {"words": [{"word": "לקנות"}, {"word": "חלב"}]}}]}}]}), "לקנות חלב")
        self.assertEqual(text_from({"candidates": [{"content": {"parts": [                # the real shape (11-09)
            {"audioTranscription": {"text": "לקנות חלב"}}]}}]}), "לקנות חלב")
        self.assertEqual(text_from({}), "")

    def test_general_model_gets_a_prompt(self):
        from worker.cloud_ref import body_for
        b = body_for(b"RIFF", "gemini-3.8-flash", ["נועם"])
        self.assertIn("נועם", b["contents"][0]["parts"][0]["text"])
        self.assertEqual(b["contents"][0]["parts"][1]["inlineData"]["mimeType"], "audio/wav")


if __name__ == "__main__":
    unittest.main()
