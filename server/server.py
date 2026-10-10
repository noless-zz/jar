"""Jar server — receives memos from the pendant / phone app and stores them as
    data/memos/<YYYY-MM-DD>/<memo-id>.wav  + .json metadata
The worker (python -m worker) picks them up from there.

Token and data folder come from ../config.toml (env JAR_DEVICE_TOKEN / JAR_DATA_DIR override).
Run from the jar folder:   python -m uvicorn server.server:app --host 0.0.0.0 --port 8080
"""

import hashlib
import json
import logging
import os
import re
import time
import tomllib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from worker.family import Family, Person
from worker.taskstore import TaskError, TaskStore

ROOT = Path(__file__).resolve().parent.parent


def _raw_config() -> dict:
    for name in ("config.toml", "config.example.toml"):
        p = ROOT / name
        if p.exists():
            with open(p, "rb") as f:
                return tomllib.load(f)
    return {}


_raw = _raw_config()
_cfg = _raw.get("server", {})
_data = Path(os.environ.get("JAR_DATA_DIR") or _cfg.get("data_dir", "data")).expanduser()
DATA_DIR = (_data if _data.is_absolute() else ROOT / _data) / "memos"
TOKEN = os.environ.get("JAR_DEVICE_TOKEN") or _cfg.get("token", "")
if TOKEN == "CHANGE-ME":
    TOKEN = ""  # refuse every upload until setup.ps1 has generated a real token
MAX_BYTES = 64 * 1024 * 1024  # ~35 minutes of 16 kHz mono WAV
ID_RE = re.compile(r"^[0-9a-f]{16}$")
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

DATA_ROOT = DATA_DIR.parent
_notes = Path(_raw.get("notes", {}).get("dir", "notes")).expanduser()
NOTES_DIR = _notes if _notes.is_absolute() else ROOT / _notes
TIMEZONE = _raw.get("notes", {}).get("timezone", "Asia/Jerusalem")
FAMILY = Family.from_config(_raw.get("family", {}), TOKEN, DATA_ROOT)
TASKS = TaskStore(DATA_ROOT / "tasks.json", FAMILY, NOTES_DIR / "Tasks.md")

app = FastAPI(title="Jar server", version="0.3")


def _ollama_url() -> str:
    for name in ("config.toml", "config.example.toml"):
        p = ROOT / name
        if p.exists():
            with open(p, "rb") as f:
                return tomllib.load(f).get("llm", {}).get("ollama_url", "http://localhost:11434").rstrip("/")
    return "http://localhost:11434"




# Recent refused uploads, shown on the dashboard so a wrong token is visible instead of silent.
REJECTED: deque = deque(maxlen=20)
log = logging.getLogger("uvicorn.error")


def check_auth(authorization: str | None, request: Request | None = None, device: str = "") -> Person:
    """The family member this phone/pendant token belongs to, or 401."""
    if not TOKEN:
        raise HTTPException(500, "no device token configured on the server (config.toml [server] token)")
    sent = (authorization or "").removeprefix("Bearer ").strip()
    person = FAMILY.who(sent)
    if person is None:
        why = "no token sent" if not sent else f"unknown token ({len(sent)} chars; {FAMILY.admin.name}'s is {len(TOKEN)})"
        ip = request.client.host if request and request.client else "?"
        REJECTED.append({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "ip": ip, "device": device or "?", "reason": why})
        log.warning("refused upload from %s (%s): %s", ip, device or "?", why)
        raise HTTPException(401, "bad token")
    return person


def find_existing(memo_id: str) -> dict | None:
    for meta_path in DATA_DIR.glob(f"*/{memo_id}.json"):
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None


@app.get("/v1/health")
def health():
    return {"ok": True}


