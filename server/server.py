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
from fastapi.responses import HTMLResponse, JSONResponse

from worker import effort, memo_items
from worker.family import Family, Person
from worker.points import PointsConfig, PointsStore
from worker.shopping import ShoppingError, ShoppingStore
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
FAMILY = Family.from_config(_raw.get("family", {}), TOKEN, DATA_ROOT, _raw.get("contacts", {}))
POINTS = PointsStore(DATA_ROOT / "points.json", FAMILY, TIMEZONE, PointsConfig.from_raw(_raw.get("points")))
TASKS = TaskStore(DATA_ROOT / "tasks.json", FAMILY, NOTES_DIR / "Tasks.md", POINTS)
SHOPPING = ShoppingStore(DATA_ROOT / "shopping.json", FAMILY,
                         lambda: next((a.get("owner") for a in TASKS.areas() if a.get("id") == "food"), None))

app = FastAPI(title="Jar server", version="0.3")


@app.middleware("http")
async def public_only_v1(request: Request, call_next):
    """Requests from the internet (Tailscale Funnel) may only use the phone API under /v1.
    The dashboard, pairing page and memo audio stay on this PC and the tailnet."""
    if request.headers.get("tailscale-funnel-request") and not request.url.path.startswith("/v1/"):
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return await call_next(request)


# Wrong tokens per address: after 20 in 10 minutes, that address waits (stops token guessing).
_FAILS: dict[str, deque] = {}


def _remote_ip(request: Request | None) -> str:
    if request is None:
        return "?"
    host = request.client.host if request.client else "?"
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd and host in ("127.0.0.1", "::1"):
        # Tailscale on this PC appends the real address last; earlier entries are whatever the sender wrote.
        return fwd.split(",")[-1].strip() or host
    return host


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


# Home Assistant's token (worker/family.py, "home") reaches only these: the wall panel's tasks, ticks and the
# leaderboard, and /v1/home (docs/HOME_ASSISTANT.md).
HOME_PATHS = re.compile(r"^/v1/(auth|me|time|points|tasks|tasks/[0-9a-f]+/(done|reopen)|home(/link)?"
                        r"|shopping|shopping/[0-9a-f]+/(bought|unbought))$")
HOME_LINK = FAMILY.tokens_path.parent / "home_assistant.json"


def check_auth(authorization: str | None, request: Request | None = None, device: str = "") -> Person:
    """The family member this phone/pendant token belongs to, or 401."""
    if not TOKEN:
        raise HTTPException(500, "no device token configured on the server (config.toml [server] token)")
    sent = (authorization or "").removeprefix("Bearer ").strip()
    ip = _remote_ip(request)
    fails = _FAILS.setdefault(ip, deque(maxlen=50))
    while fails and fails[0] < time.time() - 600:
        fails.popleft()
    if len(fails) >= 20:
        raise HTTPException(429, "too many wrong tokens from this address; try again in a few minutes")
    person = FAMILY.who(sent)
    if person is None:
        fails.append(time.time())
        why = "no token sent" if not sent else f"unknown token ({len(sent)} chars; {FAMILY.admin.name}'s is {len(TOKEN)})"
        REJECTED.append({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "ip": ip, "device": device or "?", "reason": why})
        log.warning("refused upload from %s (%s): %s", ip, device or "?", why)
        raise HTTPException(401, "bad token")
    if person.is_home and (request is None or not HOME_PATHS.match(request.url.path)):
        raise HTTPException(403, "Home Assistant's token only reaches the task list")
    return person


def find_existing(memo_id: str) -> dict | None:
    for meta_path in DATA_DIR.glob(f"*/{memo_id}.json"):
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None


@app.get("/v1/health")
def health(request: Request):
    # "via": lets the supervisor's Funnel watch (server/anywhere.py) tell a real internet request from one
    # Tailscale routed straight over the tailnet.
    return {"ok": True, "via": "funnel" if request.headers.get("tailscale-funnel-request") else "direct"}


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
        # e.g. a Hebrew name typed in the app: keep the safe part rather than refuse the memo
        x_device_id = re.sub(r"[^A-Za-z0-9_-]", "", x_device_id)[:32] or "phone"
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


