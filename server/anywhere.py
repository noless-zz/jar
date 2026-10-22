"""Keeps Jar reachable from anywhere: watches the Tailscale Funnel that publishes the phone API (/v1) and
turns it back on when it has dropped (Tailscale restarted or updated, a Funnel reset…).

Only when it is wanted: data/anywhere.json {"on": true} (tools/enable-anywhere.ps1 writes it; -Off clears it).
Every 5 minutes (1 minute after a problem) it asks Tailscale for the published address and fetches
<address>/v1/health from this PC. Missing, or failing twice in a row → publish again, the same way
enable-anywhere.ps1 does. The result goes into data/supervisor.json ("anywhere") and the supervisor log.
Runs on its own thread, so a slow network never holds up the supervisor.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("jar.supervise")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wanted(data: Path) -> bool:
    try:
        return bool(json.loads((data / "anywhere.json").read_text(encoding="utf-8")).get("on"))
    except (OSError, ValueError, AttributeError):
        return False


def public_ips(host: str, timeout: float = 8) -> list[str]:
    """The host's addresses in PUBLIC DNS (DNS-over-HTTPS), not this PC's MagicDNS: a Funnel that is off has none."""
    for doh in ("https://dns.google/resolve?type=A&name=", "https://cloudflare-dns.com/dns-query?type=A&name="):
        try:
            req = urllib.request.Request(doh + host, headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ans = json.loads(r.read().decode()).get("Answer") or []
            ips = [a["data"] for a in ans if a.get("type") == 1]
            return ips
        except Exception:  # noqa: BLE001 — try the next resolver
            continue
    return []


def healthy(url: str, timeout: float = 10) -> bool:
    """Does <url>/v1/health answer over the INTERNET, through the Funnel? Connects to the host's public address
    (from public DNS) with the right TLS name, so the request can't take a shortcut over the tailnet, and the
    server says whether it arrived as a Funnel request."""
    import http.client
    import socket
    import ssl
    host = url.replace("https://", "").split("/")[0].split(":")[0]
    ctx = ssl.create_default_context()
    for ip in public_ips(host)[:2]:
        try:
            with socket.create_connection((ip, 443), timeout=timeout) as raw, \
                    ctx.wrap_socket(raw, server_hostname=host) as tls:
                conn = http.client.HTTPConnection(host, timeout=timeout)
                conn.sock = tls
                conn.request("GET", "/v1/health", headers={"Host": host})
                body = json.loads(conn.getresponse().read().decode() or "{}")
                if body.get("ok") and body.get("via", "funnel") == "funnel":
                    return True
        except Exception:  # noqa: BLE001 — try the next address
            continue
    return False


class AnywhereWatch:
    def __init__(self, data: Path, port: int, every: float = 300, retry: float = 60,
                 status_fn=None, health_fn=healthy, run_fn=None, sleep_fn=time.sleep):
        self.data, self.port, self.every, self.retry = data, int(port), every, retry
        self.status_fn = status_fn                # () -> pairing.Tailscale; default: the real CLI
        self.health_fn, self.sleep_fn = health_fn, sleep_fn
        self.run_fn = run_fn or self._run
        self.next_at = 0.0
        self.fails = 0
        self.fix_after = 0.0                      # after a fix that didn't help: wait before the next one
        self.status: dict = {"wanted": False}
        self._busy = threading.Lock()

    # -- called from the supervisor loop every couple of seconds --
    def maybe_check(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if now < self.next_at or self._busy.locked():
            return
        self.next_at = now + self.every
        threading.Thread(target=self.check, daemon=True).start()

    def check(self) -> dict:
        with self._busy:
            st = {"wanted": wanted(self.data), "checked": time.time()}
            if not st["wanted"]:
                self.status = st
                return st
            try:
                st.update(self._check())
            except Exception as e:  # noqa: BLE001
                log.exception("anywhere check failed")
                st.update(ok=False, problem=f"{type(e).__name__}: {e}")
            if not st.get("ok"):
                self.next_at = min(self.next_at, time.time() + self.retry)
            for k in ("last_fix", "fixes"):
                if k in self.status and k not in st:
                    st[k] = self.status[k]
            self.status = st
            return st

    def _tailscale(self):
        if self.status_fn is not None:
            return self.status_fn()
        from . import pairing
        return pairing.tailscale_status(timeout=8)

    def _check(self) -> dict:
        ts = self._tailscale()
        if not getattr(ts, "installed", False) or not getattr(ts, "running", False):
            problem = getattr(ts, "problem", "") or "Tailscale isn't running"
            if self.status.get("problem") != problem:
                log.warning("anywhere: can't publish Jar — Tailscale: %s", problem)
            return {"ok": False, "url": "", "problem": f"Tailscale: {problem}"}
        url = getattr(ts, "funnel_url", "") or ""
        if url and self.health_fn(url):
            if not self.status.get("ok") and self.status.get("checked"):
                log.info("anywhere: %s answers again", url)
            self.fails = 0
            return {"ok": True, "url": url}
        self.fails += 1
        why = "not published" if not url else f"{url}/v1/health didn't answer"
        if url and self.fails < 2:
            return {"ok": False, "url": url, "problem": why + " (checking again in a minute)"}
        if time.time() < self.fix_after:
            return {"ok": False, "url": url, "problem": self.status.get("problem", why),
                    "diagnosis": self.status.get("diagnosis", {})}
        log.warning("anywhere: %s — publishing Jar again", why)
        ok, url2 = self.fix(getattr(ts, "dns_name", ""))
        self.fails = 0 if ok else self.fails
        fixes = int(self.status.get("fixes", 0)) + 1
        out = {"ok": ok, "url": url2 or url, "last_fix": time.time(), "fixes": fixes}
        if ok:
            log.info("anywhere: published again, %s answers", url2)
        else:
            self.fix_after = time.time() + 1800
            if self.status.get("tailscale_said"):
                out["tailscale_said"] = self.status["tailscale_said"]
            out["diagnosis"] = d = self.diagnose(getattr(ts, "dns_name", ""))
            out["problem"] = why + "; publishing again didn't help — " + d.get("hint", "see the diagnosis")
            log.warning("anywhere: %s %s", out["problem"], json.dumps(d, ensure_ascii=False))
        return out

    def diagnose(self, dns_name: str) -> dict:
        """Why Tailscale isn't publishing: the Funnel permission, the key expiry, public DNS."""
        d: dict = {"public_dns": public_ips(dns_name) if dns_name else []}
        raw = self._out(["status", "--json"])
        try:
            me = json.loads(raw or "{}").get("Self") or {}
        except ValueError:
            me = {}
        caps = list((me.get("CapMap") or {}).keys()) + list(me.get("Capabilities") or [])
        d["funnel_allowed"] = any("funnel" in str(c) for c in caps)
        d["https_certs"] = bool(json.loads(raw or "{}").get("CertDomains")) if raw else None
        d["key_expiry"] = me.get("KeyExpiry", "")
        d["online"] = me.get("Online")
        if not d["funnel_allowed"]:
            d["hint"] = ("this PC doesn't have the Funnel permission in the tailnet: Tailscale admin console → Access "
                         "controls → nodeAttrs \"funnel\" (or run tools/enable-anywhere.ps1 and approve the link)")
        elif d["key_expiry"] and d["key_expiry"] < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
            d["hint"] = "the PC's Tailscale key expired: sign in to Tailscale on the PC again"
        elif not d["public_dns"]:
            d["hint"] = "Tailscale isn't announcing the Funnel: run tools/enable-anywhere.ps1 on the PC and approve any link"
        else:
            d["hint"] = "the address exists but doesn't reach Jar: run tools/enable-anywhere.ps1 -Status on the PC"
        return d

    def _out(self, args: list[str]) -> str:
        from . import pairing
        exe = pairing._tailscale_exe()
        if not exe:
            return ""
        try:
            return subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=15, creationflags=NO_WINDOW).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def fix(self, dns_name: str) -> tuple[bool, str]:
        """Publish /v1 like enable-anywhere.ps1: map /v1 to the server's /v1, or (older Tailscale) to its root."""
        url = f"https://{dns_name}" if dns_name else ""
        for n, target in enumerate((f"http://127.0.0.1:{self.port}/v1", f"http://127.0.0.1:{self.port}")):
            self.run_fn(["funnel", "--bg", "--set-path", "/v1", "off"])
            self.run_fn(["funnel", "--bg", "--set-path", "/v1", target])
            if n == 0 and dns_name:
                # A re-announced Funnel takes minutes to reach public DNS (resolvers also remember the "no such
                # name" for ~5 min). Judge the mapping only once the address exists, or the right one looks broken.
                for _ in range(30):
                    if public_ips(dns_name):
                        break
                    self.sleep_fn(15)
            for _ in range(4):                       # the first certificate can take a little while
                self.sleep_fn(10)
                ts = self._tailscale()
                url = getattr(ts, "funnel_url", "") or url
                if url and self.health_fn(url):
                    return True, url
        return False, url

    def _run(self, args: list[str]) -> int:
        from . import pairing
        exe = pairing._tailscale_exe()
        if not exe:
            return 127
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=40, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired as e:
            out = ((e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "").encode()).decode(errors="replace")
            log.warning("anywhere: tailscale %s timed out: %s", " ".join(args), out.strip()[:500])
            self.status["tailscale_said"] = out.strip()[:500]
            return 1
        except OSError:
            return 1
        said = (r.stdout + r.stderr).strip()
        if said and args[-1] != "off":
            log.info("anywhere: tailscale %s -> %s", " ".join(args), said[:500])   # e.g. an approval link
            self.status["tailscale_said"] = said[:500]
        return r.returncode
