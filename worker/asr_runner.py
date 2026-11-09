"""Runs one extra speech model for the ASR bench in its OWN Python environment (see worker/asr_extra.py).

Standalone on purpose: it imports nothing from Jar, so it works inside data/asr-envs/<env> where only torch and the
model's library are installed. Protocol: start with the model, print one JSON line {"ready": true} (or
{"error": ...}), then for each JSON line {"wav": path} on stdin print {"text": ...} or {"error": ...}.

    python worker/asr_runner.py --kind qwen --model OzLabs/Caspi-1.7B --language Hebrew --context "שמות: ..."
    python worker/asr_runner.py --kind parakeet --model thewh1teagle/parakeet-tdt-0.6b-v3-he

Kinds:
- qwen: Qwen3-ASR checkpoints in the qwen-asr package's format (Caspi-1.7B, qwen-asr-0.6b-he). Hebrew is not on
  the base model's language list, so it is added here; nagisa (only for the timestamp aligner, no Windows wheel for
  Python 3.12) is stubbed.
- parakeet: NVIDIA Parakeet TDT checkpoints in transformers format (transformers >= 5.18).
"""

from __future__ import annotations

import os
import sys

# Jar's worker/ folder holds modules with library names (filelock.py): never import from the script's own folder.
_here = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.getcwd())) != _here]

import argparse  # noqa: E402
import json  # noqa: E402
import types  # noqa: E402
import wave  # noqa: E402


def load_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"only 16-bit WAV is supported ({sw * 8}-bit)")
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 16000:                                   # memos are 16 kHz; anything else: simple linear resample
        n = int(round(a.size * 16000 / sr))
        a = np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a).astype(np.float32)
    # same lift as production's normalize (worker/transcribe.py)
    a = a - float(a.mean()) if a.size else a
    peak = float(np.abs(a).max()) if a.size else 0.0
    if 0 < peak < 0.5:
        a = a * min(0.9 / peak, 10.0)
    return a.astype(np.float32)


class Qwen:
    def __init__(self, model: str, language: str, context: str, device: str, dtype: str = ""):
        for name in ("nagisa", "soynlp"):              # only the forced aligner uses them
            if name not in sys.modules:
                try:
                    __import__(name)
                except Exception:  # noqa: BLE001
                    sys.modules[name] = types.ModuleType(name)
        import torch
        import qwen_asr.inference.utils as U
        from qwen_asr import Qwen3ASRModel
        self.language = U.normalize_language_name(language) if language else None
        if self.language and self.language not in U.SUPPORTED_LANGUAGES:
            U.SUPPORTED_LANGUAGES.append(self.language)
        self.context = context
        dt = getattr(torch, dtype) if dtype else (torch.bfloat16 if device.startswith("cuda") else torch.float32)
        self.asr = Qwen3ASRModel.from_pretrained(model, dtype=dt, device_map=device,
                                                 max_inference_batch_size=1, max_new_tokens=512)

    def __call__(self, audio) -> str:
        out = self.asr.transcribe(audio=(audio, 16000), context=self.context, language=self.language)
        return (out[0].text or "").strip()


class Parakeet:
    def __init__(self, model: str, device: str):
        import torch
        from transformers import AutoModelForTDT, AutoProcessor
        self.torch, self.device = torch, device
        self.proc = AutoProcessor.from_pretrained(model)
        self.model = AutoModelForTDT.from_pretrained(model).to(device).eval()

    def __call__(self, audio) -> str:
        inputs = self.proc(audio, sampling_rate=16000, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(**inputs)
        seq = out.sequences if hasattr(out, "sequences") else out
        return self.proc.batch_decode(seq, skip_special_tokens=True)[0].strip()


def say(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=["qwen", "parakeet"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--language", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--device", default="")
    ap.add_argument("--dtype", default="", help="e.g. bfloat16 (qwen only; default: bfloat16 on GPU, float32 on CPU)")
    a = ap.parse_args(argv)
    for stream in (sys.stdin, sys.stdout):     # Hebrew both ways, whatever the Windows code page is
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    try:
        import torch
        device = a.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        run = Qwen(a.model, a.language, a.context, device, a.dtype) if a.kind == "qwen" else Parakeet(a.model, device)
    except Exception as e:  # noqa: BLE001
        say({"error": f"{type(e).__name__}: {e}"})
        return
    say({"ready": True, "device": device})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            say({"text": run(load_wav(json.loads(line)["wav"]))})
        except Exception as e:  # noqa: BLE001
            say({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
