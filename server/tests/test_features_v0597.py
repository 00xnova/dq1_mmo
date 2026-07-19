"""v0.5.97: poke/nudge, census reliability, regressions."""

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


def test_poke_nudge_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "poke.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p1@ex.com", "P1", "PokeA")
        tb, cb = register_char(base, "p2@ex.com", "P2", "PokeB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "poke", "to": "PokeA"}))
                e1 = await recv_until(wa, "error", "poke")
                assert e1.get("type") == "error"
                assert "yourself" in str(e1.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "poke"}))
                e2 = await recv_until(wa, "error", "poke")
                assert e2.get("type") == "error"

                await wa.send(json.dumps({"type": "poke", "to": "PokeB"}))
                ok = await recv_until(wa, "poke", "error")
                assert ok.get("type") == "poke", ok
                assert "PokeB" in str(ok.get("message") or "")
                peer = await recv_until(wb, "poke", "error")
                assert peer.get("type") == "poke"
                assert peer.get("from") == "PokeA"
                assert "attention" in str(peer.get("message") or "").lower()

                # /r after poke
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "reply", "text": "what?"}))
                r = await recv_until(wb, "chat", "error")
                assert r.get("channel") == "whisper"

                # Ignore blocks poke without rate burn
                await wb.send(json.dumps({"type": "ignore", "name": "PokeA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "nudge", "to": "PokeB"}))
                e3 = await recv_until(wa, "error", "poke")
                assert e3.get("type") == "error"
                assert "unavailable" in str(e3.get("reason") or "").lower()
                assert e3.get("reason") != "chat_rate_limit"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_poke_bool_id_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "pokebool.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpPoke")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "poke", "to_id": True}))
                err = await recv_until(ws, "error", "poke")
                assert err.get("type") == "error"
                assert "not found" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "poke" in cmds or "nudge" in cmds, cmds

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_fighting_includes_combat_count(tmp_path, monkeypatch):
    db_path = tmp_path / "fght.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FightPeek")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 3})
                )
                await recv_until(ws, "combat_start", "error")
                await ws.send(json.dumps({"type": "fighting"}))
                f = await recv_until(ws, "fighting", "error")
                assert "combat_count" in f, f
                assert int(f.get("combat_count") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)
