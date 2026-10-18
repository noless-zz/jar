"""Local dashboard: http://localhost:8080 (open it in VS Code with "Jar: Dashboard").

Shows recent memos (transcript, what was filed, errors), the worker's heartbeat and
Ollama. Lets you play a memo and send it back through the worker.
Answers requests from this PC. Over Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48; turn off with
[server] dashboard_tailscale = false) it also needs the admin's login cookie, which the admin's phone
app sets with a one-time link ("Open dashboard"), because the family's phones share the tailnet.
Everyone else, including the home LAN, gets a 403: transcripts are private.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}


TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def allowed(host: str | None, tailscale: bool) -> bool:
    if not host:
        return False
    if host in LOCAL:
        return True
    if not tailscale:
        return False
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in net for net in TAILNET if ip.version == net.version)


COOKIE = "jar_admin"
APP_URL = "https://github.com/noless-zz/jar/releases/latest"   # where family phones download the app


def refile_memo(path: Path, meta: dict, transcript: str | None = None, from_audio: bool = False) -> dict:
    """Back into the worker's queue. With a corrected transcript, that text is filed instead.
    The worker first removes the still-open tasks the earlier filing made, so nothing doubles."""
    if transcript is not None:
        text = transcript.strip()
        if not text:
            raise HTTPException(400, "the transcript is empty")
        if len(text) > 5000:
            raise HTTPException(400, "the transcript is too long")
        if text != (meta.get("transcript") or "").strip():
            meta.setdefault("original_transcript", meta.get("transcript"))
            meta["transcript"], meta["edited"] = text, True
            path.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
    keep_text = bool(meta.get("transcript")) and not from_audio
    meta.update(status="transcribed" if keep_text else "received", attempts=0, error=None)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return {"id": meta.get("id"), "status": meta["status"], "transcript": meta.get("transcript")}


class LoginLinks:
    """One-time, 2-minute codes the admin's phone app turns into a dashboard login cookie."""

    def __init__(self, admin_token: str):
        self.cookie_value = hashlib.sha256(("jar-dashboard|" + admin_token).encode()).hexdigest()
        self._codes: dict[str, float] = {}

    def issue(self) -> str:
        now = time.time()
        self._codes = {c: t for c, t in self._codes.items() if t > now}
        code = secrets.token_urlsafe(18)
        self._codes[code] = now + 120
        return code

    def redeem(self, code: str) -> bool:
        return self._codes.pop(code or "", 0) > time.time()

    def ok(self, cookie: str | None) -> bool:
        return bool(cookie) and hmac.compare_digest(cookie, self.cookie_value)


