"""Extra speech models for the ASR bench: candidate choice, environment setup, the runner bridge, LLM combos."""

import json
import sys
import tempfile
import textwrap
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from worker import asr_bench as B
from worker import asr_extra as X
from worker import asr_runner as R

FAMILY = {"noam": {"name": "נועם", "role": "parent", "admin": True},
          "alona": {"name": "אלונה", "role": "child"}}


def write_wav(path: Path, seconds=1.0, sr=16000, amp=0.05, ch=1):
    t = np.arange(int(sr * seconds)) / sr
    a = (amp * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    if ch == 2:
        a = np.repeat(a, 2)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())


class Choose(unittest.TestCase):
    def test_extras_only_when_asked(self):
        std = [c.key for c in B.choose(None)]
        self.assertIn("ivrit-gentle", std)
        self.assertNotIn("caspi", std)
        self.assertNotIn("combo-2", std)
        allc = [c.key for c in B.choose(None, extra=True)]
        self.assertIn("parakeet-he", allc)
        self.assertIn("combo-3", allc)

    def test_a_named_combo_brings_its_inputs(self):
        got = {c.key for c in B.choose(["combo-2"])}
        self.assertEqual(got, {"combo-2", "ivrit-gentle", "caspi", B.REFERENCE})


class Combo(unittest.TestCase):
    def test_combo_reads_the_other_transcripts(self):
        tmp = Path(tempfile.mkdtemp())
        d = tmp / "data" / "memos" / "2026-11-09"
        d.mkdir(parents=True)
        write_wav(d / "aaa.wav")
        (d / "aaa.json").write_text(json.dumps({"id": "aaa", "person": "noam", "transcript": "לקנות נייר מגבת",
                                                "edited": True, "original_transcript": "x"}, ensure_ascii=False),
                                    encoding="utf-8")
        heard = {"ivrit-gentle": "לקנות נייר נגבת", "caspi": "לקנות ניר מגבת", "ivrit-large": "לקנות נייר"}
        asked = []

        class Fake:
            def __init__(self, c):
                self.c = c

            def transcribe(self, wav):
                return SimpleNamespace(text=heard[self.c.key])

            def close(self):
                pass

        def reconcile(texts):
            asked.append(texts)
            return "לקנות נייר מגבת"
        cfg = SimpleNamespace(data_dir=tmp / "data", family=FAMILY, token="t", contacts=None, vocabulary="")
        rep = B.run(cfg, keys=["combo-2"], make=lambda c, cfg: Fake(c), reconcile=reconcile, cloud=False)
        self.assertEqual(asked, [["לקנות נייר נגבת", "לקנות ניר מגבת"]])
        self.assertEqual(rep["summary"]["combo-2"]["human"]["wer"], 0)
        self.assertGreater(rep["summary"]["caspi"]["human"]["wer"], 0)


class Env(unittest.TestCase):
    def test_install_once_then_reuse(self):
        tmp = Path(tempfile.mkdtemp())
        cmds = []

        def run(cmd, logf, beat=None):
            cmds.append(cmd)
            if cmd[1:3] == ["-m", "venv"]:
                py = X.env_python(tmp, "tf5")
                py.parent.mkdir(parents=True, exist_ok=True)
                py.write_text("")
            return 0
        py = X.ensure_env(tmp, "tf5", run=run)
        self.assertTrue(py.exists())
        self.assertEqual(len(cmds), 1 + len(X.ENVS["tf5"]))
        self.assertTrue(any("--index-url" in c for c in cmds))                   # CUDA torch
        X.ensure_env(tmp, "tf5", run=run)
        self.assertEqual(len(cmds), 1 + len(X.ENVS["tf5"]))                      # second time: nothing to do

    def test_failed_step_says_so_and_stays_unfinished(self):
        tmp = Path(tempfile.mkdtemp())

        def run(cmd, logf, beat=None):
            if "venv" in cmd:
                X.env_python(tmp, "qwen").parent.mkdir(parents=True, exist_ok=True)
                X.env_python(tmp, "qwen").write_text("")
                return 0
            return 1
        with self.assertRaises(RuntimeError):
            X.ensure_env(tmp, "qwen", run=run)
        self.assertFalse((tmp / "asr-envs" / "qwen" / ".jar-ready").exists())

    def test_refuses_without_disk_space(self):
        old = X.MIN_FREE_GB
        X.MIN_FREE_GB = 10 ** 9
        try:
            with self.assertRaisesRegex(RuntimeError, "GB free"):
                X.ensure_env(Path(tempfile.mkdtemp()), "tf5", run=lambda *a, **k: 0)
        finally:
            X.MIN_FREE_GB = old


FAKE_RUNNER = textwrap.dedent('''
    import json, sys
    if "--fail" in sys.argv:
        print(json.dumps({"error": "OSError: no such model"}), flush=True)
        sys.exit(0)
    print("some library noise on stdout", flush=True)
    print(json.dumps({"ready": True, "device": "cpu"}), flush=True)
    for line in sys.stdin:
        wav = json.loads(line)["wav"]
        if wav.endswith("bad.wav"):
            print(json.dumps({"error": "ValueError: bad audio"}), flush=True)
        else:
            print(json.dumps({"text": "שלום " + wav[-7:-4]}, ensure_ascii=False), flush=True)
''')


class Bridge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.script = self.tmp / "fake_runner.py"
        self.script.write_text(FAKE_RUNNER, encoding="utf-8")

    def test_round_trip_in_hebrew(self):
        tr = X.ExternalTranscriber(Path(sys.executable), "qwen", "m", cmd=[sys.executable, str(self.script)],
                                   log_file=self.tmp / "x.log")
        self.assertEqual(tr.transcribe(Path("/a/abc.wav")).text, "שלום abc")
        with self.assertRaisesRegex(RuntimeError, "bad audio"):
            tr.transcribe(Path("/a/bad.wav"))
        self.assertEqual(tr.transcribe(Path("/a/xyz.wav")).text, "שלום xyz")
        tr.close()

    def test_load_failure_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "no such model"):
            X.ExternalTranscriber(Path(sys.executable), "qwen", "m",
                                  cmd=[sys.executable, str(self.script), "--fail"])


class Runner(unittest.TestCase):
    def test_load_wav_resamples_mixes_and_lifts(self):
        tmp = Path(tempfile.mkdtemp())
        write_wav(tmp / "s.wav", seconds=1, sr=8000, amp=0.05, ch=2)
        a = R.load_wav(str(tmp / "s.wav"))
        self.assertEqual(a.dtype, np.float32)
        self.assertAlmostEqual(a.size, 16000, delta=2)
        self.assertGreater(np.abs(a).max(), 0.4)                                 # quiet input lifted (10x cap)

    def test_runner_never_imports_jar_modules_by_accident(self):
        here = str(Path(R.__file__).parent)
        self.assertNotIn(here, [str(Path(p).resolve()) for p in sys.path if p])


if __name__ == "__main__":
    unittest.main()
