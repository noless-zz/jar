"""Calendar + email connectors: Outlook.com (Microsoft Graph) and Google Workspace.

Phase 1 does only things that stay inside your own account:
  * create a calendar event for you (no attendees, so nobody else is notified)
  * create an email DRAFT — you review it in Outlook/Gmail and press Send yourself
Anything that reaches other people will go through an approval step (spec PRC-5) later.

Sign-in happens once, in the browser:  python -m worker.connect outlook | google
Tokens are kept in data/secrets/ (git-ignored) and refreshed automatically.
The payload builders are plain functions so they are unit-tested without any network.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("jar.connectors")

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["Calendars.ReadWrite", "Mail.ReadWrite"]   # drafts only: no Mail.Send yet
GRAPH_AUTHORITY = "https://login.microsoftonline.com/consumers"   # personal accounts (live.com)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events",
                 "https://www.googleapis.com/auth/gmail.compose"]
# The family's own Jar account (a Gmail made for Jar): it SENDS mail and invites people, but only
# family members (FamilyGoogle refuses any other address). It can't read anyone's mail.
FAMILY_SCOPES = ["https://www.googleapis.com/auth/calendar.events",
                 "https://www.googleapis.com/auth/gmail.send"]


class NotConnected(Exception):
    """No sign-in yet (or it expired): the tool falls back to a local file."""


@dataclass
class Result:
    summary: str
    link: str = ""
    id: str = ""          # the provider's id for what was made (e.g. a calendar event), when known


# ---------------------------------------------------------------- payload builders (pure)

def _span(day: date, start_time: str | None, duration_min: int, tz: ZoneInfo):
    """(start, end) as aware datetimes, or None for an all-day event."""
    if not start_time:
        return None
    start = datetime.combine(day, datetime.strptime(start_time, "%H:%M").time(), tz)
    return start, start + timedelta(minutes=duration_min)


def graph_event(title: str, day: date, start_time: str | None, duration_min: int, tz: ZoneInfo,
                location: str = "", notes: str = "") -> dict:
    body = {"subject": title, "body": {"contentType": "text", "content": notes},
            "isReminderOn": True}
    span = _span(day, start_time, duration_min, tz)
    if span:
        # Sent in UTC so Graph never has to interpret a time-zone name.
        fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
        body["start"] = {"dateTime": fmt(span[0]), "timeZone": "UTC"}
        body["end"] = {"dateTime": fmt(span[1]), "timeZone": "UTC"}
    else:
        body["isAllDay"] = True
        body["start"] = {"dateTime": f"{day.isoformat()}T00:00:00", "timeZone": "UTC"}
        body["end"] = {"dateTime": f"{(day + timedelta(days=1)).isoformat()}T00:00:00", "timeZone": "UTC"}
    if location:
        body["location"] = {"displayName": location}
    return body


def google_event(title: str, day: date, start_time: str | None, duration_min: int, tz: ZoneInfo,
                 location: str = "", notes: str = "") -> dict:
    body = {"summary": title, "description": notes}
    span = _span(day, start_time, duration_min, tz)
    if span:
        body["start"] = {"dateTime": span[0].isoformat(), "timeZone": str(tz)}
        body["end"] = {"dateTime": span[1].isoformat(), "timeZone": str(tz)}
    else:
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (day + timedelta(days=1)).isoformat()}
    if location:
        body["location"] = location
    return body


def family_event(title: str, day: date, start_time: str | None, duration_min: int, tz: ZoneInfo,
                 attendees: list[str], location: str = "", notes: str = "") -> dict:
    """A Google event on the family calendar that invites family members (they get it in their calendars)."""
    body = google_event(title, day, start_time, duration_min, tz, location, notes)
    body["attendees"] = [{"email": a} for a in attendees]
    body["guestsCanModify"] = True               # it's the family's event: anyone invited may move it
    body["reminders"] = {"useDefault": True}
    return body


def gmail_message(sender: str, to: list[str], subject: str, body: str) -> dict:
    """A message for Gmail's users.messages.send (sent at once)."""
    msg = EmailMessage()
    if sender:
        msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")}


