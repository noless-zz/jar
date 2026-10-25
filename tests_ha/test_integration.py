"""End to end: Home Assistant's Jar integration against a real Jar server on localhost.

Needs Home Assistant's test harness (not part of the normal suite):
    pip install pytest-homeassistant-custom-component fastapi uvicorn qrcode
    pytest tests_ha
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JAR_DEVICE_TOKEN", "admin-token-123")
os.environ.setdefault("JAR_DATA_DIR", tempfile.mkdtemp())

import custom_components  # noqa: E402  (the harness's own testing package: add ours to it)

if str(ROOT / "custom_components") not in list(custom_components.__path__):
    custom_components.__path__.append(str(ROOT / "custom_components"))

from homeassistant.components.todo import DOMAIN as TODO  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

FAMILY_CFG = {
    "avi": {"name": "Avi", "role": "parent", "admin": True},
    "dana": {"name": "Dana", "role": "parent"},
    "yoni": {"name": "Yoni", "role": "child"},
    "maya": {"name": "Maya", "role": "child"},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def jar(socket_enabled):
    """A real Jar server on a free localhost port, with a fresh family."""
    import uvicorn

    from server import server
    from worker.family import Family
    from worker.points import PointsConfig, PointsStore
    from worker.taskstore import TaskStore
    tmp = Path(tempfile.mkdtemp())
    fam = Family.from_config(FAMILY_CFG, "admin-token-123", tmp)
    points = PointsStore(tmp / "points.json", fam, "Asia/Jerusalem", PointsConfig())
    tasks = TaskStore(tmp / "tasks.json", fam, tmp / "Tasks.md", points)
    server.FAMILY, server.TASKS, server.POINTS, server.TOKEN = fam, tasks, points, "admin-token-123"
    server.HOME_LINK = tmp / "secrets" / "home_assistant.json"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    while not srv.started:
        time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}", "fam": fam, "tasks": tasks, "server": server}
    srv.should_exit = True
    th.join(5)


def link(jar) -> str:
    from server import pairing
    # a dead address first: the integration must fall through to the one that answers
    return pairing.pairing_link(jar["fam"].home_token(), ["http://127.0.0.1:9", jar["url"]])


async def test_config_flow_rejects_a_phone_link(hass: HomeAssistant, jar) -> None:
    from server import pairing
    r = await hass.config_entries.flow.async_init("jar", context={"source": "user"})
    phone = pairing.pairing_link(jar["fam"].token_for("yoni"), [jar["url"]])
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"link": phone, "allow_control": False})
    assert r["errors"] == {"link": "not_home_link"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"link": "nonsense", "allow_control": False})
    assert r["errors"] == {"link": "bad_link"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"link": link(jar), "allow_control": False})
    assert r["type"] == "create_entry"
    assert r["data"]["urls"][0] == jar["url"]             # the address that answered goes first


async def test_todo_tick_and_create(hass: HomeAssistant, jar) -> None:
    fam, tasks = jar["fam"], jar["tasks"]
    p = fam.people
    mine = tasks.add(p["avi"], "Dentist", p["avi"])                         # private: not on the panel
    laundry = tasks.add(p["dana"], "Hang the laundry", p["yoni"])
    room = tasks.add(p["dana"], "Tidy the room", [p["yoni"], p["maya"]], mode="all")
    from custom_components.jar.api import parse_link
    token, urls = parse_link(link(jar))
    entry = MockConfigEntry(domain="jar", unique_id="jar",
                            data={"token": token, "urls": urls, "allow_control": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    yoni = hass.states.get("todo.jar_yoni")
    assert yoni is not None, [s.entity_id for s in hass.states.async_all()]
    assert yoni.state == "2"                                                # two open tasks
    items = await hass.services.async_call(TODO, "get_items", {}, target={"entity_id": "todo.jar_yoni"},
                                           blocking=True, return_response=True)
    titles = {i["summary"] for i in items["todo.jar_yoni"]["items"]}
    assert titles == {"Hang the laundry", "Tidy the room"}
    assert "Dentist" not in str(await hass.services.async_call(
        TODO, "get_items", {}, target={"entity_id": "todo.jar_avi"}, blocking=True, return_response=True))

    await hass.services.async_call(TODO, "update_item", {"item": laundry["id"], "status": "completed"},
                                   target={"entity_id": "todo.jar_yoni"}, blocking=True)
    t = next(x for x in tasks.snapshot(p["avi"])["tasks"] if x["id"] == laundry["id"])
    assert (t["status"], t["done_by"]) == ("done", "yoni")

    await hass.services.async_call(TODO, "update_item", {"item": room["id"], "status": "completed"},
                                   target={"entity_id": "todo.jar_maya"}, blocking=True)
    t = next(x for x in tasks.snapshot(p["avi"])["tasks"] if x["id"] == room["id"])
    assert (t["status"], list(t["done_parts"])) == ("open", ["maya"])      # Maya's part only

    await hass.services.async_call(TODO, "add_item", {"item": "Feed the cat", "due_date": "2026-10-26"},
                                   target={"entity_id": "todo.jar_maya"}, blocking=True)
    new = [x for x in tasks.snapshot(p["maya"])["tasks"] if x["title"] == "Feed the cat"]
    assert new and new[0]["created_by"] == "home" and new[0]["due"] == "2026-10-26"

    r = await hass.services.async_call("jar", "add_task", {"title": "Take out the trash", "people": ["Yoni", "maya"]},
                                       blocking=True, return_response=True)
    t = next(x for x in tasks.snapshot(p["avi"])["tasks"] if x["id"] == r["id"])
    assert t["assignees"] == ["yoni", "maya"]
    assert hass.states.get("sensor.jar_yoni_coins_this_week") is not None
    assert mine["id"] not in {x["id"] for x in tasks.snapshot(fam.home)["tasks"]}


async def test_control_links_a_jar_user(hass: HomeAssistant, jar, hass_owner_user) -> None:
    from custom_components.jar.api import parse_link
    await hass.config.async_update(external_url="https://ha.example.ts.net")
    token, urls = parse_link(link(jar))
    entry = MockConfigEntry(domain="jar", unique_id="jar", data={"token": token, "urls": urls, "allow_control": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    saved = jar["server"].home_link()
    assert saved["url"] == "https://ha.example.ts.net"
    user = await hass.auth.async_get_user(entry.data["ha_user_id"])
    assert user is not None and user.name == "Jar" and not user.is_admin
    refresh = hass.auth.async_validate_access_token(saved["token"])
    assert refresh is not None and refresh.user.id == user.id

    await hass.config_entries.async_remove(entry.entry_id)                  # removing it takes access away
    await hass.async_block_till_done()
    assert jar["server"].home_link() == {}
    assert await hass.auth.async_get_user(user.id) is None
