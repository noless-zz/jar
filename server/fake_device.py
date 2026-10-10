"""Pretend to be the pendant: upload a WAV to the Jar server.

Usage (from the jar folder):
    python server/fake_device.py [--wav file.wav]          token + port come from config.toml
    python server/fake_device.py --url http://host:8080 --token <token> [--wav file.wav]

Without --wav it generates a 2-second 440 Hz tone, so you can test the server
before the hardware arrives. Uses only the Python standard library.
"""

import argparse
import hashlib
import io
import math
import secrets
import struct
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone


def tone_wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))
        )
        w.writeframes(frames)
    return buf.getvalue()


def upload(url, token, data, memo_id=None, sha=None, device="fake-01"):
    memo_id = memo_id or secrets.token_hex(8)
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/memos",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "audio/wav",
            "X-Memo-Id": memo_id,
            "X-Device-Id": device,
            "X-Recorded-At": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "X-Duration-Ms": str(int((len(data) - 44) / 32)),
            "X-Sha256": sha or hashlib.sha256(data).hexdigest(),
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode(), memo_id
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), memo_id


def _from_config():
    """Default token/port from ../config.toml so the VS Code task needs no arguments."""
    import pathlib
    try:
        import tomllib
        root = pathlib.Path(__file__).resolve().parent.parent
        for name in ("config.toml", "config.example.toml"):
            if (root / name).exists():
                with open(root / name, "rb") as f:
                    s = tomllib.load(f).get("server", {})
                return s.get("token"), f"http://localhost:{s.get('port', 8080)}"
    except Exception:  # noqa: BLE001
        pass
    return None, "http://localhost:8080"


if __name__ == "__main__":
    cfg_token, cfg_url = _from_config()
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=cfg_url)
    p.add_argument("--token", default=cfg_token)
    p.add_argument("--wav")
    p.add_argument("--device", default="fake-01")
    a = p.parse_args()
    if not a.token:
        p.error("no token: pass --token or set [server] token in config.toml")
    data = open(a.wav, "rb").read() if a.wav else tone_wav()
    status, body, memo_id = upload(a.url, a.token, data, device=a.device)
    print(status, body)