_URLS: dict = {"at": 0.0, "urls": []}


def current_urls(request: Request | None = None) -> list[str]:
    """Every address phones can use right now (cached 5 min; 30 s after a failure): lets the app learn a
    new one, e.g. the public Funnel address, without pairing again. A request that came in over the
    internet adds the public address it used, so links built for it always work outside."""
    if time.time() - _URLS["at"] > (300 if _URLS["urls"] else 30):
        try:
            from . import pairing
            _URLS["urls"] = pairing.pairing_urls(pairing.discover(), int(_cfg.get("port", 8080)))
        except Exception:  # noqa: BLE001
            log.exception("couldn't list this PC's addresses")
        _URLS["at"] = time.time()
    urls = list(_URLS["urls"])
    if request is not None and request.headers.get("tailscale-funnel-request"):
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        public = "https://" + host.split(",")[0].strip() if host else ""
        if public and public not in urls:
            urls.insert(min(2, len(urls)), public)
    return urls


@app.get("/v1/me")
def me(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    return {"person": p.public(), "family": [x.public() for x in FAMILY.people.values()],
            "timezone": TIMEZONE, "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "urls": current_urls(request)}


@app.post("/v1/invite")
def invite(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
           x_device_id: str = Header("")):
    """The admin's phone: a ready "install Jar and join" WhatsApp message for one family member,
    with their own link. Works from anywhere, so nobody has to stand at the PC."""
    from worker import join
    from . import pairing
    p = check_auth(authorization, request, x_device_id)
    if not p.admin:
        raise HTTPException(403, "only " + FAMILY.admin.name + " can invite")
    who = FAMILY.get(str(body.get("person", ""))) or FAMILY.resolve(str(body.get("person", "")))
    if who is None:
        raise HTTPException(400, "no such family member")
    urls = current_urls(request)
    if not urls:
        raise HTTPException(503, "the PC can't tell its own address right now; try again in a minute")
    link = pairing.pairing_link(FAMILY.token_for(who.id), urls)
    page = join.join_url(urls, link)
    lang = str(body.get("language", "he"))
    _, phone = FAMILY.phone_for(who.name)
    log.info("invite for %s prepared on %s's phone", who.id, p.id)
    return {"to": who.name, "phone": phone, "public": bool(page),
            "text": join.message(who.name, join.DOWNLOAD, link, page, lang)}


# ---- watchdog: if the supervisor stops (frozen or crashed), start a new one. It takes over: stops the old
# supervisor and its server and worker (this process included) and starts everything fresh.

def supervisor_stale(data: Path, now: float, limit: float = 180) -> bool:
    ages = []
    for f in ("supervisor.alive", "supervisor.json"):
        try:
            ages.append(now - (data / f).stat().st_mtime)
        except OSError:
            pass
    return bool(ages) and min(ages) > limit


def _watchdog() -> None:
    import sys
    import threading

    from . import supervise
    started = time.time()

    def loop():
        launched = 0.0
        while True:
            time.sleep(60)
            now = time.time()
            if now - started < 300 or now - launched < 900:
                continue                      # give a fresh start time; never relaunch in a loop
            if supervisor_stale(DATA_ROOT, now):
                log.warning("supervisor silent for over 3 minutes: starting a new one")
                launched = now
                try:
                    supervise.start_detached(sys.executable)
                except OSError as e:
                    log.error("couldn't start a supervisor: %s", e)
    threading.Thread(target=loop, daemon=True, name="watchdog").start()


@app.on_event("startup")
def _start_watchdog() -> None:
    if os.name == "nt" and not os.environ.get("JAR_NO_WATCHDOG") and _raw.get("supervisor", {}).get("watchdog", True):
        _watchdog()


# ---- the admin's phone looks after the PC: status, logs, update from GitHub, restart, AI test

LOGS = {"worker": "worker.log", "server": "server.log", "supervisor": "supervisor.log"}


def _admin(authorization: str | None, request: Request, device: str) -> Person:
    p = check_auth(authorization, request, device)
    if not p.admin:
        raise HTTPException(403, "only " + FAMILY.admin.name + " can do this")
    return p


def _json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/v1/admin/status")
def admin_status(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    _admin(authorization, request, x_device_id)
    now = time.time()
    sup, work = _json_file(DATA_ROOT / "supervisor.json"), _json_file(DATA_ROOT / "worker.json")
    counts: dict[str, int] = {}
    for meta in sorted(DATA_DIR.glob("*/*.json"))[-200:]:
        st = _json_file(meta).get("status", "?")
        counts[st] = counts.get(st, 0) + 1
    ev = _json_file(DATA_ROOT / "eval" / "report.json")
    return {
        "supervisor": {**{k: sup.get(k) for k in ("code", "update", "update_mode", "restarts", "last_reason",
                                                    "last_command", "auto_restart", "github_pull")},
                       "alive": bool(sup) and now - sup.get("epoch", 0) < 30,
                       "checked_ago": int(now - sup["checked_epoch"]) if sup.get("checked_epoch") else None},
        "worker": {"doing": work.get("doing"), "llm": work.get("llm"), "whisper": work.get("whisper"),
                   "alive": bool(work) and now - work.get("epoch", 0) < 120},
        "memos": counts,
        "eval": {k: ev.get(k) for k in ("passed", "total", "at", "model")} if ev else None,
        "eval_running": (DATA_ROOT / "eval" / "run").exists(),
        "urls": current_urls(),
        "rejected": list(REJECTED)[-5:],
    }


@app.post("/v1/admin/command")
def admin_command(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                  x_device_id: str = Header("")):
    p = _admin(authorization, request, x_device_id)
    cmd = str(body.get("cmd", ""))
    if cmd in ("update", "restart"):
        (DATA_ROOT / "supervisor-cmd.json").write_text(json.dumps({"cmd": cmd, "by": p.id, "at": time.time()}),
                                                       encoding="utf-8")
        return {"ok": True, "message": "update requested: the PC checks GitHub within a few seconds"
                if cmd == "update" else "restart requested: back in about 20 seconds"}
    if cmd == "eval":
        (DATA_ROOT / "eval").mkdir(parents=True, exist_ok=True)
        (DATA_ROOT / "eval" / "run").write_text(str(max(1, min(3, int(body.get("repeats", 1))))), encoding="utf-8")
        return {"ok": True, "message": "AI test queued: runs when no memo is waiting (a few minutes)"}
    raise HTTPException(400, "cmd must be update, restart or eval")


@app.get("/v1/admin/log")
def admin_log(request: Request, name: str = "worker", lines: int = 120, authorization: str | None = Header(None),
              x_device_id: str = Header("")):
    _admin(authorization, request, x_device_id)
    if name == "eval":
        path = DATA_ROOT / "eval" / "report.md"
    elif name in LOGS:
        path = DATA_ROOT / "logs" / LOGS[name]
    else:
        raise HTTPException(400, "name must be one of " + ", ".join([*LOGS, "eval"]))
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return {"name": name, "text": "(nothing yet)"}
    keep = text.splitlines()[-max(10, min(lines, 1000)):] if name != "eval" else text.splitlines()
    return {"name": name, "text": "\n".join(keep)}


@app.get("/v1/join", response_class=HTMLResponse)
def join_page():
    """Opened from the WhatsApp invite; the pairing is in the #fragment, which browsers never send."""
    from worker import join
    return HTMLResponse(join.page(), headers={"Cache-Control": "no-store"})


@app.get("/v1/tasks")
def list_tasks(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    try:
        TASKS.roll()                       # today's recurring tasks, even when the worker is busy or down
    except Exception:  # noqa: BLE001 — the list must still load
        log.exception("rolling recurring tasks failed")
    return TASKS.snapshot(p)


@app.post("/v1/tasks", status_code=201)
def new_task(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
             x_device_id: str = Header("")):
    """{"title", "due", "notes", "assignee": id} or, for a shared task, {"assignees": [ids], "mode": "any"|"all"}.
    Recurring: + "repeat": {"rule": "weekly:sun,wed", "time": "20:00", "rotate": false, "after_done": false}
    (returns the first occurrence, with "series"). A Jar idea: {"kind": "idea", "title", "notes"}."""
    p = check_auth(authorization, request, x_device_id)
    try:
        ids = body.get("assignees") or ([body["assignee"]] if body.get("assignee") else [])
        if p.is_home and (body.get("kind") == "idea" or not ids):
            raise HTTPException(400, "Home Assistant's tasks need \"assignee\" or \"assignees\"")
        if body.get("kind") == "idea":
            return TASKS.add_idea(p, str(body.get("title", "")), str(body.get("notes", "")))
        who = TASKS.resolve_people(ids) or [p]
        rep = body.get("repeat")
        if isinstance(rep, str):
            rep = {"rule": rep}
        if isinstance(rep, dict) and rep.get("rule"):
            return TASKS.add_series(p, str(body.get("title", "")), who, str(rep["rule"]), str(rep.get("time") or ""),
                                    str(body.get("notes", "")), mode=str(body.get("mode") or "any"),
                                    rotate=bool(rep.get("rotate")), after_done=bool(rep.get("after_done")))
        return TASKS.add(p, str(body.get("title", "")), who, body.get("due"), str(body.get("notes", "")),
                         mode=str(body.get("mode") or "any"))
    except TaskError as e:
        _task_error(e)


@app.post("/v1/tasks/{task_id}/repeat")
def task_repeat(task_id: str, request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                x_device_id: str = Header("")):
    """Make an existing task repeat: {"rule": "weekly:sun,wed", "time": "20:00", "rotate": false}."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.make_recurring(p, task_id, str(body.get("rule") or ""), str(body.get("time") or ""),
                                    bool(body.get("rotate")))
    except TaskError as e:
        _task_error(e)


@app.post("/v1/settings")
def family_settings(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                    x_device_id: str = Header("")):
    """A parent changes the family settings: {"keep_done_days": 0 (forever) | 30 | 90 | 180 | 365}."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.set_settings(p, body)
    except TaskError as e:
        _task_error(e)


@app.post("/v1/areas", status_code=201)
def new_area(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
             x_device_id: str = Header("")):
    """A parent adds an area of responsibility: {"name", "emoji", "owner", "description", "keywords": [...]}."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.area_act(p, "add", fields=body)
    except TaskError as e:
        _task_error(e)


@app.post("/v1/areas/{area_id}/{action}")
def area_action(area_id: str, action: str, request: Request, body: dict | None = Body(None),
                authorization: str | None = Header(None), x_device_id: str = Header("")):
    """edit ({"name", "emoji", "owner", "description", "keywords"}; a new owner takes over the area's recurring
    tasks) | delete. Parents only."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.area_act(p, action, area_id, body or {})
    except TaskError as e:
        _task_error(e)


@app.post("/v1/series/{series_id}/{action}")
def series_action(series_id: str, action: str, request: Request, body: dict | None = Body(None),
                  authorization: str | None = Header(None), x_device_id: str = Header("")):
    """A recurring task as a whole: stop | pause | resume | edit ({"title", "notes", "rule", "time",
    "owners", "mode", "rotate"})."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.series_act(p, series_id, action, body or {})
    except TaskError as e:
        _task_error(e)


# Notes and questions on a task (before the generic /{action} route, which would catch "notes").

@app.post("/v1/tasks/{task_id}/notes")
def task_note(task_id: str, request: Request, body: dict = Body(...), authorization: str | None = Header(None),
              x_device_id: str = Header("")):
    """{"text": "...", "ask": true} — ask=true sends it as a question to the other side."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.comment(p, task_id, str(body.get("text", "")), bool(body.get("ask")))
    except TaskError as e:
        _task_error(e)


@app.patch("/v1/tasks/{task_id}/notes/{note_id}")
def task_note_edit(task_id: str, note_id: int, request: Request, body: dict = Body(...),
                   authorization: str | None = Header(None), x_device_id: str = Header("")):
    """Change your own note; an empty text removes it."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.edit_comment(p, task_id, note_id, str(body.get("text", "")))
    except TaskError as e:
        _task_error(e)


@app.post("/v1/tasks/{task_id}/suggest")
def task_suggest(task_id: str, request: Request, authorization: str | None = Header(None),
                 x_device_id: str = Header("")):
    """Three short replies the local AI suggests for this person's next note (nothing is sent)."""
    from worker import replies
    p = check_auth(authorization, request, x_device_id)
    t = next((x for x in TASKS.snapshot(p)["tasks"] if x["id"] == task_id), None)
    if t is None:
        raise HTTPException(404, "no such task")
    llm = _raw.get("llm", {})
    names = {x.id: x.name for x in FAMILY.people.values()}
    try:
        return {"replies": replies.suggest(_ollama_url(), llm.get("model", "qwen3.5:9b"), t, p.id, names,
                                           num_ctx=int(llm.get("num_ctx", 12288)),
                                           keep_alive=str(llm.get("keep_alive", "10m")))}
    except replies.SuggestError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/v1/tasks/{task_id}/points")
def task_points(task_id: str, request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                x_device_id: str = Header("")):
    """A parent sets what a task is worth: {"effort": 1-10} and/or {"no_coins": true}. The effort is
    remembered for that chore; a task that is already done is paid again at the new rate."""
    p = check_auth(authorization, request, x_device_id)
    try:
        return TASKS.set_points(p, task_id, body.get("effort"), body.get("no_coins"))
    except TaskError as e:
        _task_error(e)


@app.post("/v1/tasks/{task_id}/{action}")
def task_action(task_id: str, action: str, request: Request, body: dict | None = Body(None),
                authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    body = body or {}
    try:
        if p.is_home:                       # the wall panel ticks it for one of its people: {"as": "alona"}
            return TASKS.act_for(task_id, action, str(body.get("as") or ""), body)
        return TASKS.act(p, task_id, action, body.get("until"), body)
    except TaskError as e:
        _task_error(e)


# ---------------------------------------------------------------- shopping lists (worker/shopping.py)

@app.get("/v1/shopping")
def shopping_list(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    """Everyone's shopping lists: {"items": [...], "default_buyer"}."""
    p = check_auth(authorization, request, x_device_id)
    return SHOPPING.snapshot(p)


@app.post("/v1/shopping", status_code=201)
def shopping_add(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                 x_device_id: str = Header("")):
    """{"items": ["חלב", "אפוקסי"] (or "title"), "buyer": id (empty = whoever does the shopping), "notes"}."""
    p = check_auth(authorization, request, x_device_id)
    titles = body.get("items") or ([body["title"]] if body.get("title") else [])
    buyer = FAMILY.get(str(body.get("buyer") or "")) if body.get("buyer") else None
    if body.get("buyer") and buyer is None:
        raise HTTPException(400, "no such family member: " + str(body.get("buyer")))
    try:
        return {"items": SHOPPING.add(p, [str(t) for t in titles] if isinstance(titles, list) else [str(titles)],
                                      buyer, str(body.get("notes") or ""))}
    except ShoppingError as e:
        raise HTTPException(e.status, str(e)) from None


@app.post("/v1/shopping/{item_id}/{action}")
def shopping_act(item_id: str, action: str, request: Request, body: dict | None = Body(None),
                 authorization: str | None = Header(None), x_device_id: str = Header("")):
    """bought | unbought | delete | edit {"title", "notes", "buyer"}. Home Assistant: bought/unbought, {"as"}."""
    p = check_auth(authorization, request, x_device_id)
    body = body or {}
    try:
        if p.is_home:
            return SHOPPING.act_for(item_id, action, str(body.get("as") or ""))
        return SHOPPING.act(p, item_id, action, body)
    except ShoppingError as e:
        raise HTTPException(e.status, str(e)) from None


# ---------------------------------------------------------------- Home Assistant (docs/HOME_ASSISTANT.md)

def home_link() -> dict:
    """{"url", "token"} Home Assistant gave Jar for controlling the house, or {}."""
    try:
        return json.loads(HOME_LINK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/v1/home")
def home_status(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    if not (p.is_home or p.admin):
        raise HTTPException(403, "only " + FAMILY.admin.name)
    link = home_link()
    return {"paired": FAMILY.home_paired(), "linked": bool(link.get("token")), "url": link.get("url", "")}


@app.post("/v1/home/link")
def home_set_link(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
                  x_device_id: str = Header("")):
    """Jar's Home Assistant integration hands Jar its address and a token of a Home Assistant user made for
    Jar, so memos can switch lights, the AC and the boiler (worker/home.py). {"url": "", "token": ""} unlinks."""
    p = check_auth(authorization, request, x_device_id)
    if not p.is_home:
        raise HTTPException(403, "only Home Assistant sends this")
    url, tok = str(body.get("url", "")).strip().rstrip("/"), str(body.get("token", "")).strip()
    if not url and not tok:
        HOME_LINK.unlink(missing_ok=True)
        return {"linked": False}
    if not re.match(r"^https?://[^\s/]+(:\d+)?(/\S*)?$", url) or len(tok) < 20 or any(c.isspace() for c in tok):
        raise HTTPException(400, "need {\"url\": \"https://…\", \"token\": \"…\"}")
    HOME_LINK.parent.mkdir(parents=True, exist_ok=True)
    tmp = HOME_LINK.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "token": tok, "linked_at": int(time.time())}, indent=2), encoding="utf-8")
    os.replace(tmp, HOME_LINK)
    log.info("Home Assistant linked: %s", url)
    return {"linked": True, "url": url}


# ---------------------------------------------------------------- points (docs/POINTS.md)

@app.get("/v1/points")
def points_board(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    """The leaderboard: this week (Sunday to Saturday) and all time, streaks, everyone's ledger as this
    person may see it, recent lesson notes, and the week's winner and most improved."""
    p = check_auth(authorization, request, x_device_id)
    return POINTS.board(p)


@app.post("/v1/lessons", status_code=201)
def new_lesson(request: Request, body: dict = Body(...), authorization: str | None = Header(None),
               x_device_id: str = Header("")):
    """A child's lesson: {"title": "…", "learned": "what I learned"}. The note earns the coins; the local
    AI rates the effort in it from 1 to 5 (by length when the AI is away). Parents see it on the family list."""
    p = check_auth(authorization, request, x_device_id)
    if p.is_parent:
        raise HTTPException(403, "lesson notes are for the kids")
    note = str(body.get("learned", "")).strip()
    if len(note) < 12:
        raise HTTPException(400, "write a sentence about what you learned")
    llm = _raw.get("llm", {})
    rated, by = effort.rate_lesson(_ollama_url(), llm.get("model", "qwen3.5:9b"), str(body.get("title", "")), note,
                                   int(llm.get("num_ctx", 12288)), str(llm.get("keep_alive", "10m")))
    try:
        return TASKS.add_lesson(p, str(body.get("title", "")), note, rated, by)
    except TaskError as e:
        _task_error(e)


@app.post("/v1/points/work-day")
def log_work_day(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    """A parent logs today's work day: the fixed base from [points] work_day_coins, once a day."""
    p = check_auth(authorization, request, x_device_id)
    if not p.is_parent:
        raise HTTPException(403, "work days are for the grown-ups")
    award = POINTS.pay_work_day(p.id)
    if award is None:
        raise HTTPException(409, "today's work day is already logged")
    return {"award": award}


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
        if _mine(m, p) and m.get("status") != "deleting":
            acts = m.get("actions") or []
            out.append({k: m.get(k) for k in ("id", "recorded_at", "duration_ms", "status", "transcript",
                                               "summary", "edited", "error")}
                       | {"actions": [a.get("summary", "") if isinstance(a, dict) else str(a) for a in acts],
                          "items": memo_items.items(acts)})
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

@app.post("/v1/memos/{memo_id}/items/{index}/delete")
def delete_memo_item(memo_id: str, index: int, request: Request, authorization: str | None = Header(None),
                     x_device_id: str = Header("")):
    """Take back one thing a memo made (worker/memo_items.py): a task, a note, an event or a draft.
    Tasks and files go at once; calendar and email are removed by the worker within a minute."""
    p = check_auth(authorization, request, x_device_id)
    if not ID_RE.match(memo_id):
        raise HTTPException(400, "bad memo id")
    for meta_path in DATA_DIR.glob(f"*/{memo_id}.json"):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        if not _mine(m, p):
            break
        if m.get("status") != "done":
            raise HTTPException(409, "Jar is still filing this memo: try again in a minute")
        acts = m.get("actions") or []
        if not 0 <= index < len(acts) or not isinstance(acts[index], dict):
            raise HTTPException(404, "no such item")
        a = acts[index]
        k = memo_items.kind(a)
        if k is None:
            raise HTTPException(409, "this one changed something that was already there: undo it in the app instead")
        if a.get("removed"):
            return {"items": memo_items.items(acts)}
        if k == "task":
            try:
                TASKS.act(p, a["task_id"], "delete")
            except TaskError as e:
                if e.status != 404:            # 404: already gone, which is what was asked
                    _task_error(e)
            memo_items.mark(m, index, True)
        elif k == "file":
            try:
                memo_items.remove_file(memo_items.notes_root(NOTES_DIR, p, p.admin), a.get("file", ""))
            except (OSError, ValueError) as e:
                raise HTTPException(500, f"couldn't delete the file: {e}")
            memo_items.mark(m, index, True)
        else:
            a["removing"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            memo_items.queue(DATA_ROOT / "deletes", memo_id, index)
        memo_items.save(meta_path, m)
        log.info("%s deleted “%s” from memo %s", p.name, a.get("summary", ""), memo_id)
        return {"items": memo_items.items(m.get("actions") or [])}
    raise HTTPException(404, "no such memo")


@app.post("/v1/memos/{memo_id}/delete")
def delete_memo(memo_id: str, request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    """Delete a memo and everything it made: its tasks (done ones too, coins taken back), recurring tasks,
    shopping items, notes and files at once; calendar events, email drafts, its lines in the logs and the
    recording itself by the worker within a minute. Works for a memo with no speech too."""
    p = check_auth(authorization, request, x_device_id)
    if not ID_RE.match(memo_id):
        raise HTTPException(400, "bad memo id")
    for meta_path in DATA_DIR.glob(f"*/{memo_id}.json"):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        if not _mine(m, p):
            break
        if m.get("status") in ("transcribing", "filing"):
            raise HTTPException(409, "Jar is filing this memo right now: try again in a minute")
        tasks = TASKS.delete_memo(p, memo_id)
        shopping = SHOPPING.forget_memo(memo_id)
        root = memo_items.notes_root(NOTES_DIR, p, p.admin)
        for a in m.get("actions") or []:
            if isinstance(a, dict) and memo_items.kind(a) == "file" and not a.get("removed"):
                try:
                    memo_items.remove_file(root, a.get("file", ""))
                except (OSError, ValueError) as e:
                    log.warning("memo %s: couldn't delete %s: %s", memo_id, a.get("file"), e)
        m["status"] = "deleting"
        memo_items.save(meta_path, m)
        memo_items.queue_all(DATA_ROOT / "deletes", memo_id)
        log.info("%s deleted memo %s (%d task(s), %d shopping item(s))", p.name, memo_id, tasks, shopping)
        return {"deleted": memo_id, "tasks": tasks, "shopping": shopping}
    raise HTTPException(404, "no such memo")


LOGINS = LoginLinks(TOKEN)


@app.post("/v1/dashboard-login")
def dashboard_login(request: Request, authorization: str | None = Header(None), x_device_id: str = Header("")):
    p = check_auth(authorization, request, x_device_id)
    if not p.admin:
        raise HTTPException(403, "the dashboard is only for " + FAMILY.admin.name)
    if request.headers.get("tailscale-funnel-request"):
        # Away from home the public address serves only /v1, so the dashboard itself can't open: the same one-time
        # code opens the Home Assistant link page instead (docs/HOME_ASSISTANT.md).
        return {"path": "v1/home/pair?n=" + LOGINS.issue()}
    return {"path": "login?n=" + LOGINS.issue()}


@app.get("/v1/home/pair", response_class=HTMLResponse)
def home_pair_page(n: str = ""):
    """The Home Assistant link, opened once with a dashboard login code from the admin's phone."""
    from .dashboard import home_assistant_html
    if not LOGINS.redeem(n):
        raise HTTPException(403, "this link was used or expired; tap Open dashboard in the app again")
    return HTMLResponse(home_assistant_html(FAMILY, int(_cfg.get("port", 8080)), away=True),
                        headers={"Cache-Control": "no-store"})


app.include_router(make_router(DATA_ROOT, _ollama_url(), REJECTED, TOKEN, int(_cfg.get("port", 8080)),
                               bool(_cfg.get("dashboard_tailscale", True)), FAMILY, LOGINS, TASKS))
