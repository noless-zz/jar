"""Sign in to the accounts Jar may use (opens your browser once per account).

    python -m worker.connect outlook     personal: your Outlook.com / Hotmail account
    python -m worker.connect google      school:   Google Workspace
    python -m worker.connect family      the family's own Jar Gmail (sends to family members only)
    python -m worker.connect status      which accounts are connected
"""

from __future__ import annotations

import sys

from . import config as config_mod
from .accounts import build, build_family
from .family import Family


def main() -> None:
    what = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    cfg = config_mod.load()
    conns = build(cfg)
    conns["family"] = build_family(cfg, Family.from_config(cfg.family or {}, cfg.token, cfg.data_dir))
    if what == "status":
        for role, conn in conns.items():
            if conn is None:
                print(f"{role:9} not configured")
                continue
            who = conn.account()
            print(f"{role:9} {conn.name:8} {'connected as ' + who if who else 'NOT connected'}")
        return
    match = [c for c in conns.values() if c is not None and c.name.lower() == what]
    if not match:
        raise SystemExit(f"'{what}' is not set up in config.toml [accounts] / [{what}] — see docs/CONNECT.md")
    print(f"Opening the browser to sign in to {match[0].name}…")
    who = match[0].sign_in()
    print(f"Connected: {who}")


if __name__ == "__main__":
    main()
