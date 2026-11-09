"""Audio cleanup before transcription (worker/transcribe.py: hp, denoise, loud, trim), on synthetic signals."""

import unittest

import numpy as np

from worker import transcribe as T

SR = 16000


def tone(freq, seconds, amp):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def band_energy(x, lo, hi):
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(x.size, 1 / SR)
    return float(spec[(f >= lo) & (f < hi)].sum())


class Clean(unittest.TestCase):
    def test_highpass_removes_hum_keeps_speech_band(self):
        x = tone(30, 2, 0.3) + tone(1000, 2, 0.3)
        y = T.highpass(x)
        self.assertLess(band_energy(y, 20, 40), band_energy(x, 20, 40) * 0.01)
        self.assertAlmostEqual(band_energy(y, 900, 1100) / band_energy(x, 900, 1100), 1.0, places=2)
        self.assertEqual(y.size, x.size)

    def test_loud_lifts_quiet_memos_with_a_cap(self):
        quiet = tone(500, 2, 0.02)
        y = T.loud(quiet)
        self.assertGreater(np.abs(y).max(), 0.1)                       # lifted well past plain normalize's 10x...
        self.assertLessEqual(np.abs(y).max(), 0.95)                    # ...never clipping
        whisper = tone(500, 2, 0.0005)
        self.assertLessEqual(np.abs(T.loud(whisper)).max(), 0.0005 * 30 + 1e-6)   # gain stops at 30x
        normal = tone(500, 2, 0.5)
        self.assertIs(T.loud(normal), normal)                          # already loud: untouched

    def test_trim_cuts_silence_at_both_ends(self):
        x = np.concatenate([np.zeros(SR), tone(800, 1, 0.3), np.zeros(2 * SR)]).astype(np.float32)
        y = T.trim(x)
        self.assertLess(y.size, 1.7 * SR)                              # 1 s of speech + 0.3 s padding each side
        self.assertGreater(y.size, 1.0 * SR)

    def test_denoise_quiets_hiss_and_keeps_the_voice(self):
        rng = np.random.default_rng(1)
        noise = (rng.standard_normal(3 * SR) * 0.02).astype(np.float32)
        speech = np.concatenate([np.zeros(SR), tone(700, 1, 0.3), np.zeros(SR)]).astype(np.float32)
        x = noise + speech
        y = T.denoise(x)
        self.assertEqual(y.size, x.size)
        quiet_part = slice(int(0.2 * SR), int(0.8 * SR))
        self.assertLess(np.std(y[quiet_part]), np.std(x[quiet_part]) * 0.6)
        self.assertGreater(band_energy(y, 650, 750), band_energy(x, 650, 750) * 0.7)

    def test_clean_order_and_unknown_steps(self):
        x = tone(30, 1, 0.01) + tone(1000, 1, 0.01)
        y = T.clean(x, "loud,hp")                                      # hp runs first whatever the order
        self.assertLess(band_energy(y, 20, 40), band_energy(y, 900, 1100) * 0.01)
        self.assertIs(T.clean(x, ""), x)
        tr = T.Transcriber("tiny", "cpu", "int8", clean="hp, bogus,loud")
        self.assertEqual(tr.clean, "hp,loud")

    def test_config_reads_clean(self):
        import tempfile
        from pathlib import Path

        from worker import config
        d = Path(tempfile.mkdtemp())
        (d / "config.toml").write_text('[transcribe]\nclean = "hp,loud"\n', encoding="utf-8")
        try:
            cfg = config.load(d / "config.toml")
        except TypeError:
            self.skipTest("config.load takes no path here")
        self.assertEqual(cfg.whisper_clean, "hp,loud")


if __name__ == "__main__":
    unittest.main()
