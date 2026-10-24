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
                 language: str = "", vocabulary: str = "", vad: str = "default", normalize: bool = False):
        self.model_name = model
        self.language = language_for(model, language)
        self.vad = vad if vad in ("default", "gentle", "off") else "default"
        self.normalize = bool(normalize)
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
