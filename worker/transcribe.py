"""Speech to text with faster-whisper. The model is loaded once and kept in memory,
which is why the worker is a long-running loop rather than a scheduled job."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("jar.transcribe")


@dataclass
class Transcript:
    text: str
    language: str
    language_probability: float
    seconds: float


def _add_cuda_dlls() -> None:
    """On Windows, pip's nvidia-cublas/cudnn wheels put their DLLs in site-packages/nvidia/*/bin.
    CTranslate2 only finds them if those folders are on the DLL search path."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if nv.is_dir():
            for bin_dir in nv.glob("*/bin"):
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


# Voice-activity detection presets ([transcribe] vad). faster-whisper's own default drops soft word onsets and
# endings (threshold 0.5, 400 ms padding) — quiet or hesitant speech, a child far from the mic.
VAD = {
    "default": {},
    "gentle": {"threshold": 0.3, "min_silence_duration_ms": 1000, "speech_pad_ms": 800},
}


def normalize(audio):
    """Remove DC and lift a quiet recording toward a 0.9 peak, at most 10x (20 dB). Loud audio is left alone."""
    import numpy as np
    if not isinstance(audio, np.ndarray) or audio.size == 0:
        return audio
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio)))
    if 0 < peak < 0.5:
        audio = audio * min(0.9 / peak, 10.0)
    return audio.astype(np.float32)


# ---------------------------------------------------------------- audio cleanup ([transcribe] clean)
# Steps, comma-separated, applied in this order after normalize: "hp", "denoise", "loud", "trim". numpy only (the PC
# has no scipy). Each one is a bench candidate first (worker/asr_bench.py): noise removal can hurt recognition.
SR = 16000


def highpass(audio, cutoff: float = 80.0):
    """Remove rumble, hum and handling noise below ~80 Hz (speech has almost nothing there). FFT with a soft edge."""
    import numpy as np
    n = audio.size
    spec = np.fft.rfft(audio)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    gain = np.clip((f - cutoff / 2) / (cutoff / 2), 0.0, 1.0)      # 0 below 40 Hz, ramps to 1 at 80 Hz
    return np.fft.irfft(spec * gain, n).astype(np.float32)