def make_router(data_dir: Path, ollama_url: str, rejected=(), token: str = "", port: int = 8080,
                tailscale: bool = True, family=None, logins: LoginLinks | None = None, tasks=None) -> APIRouter:
    logins = logins or LoginLinks(token)

    def gate(request: Request) -> None:
        host = request.client.host if request.client else None
        if host in LOCAL:
            return
        if not allowed(host, tailscale):
            raise HTTPException(403, "the dashboard is only available on the server PC and over Tailscale")
        if not logins.ok(request.cookies.get(COOKIE)):
            raise HTTPException(403, "log in from the Jar app on your phone: menu → Open dashboard")

    outer = APIRouter()

    @outer.get("/login")
    def login(request: Request, n: str = ""):
        if not allowed(request.client.host if request.client else None, tailscale):
            raise HTTPException(403, "the dashboard is only available on the server PC and over Tailscale")
        if not logins.redeem(n):
            raise HTTPException(403, "this login link was used or expired; tap Open dashboard in the app again")
        resp = RedirectResponse("./", status_code=303)
        resp.set_cookie(COOKIE, logins.cookie_value, max_age=30 * 86400, httponly=True, samesite="strict")
        return resp

    r = APIRouter(dependencies=[Depends(gate)])
    memos_dir = data_dir / "memos"

    def all_memos() -> list[tuple[Path, dict]]:
        out = []
        for p in memos_dir.glob("*/*.json"):
            try:
                out.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        out.sort(key=lambda x: x[1].get("recorded_at") or x[1].get("received_at") or "", reverse=True)
        return out

    def find(memo_id: str) -> tuple[Path, dict]:
        for p in memos_dir.glob(f"*/{memo_id}.json"):
            return p, json.loads(p.read_text(encoding="utf-8"))
        raise HTTPException(404, "no such memo")

    @r.get("/", response_class=HTMLResponse)
    def page():
        return (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")

    @r.get("/api/status")
    def status():
        counts: dict[str, int] = {}
        for _, m in all_memos():
            counts[m.get("status", "?")] = counts.get(m.get("status", "?"), 0) + 1
        worker = None
        hb = data_dir / "worker.json"
        if hb.exists():
            try:
                worker = json.loads(hb.read_text(encoding="utf-8"))
                worker["age_seconds"] = round(time.time() - worker.get("epoch", 0))
            except (OSError, json.JSONDecodeError):
                worker = None
        try:
            with urllib.request.urlopen(ollama_url + "/api/ps", timeout=2) as resp:
                loaded = [m["name"] for m in json.loads(resp.read().decode()).get("models", [])]
            ollama = {"up": True, "loaded": loaded}
        except Exception:  # noqa: BLE001
            ollama = {"up": False, "loaded": []}
        sup = None
        try:
            sup = json.loads((data_dir / "supervisor.json").read_text(encoding="utf-8"))
            sup["age_seconds"] = round(time.time() - sup.get("epoch", 0))
        except (OSError, ValueError):
            sup = None
        return {"counts": counts, "worker": worker, "ollama": ollama, "server_pid": os.getpid(), "supervisor": sup,
                "rejected": list(rejected)[-5:][::-1]}

    def person_token(pid: str | None) -> tuple[str, str]:
        """(token, name) for the pairing page; the admin when no/unknown person is asked for."""
        if family is None:
            return token, ""
        p = family.get(pid) or family.admin
        return family.token_for(p.id), p.name

    def pairing_info(pid: str | None = None) -> dict:
        from . import pairing
        addrs = pairing.discover()
        urls = pairing.pairing_urls(addrs, port)
        tok, _ = person_token(pid)
        return {"addrs": addrs, "urls": urls, "link": pairing.pairing_link(tok, urls) if tok else ""}

    @r.get("/api/pair")
    def pair_json(person: str = ""):
        info = pairing_info(person)
        ts = info["addrs"].tailscale
        return {"link": info["link"], "urls": info["urls"], "lan": info["addrs"].lan,
                "tailscale": {"installed": ts.installed, "running": ts.running, "ip": ts.ip,
                              "dns_name": ts.dns_name, "problem": ts.problem}}

    @r.get("/pair", response_class=HTMLResponse)
    def pair_page(person: str = ""):
        import html as h

        from . import pairing
        info = pairing_info(person)
        _, who = person_token(person)
        chosen = (family.get(person) or family.admin).id if family else ""
        people = "".join(
            f'<a class="{"on" if p.id == chosen else ""}" href="pair?person={h.escape(p.id)}">{h.escape(p.name)}</a>'
            for p in (family.people.values() if family else []))
        ts = info["addrs"].tailscale
        if not token:
            raise HTTPException(500, "no device token in config.toml — run setup.ps1")
        rows = []
        for ip in info["addrs"].lan[:2]:
            rows.append(f'<tr><td><span class="dot good"></span>Home Wi-Fi</td><td><code>http://{h.escape(ip)}:{port}</code></td></tr>')
        if ts.ip:
            rows.append(f'<tr><td><span class="dot good"></span>Tailscale</td><td><code>http://{h.escape(ts.ip)}:{port}</code></td></tr>')
        if ts.dns_name:
            rows.append(f'<tr><td><span class="dot good"></span>Tailscale name</td><td><code>http://{h.escape(ts.dns_name)}:{port}</code></td></tr>')
        if not ts.ip:
            state = "not installed" if not ts.installed else (ts.problem or "not connected")
            rows.append(f'<tr><td><span class="dot warn"></span>Tailscale</td><td>{h.escape(state)}</td></tr>')
        hint = ""
        if not ts.installed:
            hint = ('<p class="hint">For recording away from home: install Tailscale on this PC '
                    '(<a href="https://tailscale.com/download/windows" target="_blank">tailscale.com/download</a>), '
                    'sign in, then reload this page — its address is added to the code automatically.</p>')
        elif not ts.ip:
            hint = f'<p class="hint">Tailscale on this PC: {h.escape(ts.problem)}. Then reload this page.</p>'
        page = (Path(__file__).with_name("pair.html")).read_text(encoding="utf-8")
        return (page.replace("{{QR}}", pairing.qr_svg(info["link"]))
                    .replace("{{LINK}}", h.escape(info["link"]))
                    .replace("{{ROWS}}", "".join(rows))
                    .replace("{{TS_HINT}}", hint)
                    .replace("{{APP_QR}}", pairing.qr_svg(APP_URL))
                    .replace("{{APP_URL}}", h.escape(APP_URL))
                    .replace("{{WHO}}", h.escape(who or "a"))
                    .replace("{{PEOPLE}}", people if len(family.people if family else []) > 1 else "")
                    .replace("{{WARN_CLASS}}", "" if ts.ip else "warnbox"))

    @r.get("/api/family")
    def family_json():
        if family is None:
            return {"people": [], "tasks": []}
        # What the admin would see in the app: not the other parent's private to-dos.
        all_tasks = tasks.snapshot(family.admin)["tasks"] if tasks is not None else []
        return {"people": [p.public() for p in family.people.values()],
                "tasks": [t for t in all_tasks if t.get("status") in ("open", "requested")
                          or (t.get("status") == "done" and (t.get("done_at") or "") >= time.strftime(
                              "%Y-%m-%d", time.gmtime(time.time() - 3 * 86400)))]}

    @r.get("/api/memos")
    def memos(limit: int = 50):
        keep = ("id", "device_id", "person", "recorded_at", "duration_ms", "status", "transcript", "language",
                "actions", "summary", "error", "attempts", "fallback", "transcribe_seconds", "llm_seconds")
        out = []
        for _, m in all_memos()[:max(1, min(limit, 500))]:
            row = {k: m.get(k) for k in keep}
            if private(m):
                row.update(transcript="(private — recorded on another parent's phone)", actions=[],
                           summary="", private=True)
            out.append(row)
        return out

    def private(m: dict) -> bool:
        """Another adult's memo: the dashboard shows that it exists, not what was said."""
        if family is None:
            return False
        p = family.get(m.get("person"))
        return p is not None and p.is_parent and not p.admin

    @r.get("/api/memos/{memo_id}/audio")
    def audio(memo_id: str):
        p, m = find(memo_id)
        if private(m):
            raise HTTPException(403, "another parent's memo")
        return FileResponse(p.with_suffix(".wav"), media_type="audio/wav")

    @r.post("/api/memos/{memo_id}/reprocess")
    def reprocess(memo_id: str, transcribe: bool = False, body: dict | None = Body(None)):
        """Re-file the memo: as is, with a corrected transcript ({"transcript": "..."}), or
        (transcribe=true) from the audio. Open tasks from the earlier filing are replaced."""
        p, m = find(memo_id)
        if private(m):
            raise HTTPException(403, "another parent's memo")
        text = (body or {}).get("transcript")
        return refile_memo(p, m, None if text is None else str(text), from_audio=transcribe)

    @r.post("/api/tasks/{task_id}/{action}")
    def task_action(task_id: str, action: str, body: dict | None = Body(None)):
        """The dashboard edits tasks as the admin (what the admin's app could do)."""
        if tasks is None or family is None:
            raise HTTPException(404, "no task list")
        from worker.taskstore import TaskError
        b = body or {}
        try:
            return tasks.act(family.admin, task_id, action, b.get("until"), b)
        except TaskError as e:
            raise HTTPException(e.status, str(e)) from None

    @r.post("/api/tasks")
    def task_new(body: dict = Body(...)):
        if tasks is None or family is None:
            raise HTTPException(404, "no task list")
        from worker.taskstore import TaskError
        try:
            ids = body.get("assignees") or ([body["assignee"]] if body.get("assignee") else [])
            who = tasks.resolve_people(ids) or [family.admin]
            return tasks.add(family.admin, str(body.get("title", "")), who, body.get("due") or None,
                             mode=str(body.get("mode") or "any"))
        except TaskError as e:
            raise HTTPException(e.status, str(e)) from None

    outer.include_router(r)
    return outer
