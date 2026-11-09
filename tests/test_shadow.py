"""Shadow transcript (worker/shadow.py): saved next to production, never breaks filing, switches itself off."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from worker import asr_bench as B
from worker.shadow import MAX_FAILS, Shadow


class Fake:
    def __init__(self, texts=None, fail=0):
        self.texts, self.fail, self.closed = texts or {}, fail, False

    def transcribe(self, wav):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("model crashed")
        return SimpleNamespace(text=self.texts.get(Path(wav).stem, "שלום"))

    def close(self):
        self.closed = True


class ShadowTest(unittest.TestCase):
    def test_off_unless_configured(self):
        self.assertIsNone(Shadow(Path("."), "").transcribe(Path("a.wav")))

    def test_saves_text_and_starts_once(self):
        starts = []

        def start():
            starts.append(1)
            return Fake({"m1": "לקנות חלב"})
        sh = Shadow(Path("."), "parakeet-he", start=start)
        r = sh.transcribe(Path("/x/m1.wav"))
        self.assertEqual((r["model"], r["text"]), ("parakeet-he", "לקנות חלב"))
        sh.transcribe(Path("/x/m2.wav"))
        self.assertEqual(len(starts), 1)

    def test_failures_restart_then_switch_off(self):
        fakes = []

        def start():
            fakes.append(Fake(fail=1))
            return fakes[-1]
        sh = Shadow(Path("."), "parakeet-he", start=start)
        for i in range(MAX_FAILS):
            self.assertIn("error", sh.transcribe(Path(f"/x/{i}.wav")))
        self.assertTrue(all(f.closed for f in fakes))                 # a crashed process is closed and restarted
        self.assertTrue(sh.off)
        self.assertIsNone(sh.transcribe(Path("/x/later.wav")))

    def test_missing_environment_says_so_once(self):
        sh = Shadow(Path(tempfile.mkdtemp()), "parakeet-he")
        self.assertIsNone(sh.transcribe(Path("/x/a.wav")))
        self.assertIn("isn't set up", sh.off)
        sh2 = Shadow(Path("."), "unknown-model")
        self.assertIsNone(sh2.transcribe(Path("/x/a.wav")))
        self.assertIn("no runner candidate", sh2.off)


class BenchRealUse(unittest.TestCase):
    def test_report_compares_production_and_shadow_on_fixed_memos(self):
        import wave
        tmp = Path(tempfile.mkdtemp())
        d = tmp / "data" / "memos" / "2026-11-09"
        d.mkdir(parents=True)
        with wave.open(str(d / "aaa.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 16000)
        (d / "aaa.json").write_text(json.dumps({
            "id": "aaa", "person": "noam", "transcript": "לקנות נייר מגבת", "edited": True,
            "original_transcript": "אפשר לקנות לנייר נגדת",
            "shadow": {"model": "parakeet-he", "text": "לקנות נייר מגבת"}}, ensure_ascii=False), encoding="utf-8")

        class F:
            def transcribe(self, wav):
                return SimpleNamespace(text="x")

            def close(self):
                pass
        cfg = SimpleNamespace(data_dir=tmp / "data", family={"noam": {"name": "נועם", "role": "parent", "admin": True}},
                              token="t", contacts=None, vocabulary="")
        rep = B.run(cfg, keys=["base"], make=lambda c, cfg: F(), cloud=False)
        self.assertEqual(rep["live"]["shadow"]["wer"], 0)
        self.assertGreater(rep["live"]["production"]["wer"], 0.5)
        md = (tmp / "data" / "eval" / "asr" / "report.md").read_text(encoding="utf-8")
        self.assertIn("Real use", md)
        self.assertIn("*shadow heard:* לקנות נייר מגבת", md)


class ConfigTest(unittest.TestCase):
    def test_reads_shadow_settings(self):
        from worker import config
        d = Path(tempfile.mkdtemp())
        (d / "config.toml").write_text('[transcribe]\nshadow = "parakeet-he"\n', encoding="utf-8")
        cfg = config.load(d / "config.toml")
        self.assertEqual((cfg.whisper_shadow, cfg.whisper_shadow_device), ("parakeet-he", "cpu"))


if __name__ == "__main__":
    unittest.main()
