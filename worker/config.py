"""Loads config.toml (falling back to config.example.toml) into simple objects."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    root: Path
    data_dir: Path
    notes_dir: Path
    timezone: str
    whisper_model: str
    whisper_device: str
    whisper_compute: str
    whisper_language: str
    vocabulary: str
    ollama_url: str
    llm_model: str
    temperature: float
    keep_alive: str
    max_rounds: int
    poll_seconds: float
    max_attempts: int
    accounts: dict           # role -> provider, e.g. {"personal": "outlook", "school": "google"}
    outlook_client_id: str
    google_client_secrets: Path
    google_calendar_id: str
    about: str = ""          # [llm] about: who the owner is, one sentence for the model
    think: bool = True       # [llm] think: reason before calling tools (slower, better)
    num_ctx: int = 8192      # [llm] num_ctx: context window; must hold instructions + tools + memo
    port: int = 8080         # [server] port, for pairing links in messages
    token: str = ""          # [server] token = the admin's phone/pendant token
    family: dict | None = None   # [family] table (see worker/family.py)
    contacts: dict | None = None  # [contacts] name = "+972…" for WhatsApp drafts
    points: dict | None = None    # [points] table (see worker/points.py)


def _path(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else root / p


def load(path: Path | None = None, root: Path = ROOT) -> Config:
    if path is None:
        path = root / "config.toml"
        if not path.exists():
            path = root / "config.example.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    s, t, l, n, w = (raw.get(k, {}) for k in ("server", "transcribe", "llm", "notes", "worker"))
    acc, ol, gg = (raw.get(k, {}) for k in ("accounts", "outlook", "google"))
    return Config(
        root=root,
        data_dir=_path(root, s.get("data_dir", "data")),
        notes_dir=_path(root, n.get("dir", "notes")),
        timezone=n.get("timezone", "Asia/Jerusalem"),
        whisper_model=t.get("model", "large-v3-turbo"),
        whisper_device=t.get("device", "auto"),
        whisper_compute=t.get("compute_type", "auto"),
        whisper_language=t.get("language", ""),
        vocabulary=t.get("vocabulary", ""),
        ollama_url=l.get("ollama_url", "http://localhost:11434").rstrip("/"),
        llm_model=l.get("model", "qwen3.5:9b"),
        temperature=float(l.get("temperature", 0.2)),
        keep_alive=str(l.get("keep_alive", "10m")),
        max_rounds=max(6, int(l.get("max_rounds", 6))),
        poll_seconds=float(w.get("poll_seconds", 5)),
        max_attempts=int(w.get("max_attempts", 3)),
        accounts={k: str(v).lower() for k, v in acc.items()},
        outlook_client_id=str(ol.get("client_id", "")).strip(),
        google_client_secrets=_path(root, gg.get("client_secrets", "data/secrets/google_client.json")),
        google_calendar_id=gg.get("calendar_id", "primary"),
        about=str(l.get("about", "")),
        think=bool(l.get("think", True)),
        num_ctx=int(l.get("num_ctx", 8192)),
        port=int(s.get("port", 8080)),
        token=str(s.get("token", "")),
        family=raw.get("family", {}),
        contacts=raw.get("contacts", {}),
        points=raw.get("points", {}),
    )