def graph_draft(to: list[str], subject: str, body: str) -> dict:
    return {"subject": subject, "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to]}


def gmail_draft(to: list[str], subject: str, body: str) -> dict:
    msg = EmailMessage()
    if to:
        msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
    return {"message": {"raw": raw}}


# ---------------------------------------------------------------- Outlook.com via Microsoft Graph

class Outlook:
    name = "Outlook"

    def __init__(self, client_id: str, secrets_dir: Path, tz: ZoneInfo):
        self.client_id, self.tz = client_id, tz
        self.cache_path = secrets_dir / "outlook_token.json"

    def _app(self):
        import msal
        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            cache.deserialize(self.cache_path.read_text(encoding="utf-8"))
        return msal.PublicClientApplication(self.client_id, authority=GRAPH_AUTHORITY, token_cache=cache), cache

    def _save(self, cache) -> None:
        if cache.has_state_changed:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(cache.serialize(), encoding="utf-8")

    def sign_in(self) -> str:
        """Opens the browser once; afterwards tokens refresh silently."""
        app, cache = self._app()
        r = app.acquire_token_interactive(GRAPH_SCOPES, prompt="select_account")
        self._save(cache)
        if "access_token" not in r:
            raise RuntimeError(r.get("error_description") or r.get("error") or "sign-in failed")
        return (r.get("id_token_claims") or {}).get("preferred_username", "?")

    def account(self) -> str | None:
        if not self.client_id or not self.cache_path.exists():
            return None
        app, _ = self._app()
        accts = app.get_accounts()
        return accts[0]["username"] if accts else None

    def _token(self) -> str:
        if not self.client_id:
            raise NotConnected("Outlook: no client_id in config.toml [outlook]")
        app, cache = self._app()
        accts = app.get_accounts()
        r = app.acquire_token_silent(GRAPH_SCOPES, account=accts[0]) if accts else None
        self._save(cache)
        if not r or "access_token" not in r:
            raise NotConnected("Outlook: not signed in — run Jar: Connect Outlook")
        return r["access_token"]

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(GRAPH + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + self._token(),
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Graph {e.code}: {e.read().decode(errors='replace')[:300]}") from e

    def create_event(self, title, day, start_time, duration_min, location="", notes="") -> Result:
        r = self._post("/me/events", graph_event(title, day, start_time, duration_min, self.tz, location, notes))
        return Result("Outlook calendar", r.get("webLink", ""))

    def create_draft(self, to, subject, body) -> Result:
        r = self._post("/me/messages", graph_draft(to, subject, body))
        return Result("Outlook drafts", r.get("webLink", ""))


# ---------------------------------------------------------------- Google Workspace (school)

class _Catch:
    """WSGI app for the sign-in redirect. Ignores stray connections (Chrome preconnects,
    favicon) that made google-auth-oauthlib's run_local_server give up with WSGITimeoutError."""

    def __init__(self):
        self.uri: str | None = None

    def __call__(self, environ, start_response):
        import wsgiref.util
        uri = wsgiref.util.request_uri(environ)
        if "code=" in uri or "error=" in uri:
            self.uri = uri
            msg = "Jar: done, you can close this tab." if "code=" in uri else "Jar: sign-in was cancelled."
        else:
            msg = "Jar is waiting for Google sign-in..."
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
        return [msg.encode()]


def _google_browser_sign_in(flow, wait_seconds: int = 300):
    import time
    import webbrowser
    import wsgiref.simple_server
    from urllib.parse import parse_qs, urlparse

    class Quiet(wsgiref.simple_server.WSGIRequestHandler):
        def log_message(self, *a):  # keep the terminal readable
            pass

    app = _Catch()
    server = wsgiref.simple_server.make_server("127.0.0.1", 0, app, handler_class=Quiet)
    server.timeout = 1
    flow.redirect_uri = f"http://localhost:{server.server_port}/"
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    print("\nIf no browser opens, copy this link into the browser where you're signed in to the SCHOOL account:\n")
    print(url + "\n")
    webbrowser.open(url, new=1)
    deadline = time.time() + wait_seconds
    try:
        while app.uri is None and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if app.uri is None:
        raise RuntimeError("no answer from Google within 5 minutes. If the browser showed an error "
                           "(e.g. 'Access blocked' or 'org_internal'), that page says why. See docs/CONNECT.md")
    q = parse_qs(urlparse(app.uri).query)
    if "error" in q:
        raise RuntimeError(f"Google said: {q['error'][0]} (did you press Cancel, or pick the wrong account?)")
    flow.fetch_token(authorization_response=app.uri.replace("http://", "https://", 1))
    return flow.credentials

class Google:
    name = "Google"

    def __init__(self, client_secrets: Path, secrets_dir: Path, tz: ZoneInfo, calendar_id: str = "primary"):
        self.client_secrets, self.tz, self.calendar_id = client_secrets, tz, calendar_id
        self.token_path = secrets_dir / "google_token.json"

    def sign_in(self) -> str:
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not self.client_secrets.exists():
            raise RuntimeError(f"missing {self.client_secrets} — see docs/CONNECT.md")
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets), GOOGLE_SCOPES,
                                                         autogenerate_code_verifier=True)
        creds = _google_browser_sign_in(flow)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return self.account() or "signed in"

    def _creds(self):
        if not self.token_path.exists():
            raise NotConnected("Google: not signed in — run Jar: Connect Google (school)")
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(self.token_path), GOOGLE_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise NotConnected("Google: sign-in expired — run Jar: Connect Google (school)")
        return creds

    def account(self) -> str | None:
        try:
            from google.auth.transport.requests import AuthorizedSession
            r = AuthorizedSession(self._creds()).get("https://gmail.googleapis.com/gmail/v1/users/me/profile", timeout=10)
            return r.json().get("emailAddress") if r.ok else None
        except Exception:  # noqa: BLE001
            return None

    def _post(self, url: str, body: dict) -> dict:
        from google.auth.transport.requests import AuthorizedSession
        r = AuthorizedSession(self._creds()).post(url, json=body, timeout=20)
        if not r.ok:
            raise RuntimeError(f"Google {r.status_code}: {r.text[:300]}")
        return r.json()

    def create_event(self, title, day, start_time, duration_min, location="", notes="") -> Result:
        url = f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
        r = self._post(url, google_event(title, day, start_time, duration_min, self.tz, location, notes))
        return Result("Google calendar (school)", r.get("htmlLink", ""))

    def create_draft(self, to, subject, body) -> Result:
        r = self._post("https://gmail.googleapis.com/gmail/v1/users/me/drafts", gmail_draft(to, subject, body))
        msg_id = (r.get("message") or {}).get("id", "")
        return Result("Gmail drafts (school)",
                      f"https://mail.google.com/mail/u/0/#drafts?compose={msg_id}" if msg_id else "")


