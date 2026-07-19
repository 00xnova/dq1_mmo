"""v0.5.98: askwhere location request + AFK restore on failed private delivery."""

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


def test_askwhere_and_share_loop(tmp_path, monkeypatch):
    db_path = tmp_path / "askw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a1@ex.com", "A1", "AskA")
        tb, cb = register_char(base, "b1@ex.com", "B1", "AskB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "askwhere", "to": "AskA"}))
                e1 = await recv_until(wa, "error", "askwhere")
                assert e1.get("type") == "error"
                assert "yourself" in str(e1.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "askwhere"}))
                e2 = await recv_until(wa, "error", "askwhere")
                assert e2.get("type") == "error"

                await wa.send(json.dumps({"type": "locate", "to": "AskB"}))
                ok = await recv_until(wa, "askwhere", "error")
                assert ok.get("type") == "askwhere", ok
                assert "AskB" in str(ok.get("message") or "")

                peer = await recv_until(wb, "askwhere", "error")
                assert peer.get("type") == "askwhere"
                assert peer.get("from") == "AskA"
                assert "where" in str(peer.get("message") or "").lower()
                assert "share" in str(peer.get("message") or "").lower()

                # B can /share @last after askwhere
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "share", "to": "@last"}))
                sh = await recv_until(wb, "share", "error")
                assert sh.get("type") == "share", sh
                got = await recv_until(wa, "share", "error")
                assert got.get("type") == "share"
                assert got.get("from") == "AskB"
                assert got.get("zone") is not None or got.get("x") is not None

                # Ignore blocks without rate burn
                await wb.send(json.dumps({"type": "ignore", "name": "AskA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "askwhere", "to": "AskB"}))
                e3 = await recv_until(wa, "error", "askwhere")
                assert e3.get("type") == "error"
                assert "unavailable" in str(e3.get("reason") or "").lower()
                assert e3.get("reason") != "chat_rate_limit"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_askwhere_help_and_bool_id(tmp_path, monkeypatch):
    db_path = tmp_path / "askhelp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpAsk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "askwhere", "to_id": True}))
                err = await recv_until(ws, "error", "askwhere")
                assert err.get("type") == "error"
                assert "not found" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "askwhere" in cmds or "locate" in cmds, cmds

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_who_still_has_combat_and_afk_census(tmp_path, monkeypatch):
    """Regression: old census fields remain on /who after social expansion."""
    db_path = tmp_path / "whoreg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w@ex.com", "Ww", "WhoReg")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk", "text": "brb"}))
                await recv_until(ws, "status", "player_update", "afk", "error")
                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who", "error")
                assert "afk_count" in who
                assert int(who.get("afk_count") or 0) >= 1
                assert "combat_count" in who
                you = who.get("you") or {}
                assert you.get("afk") is True or int(who.get("afk_count") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)
