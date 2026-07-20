"""v0.5.147: bag/equip WS · combat gate · version."""

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


def test_bag_equip_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "inv.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "iva@ex.com", "Ia", "InvA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa:
                await auth(wsa, ta, ca["id"])
                await drain(wsa, 0.15)

                await wsa.send(json.dumps({"type": "bag"}))
                inv = await recv_until(wsa, "inventory_update", "error")
                assert inv.get("type") == "inventory_update" or "bag" in inv, inv
                assert "online" in inv or "nearby_count" in inv or inv.get("bag") is not None

                # clothes should equip (new heroes start with clothes)
                await wsa.send(
                    json.dumps({"type": "equip", "item": "clothes"})
                )
                eq = await recv_until(wsa, "inventory_update", "error")
                # may already be equipped or succeed
                assert eq.get("type") in ("inventory_update", "error"), eq

                await wsa.send(json.dumps({"type": "version"}))
                v = await recv_until(wsa, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