class NotFamily(Exception):
    """An address that isn't a family member's: the family account never writes to it."""


class FamilyGoogle(Google):
    """The family's own Jar Gmail account. Sends email and puts events (with invitations) on the family
    calendar by itself, but only to the family addresses it was given; anything else is refused."""
    name = "Family"

    def __init__(self, client_secrets: Path, secrets_dir: Path, tz: ZoneInfo, allowed: list[str],
                 calendar_id: str = "primary"):
        super().__init__(client_secrets, secrets_dir, tz, calendar_id)
        self.token_path = secrets_dir / "google_family_token.json"
        self.allowed = {a.strip().lower() for a in allowed if "@" in a}

    def sign_in(self) -> str:
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not self.client_secrets.exists():
            raise RuntimeError(f"missing {self.client_secrets} — see docs/CONNECT.md, part C")
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets), FAMILY_SCOPES,
                                                         autogenerate_code_verifier=True)
        creds = _google_browser_sign_in(flow)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return self.account() or "signed in"

    def _creds(self):
        if not self.token_path.exists():
            raise NotConnected("family account: not signed in — run Jar: Connect family account")
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(self.token_path), FAMILY_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise NotConnected("family account: sign-in expired — run Jar: Connect family account")
        return creds

    def account(self) -> str | None:
        # gmail.send can't read the profile, and calendar.events can't read calendars/primary (403).
        # Listing events is allowed, and the listing's "summary" is the account's address.
        try:
            from google.auth.transport.requests import AuthorizedSession
            r = AuthorizedSession(self._creds()).get(
                f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events",
                params={"maxResults": 1}, timeout=10)
            return r.json().get("summary") if r.ok else None
        except Exception:  # noqa: BLE001
            return None

    def check(self, addresses: list[str]) -> list[str]:
        clean = [a.strip().lower() for a in addresses if a and a.strip()]
        outside = [a for a in clean if a not in self.allowed]
        if outside:
            raise NotFamily("not a family address: " + ", ".join(outside))
        if not clean:
            raise NotFamily("nobody to send to (no family member has an email in config.toml)")
        return list(dict.fromkeys(clean))

    def create_family_event(self, title, day, start_time, duration_min, attendees, location="", notes="") -> Result:
        who = self.check(attendees)
        url = (f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events"
               "?sendUpdates=all")
        r = self._post(url, family_event(title, day, start_time, duration_min, self.tz, who, location, notes))
        return Result("the family calendar", r.get("htmlLink", ""), r.get("id", ""))

    def delete_family_event(self, event_id: str) -> bool:
        """Remove an event Jar made on the family calendar (guests get a cancellation).
        True = gone (also when it was already deleted)."""
        from google.auth.transport.requests import AuthorizedSession
        url = (f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/"
               f"{urllib.parse.quote(event_id, safe='')}?sendUpdates=all")
        r = AuthorizedSession(self._creds()).delete(url, timeout=20)
        if r.status_code in (200, 204, 404, 410):
            return True
        raise RuntimeError(f"Google {r.status_code}: {r.text[:300]}")

    def send(self, to, subject, body) -> Result:
        who = self.check(to)
        self._post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", gmail_message("", who, subject, body))
        return Result("sent from the family account")
