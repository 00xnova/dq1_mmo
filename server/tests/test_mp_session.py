"""Multiplayer session_id, level roster pulse, reconnect presence hygiene."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError(types)
        m = json.loads(await asyncio.wait_for(ws.recv(), rem))
        if m.get("type") in types:
            return m


def test_session_id_on_auth_and_replace():
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t) if isinstance(t, str) else t)

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = WS(), WS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=1)
        s1 = mgr.session_id(1)
        assert s1 is not None and s1 >= 1
        await mgr.connect(1, b, name="A", x=2, y=2, map_id=1)
        s2 = mgr.session_id(1)
        assert s2 is not None and s2 > s1
        assert mgr.owns(1, b)

    asyncio.run(scenario())


def test_auth_ok_includes_session_id(tmp_path, monkeypatch):
    db_path = tmp_path / "sid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "sid@ex.com", "SidU", "SidHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                m = await recv_until(ws, "auth_ok")
                assert m.get("session_id") is not None
                assert int(m["session_id"]) >= 1
                assert m.get("online") is not None
                snap = await recv_until(ws, "world_state")
                assert "players" in snap

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_level_up_pulses_online_roster(tmp_path, monkeypatch):
    """After level publish, online roster should reflect new level."""
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = WS(), WS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=1, level=1)
        await mgr.connect(2, b, name="Peer", x=3, y=2, map_id=1, level=1)
        b.sent.clear()
        await mgr.publish_level(1, 5)
        # peer should get player_update and/or online pulse
        saw_level = False
        saw_online = False
        for m in b.sent:
            if m.get("type") == "player_update" and m.get("level") == 5:
                saw_level = True
            if m.get("type") == "online":
                saw_online = True
                for card in m.get("roster") or []:
                    if card.get("id") == 1:
                        assert card.get("level") == 5
        assert saw_level
        assert saw_online or mgr.get_meta(1)["level"] == 5

    asyncio.run(scenario())


def test_two_player_reconnect_presence(tmp_path, monkeypatch):
    """A disconnects and reconnects; B still has consistent online count."""
    db_path = tmp_path / "rc2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "ra@ex.com", "RaU", "RaHero")
        token_b, ch_b = register_char(base, "rb@ex.com", "RbU", "RbHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await wb.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "token": token_b,
                            "character_id": ch_b["id"],
                        }
                    )
                )
                await recv_until(wb, "auth_ok")
                await recv_until(wb, "world_state")

                async with websockets.connect(ws_url) as wa:
                    await wa.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": token_a,
                                "character_id": ch_a["id"],
                            }
                        )
                    )
                    auth = await recv_until(wa, "auth_ok")
                    assert auth.get("session_id") is not None
                    await recv_until(wa, "world_state")
                    await wb.send(json.dumps({"type": "who"}))
                    who = await recv_until(wb, "who")
                    assert who["online"] == 2

                # A closed — wait for leave pulse
                await asyncio.sleep(0.35)
                await wb.send(json.dumps({"type": "who"}))
                who2 = await recv_until(wb, "who")
                assert who2["online"] == 1

                # A reconnects
                async with websockets.connect(ws_url) as wa2:
                    await wa2.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": token_a,
                                "character_id": ch_a["id"],
                            }
                        )
                    )
                    auth2 = await recv_until(wa2, "auth_ok")
                    assert auth2.get("session_id") is not None
                    await recv_until(wa2, "world_state")
                    await asyncio.sleep(0.25)
                    await wb.send(json.dumps({"type": "who"}))
                    who3 = await recv_until(wb, "who")
                    assert who3["online"] == 2

        asyncio.run(flow())
    finally:
        stop_server(server)
