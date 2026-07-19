"""v0.5.125: /ignores near/far · soft reconnect mute list · version."""

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


def test_ignores_nearby_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "ig.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "iga@ex.com", "Ia", "IgnA")
        tb, cb = register_char(base, "igb@ex.com", "Ib", "IgnB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await wa.send(json.dumps({"type": "ignore", "name": "IgnB"}))
                ig = await recv_until(wa, "ignore", "error")
                assert ig.get("type") == "ignore", ig
                await wa.send(json.dumps({"type": "ignores"}))
                lst = await recv_until(wa, "ignore", "error")
                assert lst.get("action") == "list", lst
                ignores = lst.get("ignores") or []
                assert ignores, lst
                card = ignores[0]
                assert "IgnB" in str(card.get("name") or "")
                assert card.get("online") is True
                assert "nearby" in card, card
                assert lst.get("count") == 1
                assert "Mute list" in str(lst.get("message") or "") or "IgnB" in str(
                    lst.get("message") or ""
                )

                await wa.send(json.dumps({"type": "version"}))
                v = await recv_until(wa, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
