"""v0.5.55: bare look self; version/about; time/uptime; whoami; pong version."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(types)
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)
    return m


def test_format_uptime_unit():
    from network.message_handler import _format_uptime

    assert _format_uptime(0) == "0s"
    assert _format_uptime(45) == "45s"
    assert _format_uptime(65) == "1m 05s"
    assert _format_uptime(3661) == "1h 01m 01s"


def test_bare_look_is_self(tmp_path, monkeypatch):
    db_path = tmp_path / "lookself.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ls@ex.com", "LsU", "LookSelfHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "look"}))
                m = await recv_until(ws, "look", "error")
                assert m.get("type") == "look", m
                p = m.get("player") or {}
                assert p.get("id") == ca["id"], p
                assert str(p.get("name") or "") == "LookSelfHero", p
                assert p.get("nearby") is True, p
                assert p.get("zone") in ("town", "field", "dungeon"), p

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_and_about(tmp_path, monkeypatch):
    db_path = tmp_path / "ver.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vu", "VerHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "version"}))
                m = await recv_until(ws, "version", "error")
                assert m.get("type") == "version", m
                assert m.get("version") == config.VERSION, m
                assert m.get("service") == "dq1-mmo", m
                assert isinstance(m.get("uptime"), int), m
                assert m.get("uptime") >= 0, m
                assert isinstance(m.get("zones"), dict), m
                await ws.send(json.dumps({"type": "about"}))
                m2 = await recv_until(ws, "version", "error")
                assert m2.get("type") == "version", m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_time_uptime(tmp_path, monkeypatch):
    db_path = tmp_path / "tm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "t@ex.com", "Tu", "TimeHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "time"}))
                m = await recv_until(ws, "time", "error")
                assert m.get("type") == "time", m
                assert m.get("server_t") is not None, m
                assert isinstance(m.get("uptime"), int), m
                assert m.get("uptime_hms"), m
                assert m.get("version") == config.VERSION, m
                await ws.send(json.dumps({"type": "uptime"}))
                m2 = await recv_until(ws, "time", "error")
                assert m2.get("type") == "time", m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whoami_status(tmp_path, monkeypatch):
    db_path = tmp_path / "whoami.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w@ex.com", "Wu", "WhoamiHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "whoami"}))
                m = await recv_until(ws, "status", "error")
                assert m.get("type") == "status", m
                ch = m.get("character") or {}
                assert ch.get("name") == "WhoamiHero", ch
                you = m.get("you") or {}
                assert you.get("zone") in ("town", "field", "dungeon", None) or "zone" in you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_pong_includes_version_and_uptime(tmp_path, monkeypatch):
    db_path = tmp_path / "pong.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pu", "PongHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "ping", "t": 42}))
                m = await recv_until(ws, "pong")
                assert m.get("t") == 42, m
                assert m.get("version") == config.VERSION, m
                assert isinstance(m.get("uptime"), int), m
                assert m.get("uptime") >= 0, m
                assert m.get("session_id") is not None, m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_mentions_version_time(tmp_path, monkeypatch):
    db_path = tmp_path / "helpvt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hu", "HelpHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                m = await recv_until(ws, "help", "error")
                cmds = {c.get("cmd") for c in (m.get("commands") or [])}
                assert "version" in cmds, cmds
                assert "time" in cmds, cmds
                assert m.get("version") == config.VERSION, m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_health_includes_uptime(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod
    import urllib.request

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, _ws = start_server()
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
            body = json.loads(resp.read().decode())
        assert body.get("status") == "ok", body
        assert body.get("version") == config.VERSION, body
        assert isinstance(body.get("uptime"), int), body
        assert body.get("uptime") >= 0, body
    finally:
        stop_server(server)
