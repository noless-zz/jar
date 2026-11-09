"""Extra speech models for the ASR bench that don't run on faster-whisper (Caspi-1.7B, qwen-asr-0.6b-he, Parakeet he).

Each runs in its own Python environment under data/asr-envs/<env> (never in Jar's .venv: qwen-asr pins
transformers 4.57.6 while Parakeet needs transformers 5), created on first use, with CUDA torch. The model itself
downloads from Hugging Face the first time the runner loads it. Bench only: production never loads these.

Disk: about 5 GB per environment plus the models (Caspi ~4.7 GB, qwen-he ~1.8 GB, Parakeet ~2.5 GB).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

log = logging.getLogger("jar.asr_extra")

TORCH_INDEX = "https://download.pytorch.org/whl/cu128"     # RTX 30xx/40xx; CUDA 12.8 wheels for Python 3.12
RUNNER = Path(__file__).with_name("asr_runner.py")
MIN_FREE_GB = 15

# pip steps per environment. qwen-asr goes in without its dependency list: it pulls nagisa (no Windows wheel for
# Python 3.12, only used by the timestamp aligner; the runner stubs it), gradio, flask and sox.
ENVS = {
    "qwen": [["torch", "--index-url", TORCH_INDEX],
             ["--no-deps", "qwen-asr==0.0.6"],
             ["transformers==4.57.6", "accelerate==1.12.0", "librosa", "soundfile"]],
    "tf5": [["torch", "--index-url", TORCH_INDEX],
            ["transformers>=5.18,<6", "librosa"]],
}

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _env_dir(data_dir: Path, env: str) -> Path:
    return data_dir / "asr-envs" / env


def env_python(data_dir: Path, env: str) -> Path:
    d = _env_dir(data_dir, env)
    return d / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _spec_hash(env: str) -> str:
    return hashlib.sha1(json.dumps(ENVS[env]).encode()).hexdigest()[:12]


def _child_env() -> dict:
    e = dict(os.environ)
    e.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_PROGRESS_BARS="1",
             TRANSFORMERS_VERBOSITY="error", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return e


def _run_logged(cmd: list, logf: Path, beat=None, timeout: int = 3600) -> int:
    """Run a long command, append its output to logf, call beat() about once a minute (keeps the worker's
    heartbeat fresh so the supervisor doesn't restart it mid-install)."""
    with open(logf, "a", encoding="utf-8", errors="replace") as fh:
        fh.write("\n$ " + " ".join(map(str, cmd)) + "\n")
        fh.flush()
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=_child_env(), creationflags=NO_WINDOW)
        t0 = time.monotonic()
        while True:
            try:
                return p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                if beat:
                    beat()
                if time.monotonic() - t0 > timeout:
                    p.kill()
                    return -9


def _tail(f: Path, n: int = 6) -> str:
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return " | ".join(lines[-n:])[-600:]


def ensure_env(data_dir: Path, env: str, beat=None, run=None) -> Path:
    """The environment's python, creating and filling it first when needed. run(cmd, logf, beat) is injectable."""
    run = run or _run_logged
    d = _env_dir(data_dir, env)
    py = env_python(data_dir, env)
    stamp = d / ".jar-ready"
    if py.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == _spec_hash(env):
        return py
    d.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(d.parent).free / 1e9
    if free < MIN_FREE_GB:
        raise RuntimeError(f"only {free:.0f} GB free; installing {env} needs about {MIN_FREE_GB} GB")
    logf = d.parent / f"{env}-install.log"
    log.info("ASR bench: setting up the %s environment (a few GB, can take a while; log %s)", env, logf)
    if not py.exists():
        if run([sys.executable, "-m", "venv", str(d)], logf, beat) != 0:
            raise RuntimeError(f"couldn't create {d}: {_tail(logf)}")
    for step in ENVS[env]:
        if run([str(py), "-m", "pip", "install", "--no-cache-dir", "-q", *step], logf, beat) != 0:
            raise RuntimeError(f"pip install {' '.join(step)} failed: {_tail(logf)}")
    stamp.write_text(_spec_hash(env), encoding="utf-8")
    return py


class ExternalTranscriber:
    """Same face as worker.transcribe.Transcriber for the bench: transcribe(wav) -> .text, close()."""

    def __init__(self, python: Path, kind: str, model: str, language: str = "", log_file: Path | None = None,
                 beat=None, ready_timeout: int = 3600, memo_timeout: int = 300, cmd: list | None = None):
        self.memo_timeout = memo_timeout
        self._err = open(log_file, "a", encoding="utf-8", errors="replace") if log_file else subprocess.DEVNULL
        cmd = cmd or [str(python), str(RUNNER), "--kind", kind, "--model", model, "--language", language]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                  text=True, encoding="utf-8", errors="replace", env=_child_env(),
                                  creationflags=NO_WINDOW)
        self._q: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        t0 = time.monotonic()
        while True:                      # the first load may download the model (GBs): wait, beating
            try:
                msg = self._q.get(timeout=30)
                break
            except queue.Empty:
                if beat:
                    beat()
                if self.p.poll() is not None or time.monotonic() - t0 > ready_timeout:
                    self.close()
                    raise RuntimeError(f"{model} didn't start (see {log_file})")
        if msg is None or not msg.get("ready"):
            self.close()
            raise RuntimeError((msg or {}).get("error") or f"{model} stopped while loading (see {log_file})")
        self.device = msg.get("device", "")

    def _pump(self) -> None:
        for line in self.p.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    self._q.put(json.loads(line))
                except ValueError:
                    pass
        self._q.put(None)

    def transcribe(self, wav: Path):
        self.p.stdin.write(json.dumps({"wav": str(wav)}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        try:
            msg = self._q.get(timeout=self.memo_timeout)
        except queue.Empty:
            raise RuntimeError(f"no answer for {wav.name} in {self.memo_timeout} s") from None
        if msg is None:
            raise RuntimeError("the model process stopped")
        if "error" in msg:
            raise RuntimeError(msg["error"])
        return SimpleNamespace(text=msg.get("text", ""))

    def close(self) -> None:
        try:
            if self.p.stdin:
                self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:  # noqa: BLE001
            self.p.kill()
        if self._err not in (None, subprocess.DEVNULL):
            try:
                self._err.close()
            except Exception:  # noqa: BLE001
                pass
