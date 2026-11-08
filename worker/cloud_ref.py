"""Cloud reference transcripts for the ASR bench (Gemini), so local models can be scored against something better
than another local model while there are few hand-corrected memos.

Opt-in and bench-only: production transcription never calls this. It runs only when a key file exists:
    data/secrets/gemini_key.txt      (or the GEMINI_API_KEY environment variable)
Use a key from a Google Cloud project WITH BILLING LINKED (paid tier). On the free tier Google may use the audio
and transcripts to improve its products and human reviewers may read them, which is wrong for the kids' memos.

Audio is sent inline in the request (no Files API, nothing stored as a file at Google). Each memo is sent once:
the result is cached in data/eval/asr/cloud/<memo id>.json (private, data/ is gitignored), so re-running the bench
costs nothing. Price at the time of writing: about $0.005 per audio minute, i.e. a few cents for all memos.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("jar.cloud_ref")

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-transcribe"
MAX_INLINE_BYTES = 18_000_000          # the request limit is 20 MB including base64 overhead
PROMPT = ("Transcribe this voice memo word for word, in the language spoken (usually Hebrew, sometimes with "
          "English words). Write only the transcript: no translation, no notes, no speaker labels.")


def load_key(data_dir: Path) -> str:
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    f = data_dir / "secrets" / "gemini_key.txt"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def vocabulary(cfg, family) -> list[str]:
    """The family's names plus the configured Whisper vocabulary: the words a generic model gets wrong."""
    words: list[str] = []
    for p in (getattr(family, "people", None) or {}).values():
        if getattr(p, "name", ""):
            words.append(p.name)
    for w in str(getattr(cfg, "vocabulary", "") or "").replace("\n", ",").split(","):
        w = w.strip()
        if w:
            words.append(w)
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:100]


def body_for(wav_bytes: bytes, model: str, vocab: list[str]) -> dict:
    audio = {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav_bytes).decode("ascii")}}
    if "transcribe" in model:
        cfg = {"languageCodes": ["he-IL", "en-US"]}
        if vocab:
            cfg["customVocabulary"] = vocab
        return {"contents": [{"parts": [audio]}], "generationConfig": {"audioTranscriptionConfig": cfg}}
    prompt = PROMPT + (" Words that may appear: " + ", ".join(vocab) + "." if vocab else "")
    return {"contents": [{"parts": [{"text": prompt}, audio]}], "generationConfig": {"temperature": 0}}


def text_from(resp: dict) -> str:
    """The transcript from a generateContent response: plain text parts, else an audioTranscription part
    (text/transcript field, or its words joined)."""
    out = []
    for cand in (resp.get("candidates") or [])[:1]:
        for p in (cand.get("content") or {}).get("parts") or []:
            if isinstance(p.get("text"), str):
                out.append(p["text"])
                continue
            at = p.get("audioTranscription") or {}
            t = at.get("text") or at.get("transcript")
            if isinstance(t, str):
                out.append(t)
            elif at.get("words"):
                out.append(" ".join(str(w.get("word") or w.get("text") or "") for w in at["words"]))
    return " ".join(s.strip() for s in out if s and s.strip())


class GeminiError(RuntimeError):
    pass


def transcribe(wav: Path, key: str, model: str = DEFAULT_MODEL, vocab: list[str] | None = None,
               post=None, raw_out: Path | None = None) -> str:
    """One memo → its transcript. post(url, headers, json) -> (status, dict) is injectable for tests."""
    data = wav.read_bytes()
    if len(data) > MAX_INLINE_BYTES:
        raise GeminiError(f"{wav.name} is too long to send inline ({len(data) // 1_000_000} MB)")
    if post is None:
        import requests

        def post(url, headers, body):
            r = requests.post(url, headers=headers, json=body, timeout=180)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"error": {"message": r.text[:300]}}
    url = API.format(model=model)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    body = body_for(data, model, vocab or [])
    for attempt in range(4):
        status, resp = post(url, headers, body)
        if status in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(5 * (attempt + 1))
            continue
        break
    if raw_out is not None:
        try:
            raw_out.write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    if status != 200:
        msg = ((resp or {}).get("error") or {}).get("message") or str(resp)[:300]
        raise GeminiError(f"HTTP {status}: {msg}")
    text = text_from(resp)
    if not text and not (resp.get("candidates")):
        raise GeminiError("no transcript in the response (see data/eval/asr/cloud/_last_response.json)")
    return text


def references(memos, cfg, family, out_dir: Path, model: str = DEFAULT_MODEL, post=None) -> dict:
    """Fill memo.cloud_ref for each memo, from the cache or by asking Gemini once. Returns a status dict for the
    report: {"model", "sent", "cached", "failed", "error"}."""
    status = {"model": model, "sent": 0, "cached": 0, "failed": 0, "error": ""}
    key = load_key(cfg.data_dir)
    if not key:
        status["error"] = "no key (data/secrets/gemini_key.txt)"
        return status
    cache = out_dir / "cloud"
    cache.mkdir(parents=True, exist_ok=True)
    vocab = vocabulary(cfg, family)
    for mm in memos:
        f = cache / f"{mm.id}.json"
        try:
            hit = json.loads(f.read_text(encoding="utf-8"))
            if hit.get("model") == model and isinstance(hit.get("text"), str):
                mm.cloud_ref = hit["text"]
                status["cached"] += 1
                continue
        except (OSError, ValueError):
            pass
        try:
            text = transcribe(mm.wav, key, model, vocab, post=post, raw_out=cache / "_last_response.json")
        except Exception as e:  # noqa: BLE001
            status["failed"] += 1
            status["error"] = f"{type(e).__name__}: {e}"
            log.warning("Gemini reference failed for %s: %s", mm.id, e)
            if "HTTP 4" in str(e) and "429" not in str(e):
                break                    # bad key / model / request: every memo would fail the same way
            continue
        mm.cloud_ref = text
        status["sent"] += 1
        f.write_text(json.dumps({"model": model, "text": text,
                                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                ensure_ascii=False), encoding="utf-8")
    return status
