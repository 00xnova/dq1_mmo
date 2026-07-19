"""v0.5.124: auth restored.played + session timer welcome · version."""

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
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_auth_restored_played_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "rp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "rp@ex.com", "Rp", "RestPlay")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await asyncio.sleep(0.45)
            # Allow server soft-disconnect to finish before rejoin (avoid live-replace race)
            await asyncio.sleep(0.35)

            async with websockets.connect(ws_url) as ws2:
                await ws2.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(ws2.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state" and m.get("restored") is not None:
                        world = m
                assert auth_ok and world
                rest = world.get("restored") or auth_ok.get("restored") or {}
                assert rest.get("played") is True, rest
                welcome = str(auth_ok.get("welcome") or "")
                assert "session timer" in welcome.lower() or "Restored" in welcome, welcome
                await ws2.send(json.dumps({"type": "version"}))
                v = await recv_until(ws2, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_first_join_played_not_restored_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "fj3.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "fj3@ex.com", "Fj", "FirstPlay")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 4.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(ws.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state":
                        world = m
                assert auth_ok and world
                rest = world.get("restored") or auth_ok.get("restored") or {}
                assert rest.get("played") is False or rest.get("played") is None
                welcome = str(auth_ok.get("welcome") or "")
                assert "session timer" not in welcome.lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
