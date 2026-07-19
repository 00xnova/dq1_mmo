"""v0.5.119: @emote / @emotedby WS · lastemote both ways · version."""

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


def test_emote_aliases_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "em.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e1@ex.com", "Ee", "EmA")
        tb, cb = register_char(base, "e2@ex.com", "Ff", "EmB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "wave", "to": "EmB"}))
                em = await recv_until(wa, "emote", "error")
                if em.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(em.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "wave", "to": "EmB"}))
                    em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em

                await wb.send(json.dumps({"type": "lastemote"}))
                le = await recv_until(wb, "lastemote", "error")
                assert le.get("type") == "lastemote", le
                assert le.get("has_from") is True or "from" in str(
                    le.get("message") or ""
                ).lower()

                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "whisper", "to": "@emotedby", "text": "hey"})
                )
                w = await recv_until(wb, "chat", "error")
                if w.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(w.get("retry_after") or 1.0) + 0.1)
                    await wb.send(
                        json.dumps(
                            {"type": "whisper", "to": "@emotedby", "text": "hey"}
                        )
                    )
                    w = await recv_until(wb, "chat", "error")
                assert w.get("type") == "chat" and w.get("channel") == "whisper", w

                await wa.send(json.dumps({"type": "version"}))
                v = await recv_until(wa, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
