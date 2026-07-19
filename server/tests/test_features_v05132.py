"""v0.5.132: AFK WS · busy/back census messages."""

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


def test_afk_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "afk@ex.com", "Af", "AfkHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(
                    json.dumps({"type": "afk", "reason": "lunch break"})
                )
                m = await recv_until(ws, "afk", "error")
                assert m.get("type") == "afk", m
                assert m.get("afk") is True
                assert m.get("afk_message") == "lunch break" or "lunch" in str(
                    m.get("afk_message") or m.get("message") or ""
                )
                assert isinstance(m.get("message"), str)
                assert "AFK" in m["message"]
                assert "online" in m
                assert "afk_count" in m
                assert "nearby_count" in m

                await ws.send(json.dumps({"type": "busy", "text": "meeting"}))
                m2 = await recv_until(ws, "afk", "error")
                assert m2.get("afk") is True

                await ws.send(json.dumps({"type": "back"}))
                m3 = await recv_until(ws, "afk", "error")
                assert m3.get("afk") is False
                assert "Welcome back" in (m3.get("message") or "")

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
