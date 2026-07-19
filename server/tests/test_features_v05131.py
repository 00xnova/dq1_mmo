"""v0.5.131: hud info WS · keys/help/motd census messages."""

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


def test_hud_info_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "hud.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "hud@ex.com", "Hud", "HudHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(json.dumps({"type": "keys"}))
                k = await recv_until(ws, "controls", "error")
                assert k.get("type") == "controls", k
                assert isinstance(k.get("message"), str) and k["message"]
                assert "online" in k
                assert "combat_count" in k

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                assert h.get("type") == "help", h
                assert isinstance(h.get("commands"), list) and h["commands"]
                assert isinstance(h.get("message"), str)
                assert "afk_count" in h

                await ws.send(json.dumps({"type": "motd"}))
                m = await recv_until(ws, "motd", "error")
                assert m.get("type") == "motd", m
                assert "text" in m
                assert isinstance(m.get("message"), str)
                assert "combat_count" in m

                await ws.send(json.dumps({"type": "controls"}))
                k2 = await recv_until(ws, "controls", "error")
                assert k2.get("type") == "controls"

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
