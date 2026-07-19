"""Multiplayer look/examine + online pulse debounce + field-spell-in-combat guard."""

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


def test_online_pulse_debounce_unit():
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
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=1)
        # First pulse always sends
        await mgr.broadcast_online()
        n1 = sum(1 for m in a.sent if m.get("type") == "online")
        assert n1 >= 1
        # Rapid second pulse is debounced then flushed shortly
        a.sent.clear()
        await mgr.broadcast_online()
        n2 = sum(1 for m in a.sent if m.get("type") == "online")
        assert n2 == 0
        assert mgr._online_pulse_pending is True
        await asyncio.sleep(mgr.ONLINE_PULSE_MIN_INTERVAL + 0.05)
        n3 = sum(1 for m in a.sent if m.get("type") == "online")
        assert n3 == 1

        # soft grace purge
        mgr._soft_grace[99] = {"repel_steps": 1, "expires": time.monotonic() - 1}
        assert mgr.purge_expired_soft_grace() == 1
        assert 99 not in mgr._soft_grace

    asyncio.run(scenario())


def test_look_nearby_and_far(tmp_path, monkeypatch):
    db_path = tmp_path / "look.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "la@ex.com", "LookA", "LookAlice")
        token_b, ch_b = register_char(base, "lb@ex.com", "LookB", "LookBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, token_a, ch_a), (wb, token_b, ch_b)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")

                # Both at spawn — nearby
                await wa.send(json.dumps({"type": "look", "name": "LookBob"}))
                look = await recv_until(wa, "look", "error")
                assert look["type"] == "look", look
                p = look["player"]
                assert p["name"] == "LookBob"
                assert p["nearby"] is True
                assert "x" in p and "y" in p

                # Missing / offline player (live resolve — not online)
                await wa.send(json.dumps({"type": "look", "name": "Nobody"}))
                err = await recv_until(wa, "error")
                assert err["reason"] in ("player not online", "player not found"), err

                # by id
                await wa.send(
                    json.dumps({"type": "examine", "player_id": ch_b["id"]})
                )
                look2 = await recv_until(wa, "look")
                assert look2["player"]["id"] == ch_b["id"]

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_field_spell_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "fc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "fc@ex.com", "FcU", "FcHero")
        import sqlite3

        con = sqlite3.connect(str(db_path))
        con.execute(
            "UPDATE characters SET level=13, max_mp=40, current_mp=40 WHERE id=?",
            (ch["id"],),
        )
        con.commit()
        con.close()

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(
                    json.dumps(
                        {"type": "debug_encounter", "enemy": "slime", "seed": 1}
                    )
                )
                await recv_until(ws, "combat_start")
                await ws.send(json.dumps({"type": "use_spell", "spell": "return"}))
                err = await recv_until(ws, "error", "spell_cast", "combat_update")
                # Should not cast field return mid-fight
                assert err.get("type") != "spell_cast" or not err.get("teleported")
                if err.get("type") == "error":
                    assert err.get("reason") in (
                        "in combat",
                        "illegal action",
                        "wait for your turn",
                    )

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_four_player_presence_stress(tmp_path, monkeypatch):
    """Four clients online; who/look/sync remain consistent."""
    db_path = tmp_path / "stress.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        clients = [
            register_char(base, f"s{i}@ex.com", f"SU{i}", f"Stress{i}")
            for i in range(4)
        ]

        async def flow():
            import websockets

            sockets = []
            for tok, ch in clients:
                ws = await websockets.connect(ws_url)
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": tok, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                sockets.append(ws)

            await sockets[0].send(json.dumps({"type": "who"}))
            who = await recv_until(sockets[0], "who")
            assert who["online"] == 4
            assert len(who.get("roster") or []) == 4

            await sockets[0].send(
                json.dumps({"type": "look", "name": clients[2][1]["name"]})
            )
            look = await recv_until(sockets[0], "look")
            assert look["player"]["name"] == clients[2][1]["name"]

            await sockets[1].send(json.dumps({"type": "sync"}))
            snap = await recv_until(sockets[1], "world_state")
            assert snap.get("online") == 4

            for ws in sockets:
                await ws.close()

        asyncio.run(flow())
    finally:
        stop_server(server)
