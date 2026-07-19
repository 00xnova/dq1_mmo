"""v0.5.92: meetup invite, client-facing peeks, regressions."""

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


def test_invite_meet_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "invite.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "i1@ex.com", "I1", "InvA")
        tb, cb = register_char(base, "i2@ex.com", "I2", "InvB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Self
                await wa.send(json.dumps({"type": "invite", "to": "InvA"}))
                e1 = await recv_until(wa, "error", "invite")
                assert e1.get("type") == "error"
                assert "yourself" in str(e1.get("reason") or "").lower()

                # Offline
                await wa.send(json.dumps({"type": "meet", "to": "Nobody"}))
                e2 = await recv_until(wa, "error", "invite")
                assert e2.get("type") == "error"
                assert "online" in str(e2.get("reason") or "").lower()

                # Bare invite without peer
                await wa.send(json.dumps({"type": "invite"}))
                e3 = await recv_until(wa, "error", "invite")
                assert e3.get("type") == "error"

                # Success
                await wa.send(json.dumps({"type": "invite", "to": "InvB"}))
                ok = await recv_until(wa, "invite", "error")
                assert ok.get("type") == "invite", ok
                assert "InvB" in str(ok.get("message") or "")
                assert ok.get("to_id") == cb["id"]
                assert ok.get("from_id") == ca["id"]

                peer = await recv_until(wb, "invite", "error")
                assert peer.get("type") == "invite"
                assert peer.get("from") == "InvA"
                assert "meet" in str(peer.get("message") or "").lower()
                assert peer.get("zone") in ("town", "field", "dungeon", None)

                # @last after invite (notes whisper peer)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "meet", "to": "@last"}))
                ok2 = await recv_until(wa, "invite", "error")
                assert ok2.get("type") == "invite", ok2
                assert ok2.get("to_id") == cb["id"]
                await recv_until(wb, "invite", "error")

                # Ignore blocks invite (before rate)
                await wb.send(json.dumps({"type": "ignore", "name": "InvA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "invite", "to": "InvB"}))
                e4 = await recv_until(wa, "error", "invite")
                assert e4.get("type") == "error"
                assert "unavailable" in str(e4.get("reason") or "").lower()
                assert e4.get("reason") != "chat_rate_limit"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_invite_help_and_busy_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "invhelp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpInv")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "invite" in cmds, cmds

                await ws.send(json.dumps({"type": "busy", "text": "brb"}))
                afk = await recv_until(ws, "afk", "error")
                assert afk.get("afk") is True
                assert afk.get("afk_message") == "brb"

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                ver = str(v.get("version") or config.VERSION)
                assert ver.startswith("0.5."), ver

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_invite_bool_id_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "invbool.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b@ex.com", "Bb", "BoolInv")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "invite", "to_id": True}))
                err = await recv_until(ws, "error", "invite")
                assert err.get("type") == "error"
                assert "not found" in str(err.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