@app.get("/v1/auth")
def auth_check(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    """Lets the phone app's "Test connection" check the token, not just reachability."""
    p = check_auth(authorization, request, x_device_id)
    return {"ok": True, "person": p.public()}


@app.get("/v1/time")
def server_time():
    return {"epoch": int(time.time())}


@app.post("/v1/memos", status_code=201)
async def upload_memo(
    request: Request,
    authorization: str | None = Header(None),
    x_memo_id: str = Header(...),
    x_device_id: str = Header(...),
    x_sha256: str = Header(...),
    x_recorded_at: str = Header(""),
    x_duration_ms: int = Header(0),
):
    person = check_auth(authorization, request, x_device_id)
    if not ID_RE.match(x_memo_id):
        raise HTTPException(400, "bad memo id")
    if not DEVICE_RE.match(x_device_id):
        raise HTTPException(400, "bad device id")
    expected = x_sha256.lower()

    # Idempotent: a retry of a memo we already stored is acknowledged again.
    existing = find_existing(x_memo_id)
    if existing:
        if existing["sha256"] == expected:
            return JSONResponse(status_code=200, content={"id": x_memo_id, "sha256": expected, "status": "duplicate"})
        raise HTTPException(409, "memo id already stored with different content")

    received_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    day = (x_recorded_at or received_at)[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        day = received_at[:10]
    dest_dir = DATA_DIR / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".{x_memo_id}.part"

    h = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "memo too large")
                h.update(chunk)
                f.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    digest = h.hexdigest()
    if digest != expected:
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, f"checksum mismatch (got {digest})")

    os.replace(tmp, dest_dir / f"{x_memo_id}.wav")
    meta = {
        "id": x_memo_id,
        "device_id": x_device_id,
        "person": person.id,
        "recorded_at": x_recorded_at or None,
        "received_at": received_at,
        "duration_ms": x_duration_ms,
        "bytes": size,
        "sha256": digest,
        "status": "received",  # later steps: transcribed, routed, ...
    }
    (dest_dir / f"{x_memo_id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[jar] stored {x_memo_id} from {x_device_id}: {size} bytes, {x_duration_ms} ms")
    return {"id": x_memo_id, "sha256": digest, "status": "stored"}


# ---------------------------------------------------------------- family tasks (phone apps)

def _task_error(e: TaskError):
    raise HTTPException(e.status, str(e))


@app.get("/v1/me")
def me(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    return {"person": p.public(), "family": [x.public() for x in FAMILY.people.values()],
            "timezone": TIMEZONE, "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


@app.get("/v1/tasks")
def list_tasks(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    return TASKS.snapshot(p)


@app.post("/v1/tasks", status_code=201)
def new_task(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
             x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    who = FAMILY.get(body.get("assignee")) if body.get("assignee") else p
    if who is None:
        raise HTTPException(400, "no such family member")
    try:
        return TASKS.add(p, str(body.get("title", "")), who, body.get("due"), str(body.get("notes", "")))
    except TaskError as e:
        _task_error(e)


@app.post("/v1/tasks/{task_id}/{action}")
def task_action(task_id: str, action: str, request: Request, body: dict | None = Body(None),
                authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    body = body or {}
    try:
        return TASKS.act(p, task_id, action, body.get("until"), body)
    except TaskError as e:
        _task_error(e)


# ---------------------------------------------------------------- dashboard
# http://localhost:8080 on the PC; from the admin's phone over Tailscale after a one-time login link
# (the phone app's "Open dashboard"). At the end so REJECTED exists.
from .dashboard import LoginLinks, make_router, refile_memo  # noqa: E402


# ---------------------------------------------------------------- my memos (phone app)

def _mine(meta: dict, p: Person) -> bool:
    owner = meta.get("person") or FAMILY.admin.id      # memos from before families belong to the admin
    return owner == p.id


@app.get("/v1/memos")
def my_memos(request: Request, limit: int = 30, authorization: str | None = Header(None),
             x_device_id: str = Header("")):
    """This person's recent memos: what was said and what Jar did with it."""
    p = check_auth(authorization, request, x_device_id)
    out = []
    for meta_path in DATA_DIR.glob("*/*.json"):
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _mine(m, p):
            out.append({k: m.get(k) for k in ("id", "recorded_at", "duration_ms", "status", "transcript",
                                               "summary", "edited", "error")}
                       | {"actions": [a.get("summary", "") for a in (m.get("actions") or [])]})
    out.sort(key=lambda x: x.get("recorded_at") or "", reverse=True)
    return {"memos": out[:max(1, min(limit, 200))]}


@app.post("/v1/memos/{memo_id}/refile")
def refile_my_memo(memo_id: str, request: Request, body: dict | None = Body(None),
                   authorization: str | None = Header(None), x_device_id: str = Header("")):
    """File a memo again, optionally with a corrected transcript ({"transcript": "..."})."""
    p = check_auth(authorization, request, x_device_id)
    if not ID_RE.match(memo_id):
        raise HTTPException(400, "bad memo id")
    for meta_path in DATA_DIR.glob(f"*/{memo_id}.json"):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        if not _mine(m, p):
            break
        text = (body or {}).get("transcript")
        return refile_memo(meta_path, m, None if text is None else str(text))
    raise HTTPException(404, "no such memo")

LOGINS = LoginLinks(TOKEN)


@app.post("/v1/dashboard-login")
def dashboard_login(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    if not p.admin:
        raise HTTPException(403, "the dashboard is only for " + FAMILY.admin.name)
    return {"path": "login?n=" + LOGINS.issue()}


app.include_router(make_router(DATA_ROOT, _ollama_url(), REJECTED, TOKEN, int(_cfg.get("port", 8080)),
                               bool(_cfg.get("dashboard_tailscale", True)), FAMILY, LOGINS, TASKS))
