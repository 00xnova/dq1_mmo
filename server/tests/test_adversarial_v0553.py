"""v0.5.53: look includes zone when far; empty chat does not block next message."""

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


async def drain(ws, seconds=0.15):
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


def test_empty_chat_then_real_chat(tmp_path, monkeypatch):
    db_path = tmp_path / "empty2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "e@ex.com", "Eu", "Empty2")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "chat", "channel": "system", "text": "x"}))
                e1 = await recv_until(ws, "error", "chat")
                assert e1.get("type") == "error", e1
                await ws.send(json.dumps({"type": "chat", "text": "  \t\n  "}))
                e2 = await recv_until(ws, "error", "chat")
                assert e2.get("type") == "error", e2
                assert "empty" in str(e2.get("reason") or "").lower(), e2
                await ws.send(
                    json.dumps({"type": "chat", "channel": "global", "text": "after-ws"})
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert m.get("text") == "after-ws", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_look_includes_zone(tmp_path, monkeypatch):
    db_path = tmp_path / "lookz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "la@ex.com", "La", "LookA")
        tb, cb = register_char(base, "lb@ex.com", "Lb", "LookB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "look", "name": "LookB"}))
                m = await recv_until(wa, "look", "error")
                assert m.get("type") == "look", m
                player = m.get("player") or {}
                assert player.get("name") == "LookB", player
                assert player.get("zone") in ("town", "field", "dungeon"), player
                # Nearby at spawn — may have coords
                assert "nearby" in player, player

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_look_ambiguous_prefix(tmp_path, monkeypatch):
    db_path = tmp_path / "looka.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "Sam")
        tb, cb = register_char(base, "sy@ex.com", "Sy", "Sammy")
        tc, cc = register_char(base, "sc@ex.com", "Sc", "Seer")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await auth(wc, tc, cc["id"])
                await wc.send(json.dumps({"type": "look", "name": "Sa"}))
                err = await recv_until(wc, "error", "look")
                assert err.get("type") == "error", err
                assert err.get("reason") == "name ambiguous", err

        asyncio.run(flow())
    finally:
        stop_server(server)
