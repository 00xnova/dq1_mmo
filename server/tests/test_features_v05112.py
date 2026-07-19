"""v0.5.112: social nearby/far badges · whisper delivery · version."""

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


def test_pending_near_far_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "nearfar.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "n@ex.com", "Nn", "NearA")
        tb, cb = register_char(base, "f@ex.com", "Ff", "FarB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "FarB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await wa.send(json.dumps({"type": "pending"}))
                pend = await recv_until(wa, "pending", "error")
                assert pend.get("type") == "pending", pend
                outg = pend.get("outgoing") or {}
                assert "nearby" in outg, outg
                # both spawn town — usually nearby
                assert isinstance(outg.get("nearby"), bool), outg
                msg = str(pend.get("message") or "")
                assert "near" in msg.lower() or "far" in msg.lower() or "offline" in msg.lower()

                await wa.send(json.dumps({"type": "social"}))
                soc = await recv_until(wa, "social", "error")
                assert soc.get("type") == "social"
                inv_to = soc.get("invite_to") or {}
                if inv_to.get("online"):
                    assert "nearby" in inv_to, inv_to

                await wa.send(json.dumps({"type": "version"}))
                v = await recv_until(wa, "version", "about", "error")
                assert str(v.get("version") or "").startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_r_still_works_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "wr.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w1@ex.com", "Ww", "WhA")
        tb, cb = register_char(base, "w2@ex.com", "Xx", "WhB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "whisper", "to": "WhB", "text": "yo"}))
                r = await recv_until(wa, "chat", "error")
                if r.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(r.get("retry_after") or 1.0) + 0.1)
                    await wa.send(
                        json.dumps({"type": "whisper", "to": "WhB", "text": "yo"})
                    )
                    r = await recv_until(wa, "chat", "error")
                assert r.get("type") == "chat" and r.get("channel") == "whisper", r
                got = await recv_until(wb, "chat", "error")
                assert got.get("channel") == "whisper"

        asyncio.run(flow())
    finally:
        stop_server(server)
