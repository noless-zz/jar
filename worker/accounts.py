"""Which connector serves which role ("personal", "school"), from config.toml."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from .connectors import FamilyGoogle, Google, Outlook


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


def build_family(cfg, family):
    """The family's own Jar Gmail ([family_account] in config.toml), or None when it isn't set up."""
    fa = getattr(cfg, "family_account", None) or {}
    if not fa or str(fa.get("provider", "google")).lower() != "google" or fa.get("enabled") is False:
        return None
    secrets = cfg.data_dir / "secrets"
    client = fa.get("client_secrets") or "data/secrets/google_family_client.json"
    from pathlib import Path
    path = Path(client) if Path(client).is_absolute() else cfg.root / client
    return FamilyGoogle(path, secrets, ZoneInfo(cfg.timezone), family.emails() if family else [],
                        str(fa.get("calendar_id", "primary")))