def _frames(audio, size: int, hop: int):
    import numpy as np
    if audio.size < size:
        audio = np.pad(audio, (0, size - audio.size))
    count = 1 + (audio.size - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return audio[idx], audio


def denoise(audio, strength: float = 1.5, floor: float = 0.15):
    """Light spectral gating: the noise profile is the quietest 10% of 32 ms frames; each frequency bin is turned
    down where it doesn't rise above that noise. floor keeps 15% so words never vanish completely."""
    import numpy as np
    size, hop = 512, 128
    if audio.size < size * 4:
        return audio
    frames, padded = _frames(audio, size, hop)
    win = np.hanning(size).astype(np.float32)
    spec = np.fft.rfft(frames * win, axis=1)
    mag = np.abs(spec)
    energy = mag.sum(axis=1)
    quiet = mag[energy <= np.percentile(energy, 10)]
    noise = quiet.mean(axis=0) if quiet.size else np.zeros(mag.shape[1])
    gain = np.clip((mag - strength * noise) / np.maximum(mag, 1e-9), floor, 1.0)
    # smooth the gain over time so it doesn't "bubble" (musical noise)
    k = np.ones(5) / 5
    gain = np.apply_along_axis(lambda g: np.convolve(g, k, mode="same"), 0, gain)
    out_frames = np.fft.irfft(spec * gain, size, axis=1) * win
    out = np.zeros(padded.size, dtype=np.float32)
    norm = np.zeros(padded.size, dtype=np.float32)
    for i, fr in enumerate(out_frames):                               # overlap-add
        out[i * hop:i * hop + size] += fr
        norm[i * hop:i * hop + size] += win ** 2
    out = out / np.maximum(norm, 1e-6)
    return out[:audio.size].astype(np.float32)


def loud(audio, target_db: float = -20.0, max_gain: float = 30.0):
    """Bring speech to a steady level: RMS of the loudest half-second parts to -20 dBFS, at most 30x (the plain
    normalize stops at 10x; 19 of 87 family memos peak under 0.1). Peaks above 0.95 are softly limited."""
    import numpy as np
    frames, _ = _frames(audio, 8000, 4000)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    level = float(np.percentile(rms, 90)) if rms.size else 0.0
    if level <= 1e-5:
        return audio
    g = min(10 ** (target_db / 20) / level, max_gain)
    if g <= 1.0:
        return audio
    out = audio * g
    return (np.tanh(out / 0.95) * 0.95).astype(np.float32)


def trim(audio, pad_s: float = 0.3):
    """Cut silence at the start and the end (keeps 0.3 s around the speech)."""
    import numpy as np
    size = 320                                                        # 20 ms
    frames, _ = _frames(audio, size, size)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    if not rms.size or rms.max() <= 0:
        return audio
    thr = max(rms.max() * 0.05, np.percentile(rms, 20) * 2)
    on = np.where(rms > thr)[0]
    if not on.size:
        return audio
    pad = int(pad_s * SR)
    a, b = max(0, on[0] * size - pad), min(audio.size, (on[-1] + 1) * size + pad)
    return audio[a:b]


CLEAN = {"hp": highpass, "denoise": denoise, "loud": loud, "trim": trim}


def clean(audio, steps: str):
    import numpy as np
    if not isinstance(audio, np.ndarray) or audio.size == 0 or not steps:
        return audio
    names = [s.strip() for s in steps.split(",") if s.strip()]
    for name in ("hp", "denoise", "loud", "trim"):                    # fixed order whatever the config says
        if name in names:
            audio = CLEAN[name](audio)
    return audio.astype(np.float32)


def language_for(model: str, language: str) -> str | None:
    """ivrit-ai's Hebrew models weakened language detection on purpose: they must run with "he"."""
    if not language and "ivrit" in (model or "").lower():
        return "he"
    return language or None


def load_audio(wav: Path):
    """Memos are always 16 kHz mono 16-bit WAV (pendant and phone app), so read them with the
    standard library instead of faster-whisper's PyAV decoder — one less version to break.
    Anything else (e.g. a file dropped in by hand) still goes through PyAV."""
    import wave

    import numpy as np
    try:
        with wave.open(str(wav), "rb") as w:
            if w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
                return pcm.astype(np.float32) / 32768.0
    except (wave.Error, EOFError):
        pass
    return str(wav)


class Transcriber:
    def __init__(self, model: str, device: str = "auto", compute_type: str = "auto",
                 language: str = "", vocabulary: str = "", vad: str = "default", normalize: bool = False,
                 clean: str = ""):
        self.model_name = model
        self.language = language_for(model, language)
        self.vad = vad if vad in ("default", "gentle", "off") else "default"
        self.normalize = bool(normalize)
        self.clean = ",".join(s for s in (clean or "").replace(" ", "").split(",") if s in CLEAN)
        self.vocabulary = vocabulary or None
        self.device, self.compute_type = self._pick(device, compute_type)
        self._model = None

    @staticmethod
    def _pick(device: str, compute_type: str) -> tuple[str, str]:
        if device == "auto":
            try:
                _add_cuda_dlls()
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:  # noqa: BLE001 — any problem means: use the CPU
                device = "cpu"
        if compute_type == "auto":
            compute_type = "int8_float16" if device == "cuda" else "int8"
        return device, compute_type

    def _load(self):
        from faster_whisper import WhisperModel
        if self.device == "cuda":
            _add_cuda_dlls()
        t0 = time.monotonic()
        log.info("loading Whisper %s on %s (%s)…", self.model_name, self.device, self.compute_type)
        self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        log.info("Whisper ready in %.1f s", time.monotonic() - t0)

    def close(self) -> None:
        """Free the model (the ASR bench loads one candidate at a time)."""
        self._model = None
        import gc
        gc.collect()

    def transcribe(self, wav: Path) -> Transcript:
        if self._model is None:
            self._load()
        t0 = time.monotonic()
        try:
            return self._run(wav, t0)
        except RuntimeError as e:
            # Typical on Windows: "Library cublas64_12.dll is not found". Keep working on the CPU.
            if self.device != "cuda":
                raise
            log.warning("GPU transcription failed (%s); switching to CPU", e)
            self.device, self.compute_type = "cpu", "int8"
            self._load()
            return self._run(wav, time.monotonic())

    def _run(self, wav: Path, t0: float) -> Transcript:
        audio = load_audio(wav)
        if self.normalize:
            audio = normalize(audio)
        if self.clean:
            audio = clean(audio, self.clean)
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.vocabulary,
            beam_size=5,
            vad_filter=self.vad != "off",  # skip silence, avoids hallucinated text on quiet memos
            vad_parameters=VAD.get(self.vad) or None,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(text, info.language, round(info.language_probability, 3),
                          round(time.monotonic() - t0, 2))
