"""A small client for Jar's server (/v1), with the Home Assistant ("home") token from the pairing link."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=8)


class JarError(Exception):
    """Jar answered with an error (the message is Jar's own)."""


class JarAuthError(JarError):
    """The token isn't accepted (a new link was made on the Jar dashboard)."""


class JarUnreachable(JarError):
    """None of Jar's addresses answered."""


def parse_link(link: str) -> tuple[str, list[str]]:
    """jar://pair?v=1&t=TOKEN&u=URL&u=URL -> (token, urls). Raises ValueError on anything else."""
    link = (link or "").strip()
    u = urlparse(link)
    if u.scheme != "jar" or u.netloc != "pair":
        raise ValueError("not a Jar link")
    q = parse_qs(u.query)
    token = (q.get("t") or [""])[0].strip()
    urls = [x.rstrip("/") for x in q.get("u", []) if x.startswith(("http://", "https://"))]
    if not token or not urls:
        raise ValueError("the link has no token or address")
    # The public https address first: Home Assistant may not share the PC's home network.
    urls.sort(key=lambda x: 0 if x.startswith("https://") else 1)
    return token, urls


class JarApi:
    def __init__(self, session: aiohttp.ClientSession, token: str, urls: list[str]) -> None:
        self._session = session
        self._token = token
        self.urls = list(urls)
        self._good = 0          # index of the address that worked last

    async def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "X-Device-Id": "home-assistant"}
        order = self.urls[self._good:] + self.urls[:self._good]
        last: Exception | None = None
        for url in order:
            try:
                async with self._session.request(method, url + path, json=body, headers=headers,
                                                 timeout=TIMEOUT) as r:
                    if r.status == 401:
                        raise JarAuthError("Jar refused the token")
                    data = await r.json(content_type=None) if r.content_length != 0 else None
                    if r.status >= 400:
                        detail = (data or {}).get("detail") if isinstance(data, dict) else None
                        raise JarError(str(detail or f"HTTP {r.status}"))
                    self._good = self.urls.index(url)
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last = e
                _LOGGER.debug("Jar at %s didn't answer: %s", url, e)
        raise JarUnreachable(f"Jar didn't answer at any address ({last})")

    async def auth(self) -> dict:
        return await self._request("GET", "/v1/auth")

    async def me(self) -> dict:
        return await self._request("GET", "/v1/me")

    async def tasks(self) -> dict:
        return await self._request("GET", "/v1/tasks")

    async def points(self) -> dict:
        return await self._request("GET", "/v1/points")

    async def add_task(self, title: str, assignees: list[str], due: str | None = None, notes: str = "",
                       mode: str = "any") -> dict:
        body: dict[str, Any] = {"title": title, "assignees": assignees, "notes": notes, "mode": mode}
        if due:
            body["due"] = due
        return await self._request("POST", "/v1/tasks", body)

    async def act(self, task_id: str, action: str, person: str) -> dict:
        return await self._request("POST", f"/v1/tasks/{task_id}/{action}", {"as": person})

    async def link_home(self, url: str, token: str) -> dict:
        return await self._request("POST", "/v1/home/link", {"url": url, "token": token})
