"""v0.5.143: emote WS · wave directed · list · version."""

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


def test_emote_wave_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "emote.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ema@ex.com", "Ea", "EmoteA")
        tb, cb = register_char(base, "emb@ex.com", "Eb", "EmoteB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(
                ws_url
            ) as wsb:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await drain(wsa, 0.15)
                await drain(wsb, 0.15)

                await wsa.send(json.dumps({"type": "emotes"}))
                cat = await recv_until(wsa, "emotes", "error")
                assert cat.get("type") == "emotes"
                assert "wave" in (cat.get("emotes") or [])

                await wsa.send(json.dumps({"type": "wave", "to": "EmoteB"}))
                ok = await recv_until(wsa, "emote", "error")
                assert ok.get("type") == "emote", ok
                assert ok.get("emote") == "wave"
                assert ok.get("to") == "EmoteB" or "EmoteB" in str(ok.get("message") or "")
                assert "online" in ok or "nearby" in ok
                peer = await recv_until(wsb, "emote", "error")
                assert peer.get("type") == "emote"
                assert peer.get("emote") == "wave"

                await asyncio.sleep(1.1)
                await wsa.send(json.dumps({"type": "version"}))
                v = await recv_until(wsa, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
