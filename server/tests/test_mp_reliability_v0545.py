"""v0.5.45 multiplayer reliability: zone roster, chat/emote self-echo, ignore names, pong."""

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
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_zone_roster_unit():
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()
    mgr._connections[1] = object()  # type: ignore[assignment]
    mgr._connections[2] = object()  # type: ignore[assignment]
    mgr._meta[1] = {
        "id": 1,
        "name": "A",
        "x": 2.0,
        "y": 2.0,
        "map_id": 0,
        "level": 1,
        "in_combat": False,
        "last_seen": time.monotonic(),
    }
    mgr._meta[2] = {
        "id": 2,
        "name": "B",
        "x": 3.0,
        "y": 2.0,
        "map_id": 0,
        "level": 2,
        "in_combat": False,
        "last_seen": time.monotonic(),
    }
    cards = mgr.zone_roster(1, include_self=True)
    names = {c["name"] for c in cards}
    assert names == {"A", "B"}
    # Orphan meta (no socket) must not appear
    mgr._meta[3] = {
        "id": 3,
        "name": "Ghost",
        "x": 2.0,
        "y": 2.0,
        "map_id": 0,
        "level": 1,
        "in_combat": False,
        "last_seen": time.monotonic(),
    }
    cards2 = mgr.zone_roster(1, include_self=True)
    assert all(c["name"] != "Ghost" for c in cards2)


def test_ignore_names_survive_disconnect(tmp_path, monkeypatch):
    """Ignore list keeps cached name after target goes offline."""
    db_path = tmp_path / "igname.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ia@ex.com", "IaU", "IgAlice")
        tb, cb = register_char(base, "ib@ex.com", "IbU", "IgBob")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
                async with websockets.connect(ws_url) as wb:
                    await auth(wb, tb, cb["id"])
                    await wa.send(json.dumps({"type": "ignore", "name": "IgBob"}))
                    ig = await recv_until(wa, "ignore", "error")
                    assert ig.get("ok") is True, ig
                # Bob disconnected — Alice still sees name on ignore list
                await asyncio.sleep(0.15)
                await wa.send(json.dumps({"type": "ignores"}))
                lst = await recv_until(wa, "ignore", "error")
                players = lst.get("ignores") or lst.get("players") or []
                assert any(
                    (p.get("name") == "IgBob" or p.get("id") == cb["id"])
                    and p.get("name") != "?"
                    for p in players
                ), lst

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_includes_players_roster(tmp_path, monkeypatch):
    db_path = tmp_path / "zrost.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "ZaU", "ZoneA")
        tb, cb = register_char(base, "zb@ex.com", "ZbU", "ZoneB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "zone"}))
                m = await recv_until(wa, "zone", "error")
                assert m.get("type") == "zone", m
                players = m.get("players") or []
                names = {p.get("name") for p in players}
                assert "ZoneA" in names and "ZoneB" in names, m
                assert int(m.get("zone_count") or 0) >= 2, m
                assert "2" in str(m.get("message") or "") or "here" in str(
                    m.get("message") or ""
                ).lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_nearby_and_zone_chat_self_echo_once(tmp_path, monkeypatch):
    """Nearby/zone/global: sender gets exactly one chat echo."""
    db_path = tmp_path / "echo.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "ec@ex.com", "EcU", "EchoMe")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                for channel, text in (
                    ("global", "g1"),
                    ("nearby", "n1"),
                    ("zone", "z1"),
                ):
                    await asyncio.sleep(0.75)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "chat",
                                "channel": channel,
                                "text": text,
                            }
                        )
                    )
                    m = await recv_until(ws, "chat", "error")
                    assert m.get("type") == "chat", m
                    assert m.get("text") == text, m
                    assert m.get("channel") == channel, m
                    extras = await drain(ws, 0.2)
                    dups = [
                        x
                        for x in extras
                        if x.get("type") == "chat" and x.get("text") == text
                    ]
                    assert not dups, (channel, dups)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_emote_self_echo(tmp_path, monkeypatch):
    db_path = tmp_path / "emote.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "em@ex.com", "EmU", "EmoteHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                m = await recv_until(ws, "emote", "error")
                assert m.get("type") == "emote", m
                assert m.get("emote") == "wave", m
                assert m.get("name") == "EmoteHero", m
                extras = await drain(ws, 0.2)
                dups = [x for x in extras if x.get("type") == "emote"]
                assert not dups, dups

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_pong_includes_zones_and_nearby(tmp_path, monkeypatch):
    db_path = tmp_path / "pong.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "pa@ex.com", "PaU", "PongA")
        tb, cb = register_char(base, "pb@ex.com", "PbU", "PongB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "ping", "t": 12345}))
                p = await recv_until(wa, "pong")
                assert p.get("t") == 12345, p
                assert int(p.get("online") or 0) >= 2, p
                assert isinstance(p.get("zones"), dict), p
                assert p.get("zones").get("town", 0) >= 1, p
                assert int(p.get("nearby_count") or 0) >= 1, p
                assert p.get("session_id") is not None, p

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_two_player_nearby_chat_delivery(tmp_path, monkeypatch):
    """Peer hears nearby say; sender hears once."""
    db_path = tmp_path / "nchat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "na@ex.com", "NaU", "NearA")
        tb, cb = register_char(base, "nb@ex.com", "NbU", "NearB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(
                    json.dumps(
                        {
                            "type": "say",
                            "text": "hello near",
                        }
                    )
                )
                ca_m = await recv_until(wa, "chat", "error")
                cb_m = await recv_until(wb, "chat", "error")
                assert ca_m.get("text") == "hello near", ca_m
                assert ca_m.get("channel") == "nearby", ca_m
                assert cb_m.get("text") == "hello near", cb_m
                assert cb_m.get("name") == "NearA", cb_m

        asyncio.run(flow())
    finally:
        stop_server(server)
