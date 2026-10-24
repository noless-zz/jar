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


if __name__ == "__main__":
    unittest.main()
