"""Which connector serves which role ("personal", "school"), from config.toml."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from .connectors import Google, Outlook


def build(cfg) -> dict:
    tz = ZoneInfo(cfg.timezone)
    secrets = cfg.data_dir / "secrets"
    out = {}
    for role, provider in cfg.accounts.items():
        if provider == "outlook" and cfg.outlook_client_id:
            out[role] = Outlook(cfg.outlook_client_id, secrets, tz)
        elif provider == "google":
            out[role] = Google(cfg.google_client_secrets, secrets, tz, cfg.google_calendar_id)
        else:
            out[role] = None
    return out
