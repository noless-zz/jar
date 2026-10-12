"""Pairing: everything the phone app needs, in one QR code.

The PC works out how a phone can reach it:
  * home network — its LAN IPv4 addresses (192.168.x.x, 10.x.x.x …)
  * Tailscale    — its 100.x.y.z address and MagicDNS name, if Tailscale is installed and up
  * anywhere     — https://<pc>.<tailnet>.ts.net when Tailscale Funnel publishes /v1 (phones then need
                   nothing installed; tools/enable-anywhere.ps1 turns it on)
and packs them with the device token into a link:

    jar://pair?v=1&t=<token>&u=http://192.168.1.87:8080&u=http://100.101.102.103:8080

The app scans it (or opens it as a link), saves every address, and uploads to whichever
answers — home Wi-Fi at home, Tailscale everywhere else — with no settings to switch.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Tailscale:
    installed: bool = False
    running: bool = False
    ip: str = ""
    dns_name: str = ""
    problem: str = ""
    funnel_url: str = ""      # public https address when Funnel serves Jar's /v1


@dataclass
class Addresses:
    lan: list[str] = field(default_factory=list)
    tailscale: Tailscale = field(default_factory=Tailscale)


def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    if sys.platform == "win32":
        p = Path(r"C:\Program Files\Tailscale\tailscale.exe")
        if p.exists():
            return str(p)
    return None


def parse_tailscale_status(raw: str) -> Tailscale:
    """`tailscale status --json` → our own IP + MagicDNS name (pure, unit-tested)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Tailscale(installed=True, problem="unreadable tailscale status")
    state = data.get("BackendState", "")
    me = data.get("Self") or {}
    ips = [ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip]  # IPv4 only
    ts = Tailscale(installed=True, running=state == "Running", ip=ips[0] if ips else "",
                   dns_name=(me.get("DNSName") or "").rstrip("."))
    if state != "Running":
        ts.problem = {"NeedsLogin": "signed out — open Tailscale and sign in",
                      "Stopped": "Tailscale is turned off — open it and connect"}.get(state, f"state {state or 'unknown'}")
    return ts


def parse_funnel(raw: str) -> str:
    """`tailscale serve status --json` → the public https URL that reaches Jar's /v1, or "" (pure)."""
    try:
        cfg = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return ""
    allow = cfg.get("AllowFunnel") or {}
    for hostport, handlers in (cfg.get("Web") or {}).items():
        if not allow.get(hostport):
            continue
        paths = (handlers or {}).get("Handlers") or {}
        if not any(p in ("/", "/v1", "/v1/") for p in paths):
            continue
        host, _, port = hostport.rpartition(":")
        return f"https://{host}" + ("" if port in ("443", "") else f":{port}")
    return ""


def tailscale_status(timeout: float = 4) -> Tailscale:
    exe = _tailscale_exe()
    if not exe:
        return Tailscale(problem="not installed")
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return Tailscale(installed=True, problem=f"tailscale CLI failed ({type(e).__name__})")
    if not out.stdout.strip():
        return Tailscale(installed=True, problem=(out.stderr.strip() or "Tailscale service not running")[:200])
    ts = parse_tailscale_status(out.stdout)
    if ts.running:
        try:
            serve = subprocess.run([exe, "serve", "status", "--json"], capture_output=True, text=True,
                                   timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ts.funnel_url = parse_funnel(serve.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ts


def is_lan(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # Private home-network ranges; skip Tailscale's own range, loopback and link-local.
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local and a not in TAILSCALE_NET


def lan_addresses() -> list[str]:
    found: list[str] = []
    # The address of the interface that carries the default route (no packet is actually sent).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if is_lan(ip) and ip not in out:
            out.append(ip)
    return out


def discover() -> Addresses:
    return Addresses(lan=lan_addresses(), tailscale=tailscale_status())


def pairing_urls(addrs: Addresses, port: int) -> list[str]:
    """Order matters: the app tries them in this order the first time.
    Home network first (fastest at home), then the public Funnel address (works anywhere, nothing to
    install), then the Tailscale IP and MagicDNS name (for phones that run Tailscale)."""
    urls = [f"http://{ip}:{port}" for ip in addrs.lan[:2]]
    ts = addrs.tailscale
    if ts.funnel_url:
        urls.append(ts.funnel_url)
    if ts.ip:
        urls.append(f"http://{ts.ip}:{port}")
    if ts.dns_name:
        urls.append(f"http://{ts.dns_name}:{port}")
    return urls


def pairing_link(token: str, urls: list[str]) -> str:
    return "jar://pair?" + urlencode([("v", "1"), ("t", token)] + [("u", u) for u in urls])


def qr_svg(text: str) -> str:
    """QR code as inline SVG (needs the `qrcode` package; no Pillow required)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    svg = img.to_string(encoding="unicode")
    return svg[svg.index("<svg"):]  # drop the XML declaration so it can sit inside HTML
