"""v0.5.66: vitals/xp peeks; equip feedback; unequip aliases; sleep; client gaps covered server-side."""

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


async def drain(ws, seconds=0.1):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_vitals_and_xp_peek(tmp_path, monkeypatch):
    db_path = tmp_path / "vit.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "VitHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "hp"}))
                v = await recv_until(ws, "vitals", "error")
                assert v.get("type") == "vitals", v
                assert int(v.get("hp") or 0) > 0 and int(v.get("max_hp") or 0) > 0, v
                assert "HP" in str(v.get("message") or ""), v

                await ws.send(json.dumps({"type": "mp"}))
                v2 = await recv_until(ws, "vitals", "error")
                assert v2.get("type") == "vitals", v2

                await ws.send(json.dumps({"type": "xp"}))
                x = await recv_until(ws, "xp", "error")
                assert x.get("type") == "xp", x
                assert int(x.get("level") or 0) == 1, x
                assert x.get("xp_progress") is not None, x
                assert "Level" in str(x.get("message") or ""), x

                await ws.send(json.dumps({"type": "level"}))
                x2 = await recv_until(ws, "xp", "error")
                assert x2.get("type") == "xp", x2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_equip_message_and_takeoff_alias(tmp_path, monkeypatch):
    db_path = tmp_path / "eq.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EqHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                b = await recv_until(ws, "inventory_update", "error")
                assert b.get("type") == "inventory_update", b

                await ws.send(
                    json.dumps({"type": "equip", "slot": "weapon", "item": "club"})
                )
                eq = await recv_until(ws, "inventory_update", "error")
                assert eq.get("type") == "inventory_update", eq
                assert (eq.get("equipped") or {}).get("item_id") == "club", eq
                assert "Equipped" in str(eq.get("message") or ""), eq
                char = eq.get("character") or {}
                assert char.get("equipment_weapon") == "club", char

                await ws.send(json.dumps({"type": "takeoff", "slot": "weapon"}))
                uq = await recv_until(ws, "inventory_update", "error")
                assert uq.get("type") == "inventory_update", uq
                assert (uq.get("unequipped") or {}).get("item_id") == "club", uq
                assert "Unequipped" in str(uq.get("message") or ""), uq
                char2 = uq.get("character") or {}
                assert not char2.get("equipment_weapon"), char2

                # re-equip then remove alias
                await ws.send(
                    json.dumps({"type": "equip", "slot": "weapon", "item": "club"})
                )
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "remove", "slot": "weapon"}))
                r = await recv_until(ws, "inventory_update", "error")
                assert r.get("type") == "inventory_update", r
                assert (r.get("unequipped") or {}).get("slot") == "weapon", r

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sleep_alias_for_rest(tmp_path, monkeypatch):
    db_path = tmp_path / "sl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "SleepH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Full HP spawn → already rested
                await ws.send(json.dumps({"type": "sleep"}))
                m = await recv_until(ws, "error", "rest_ok", "inn_quote")
                assert m.get("type") == "error", m
                assert "rest" in str(m.get("reason") or "").lower() or "full" in str(
                    m.get("reason") or ""
                ).lower() or "already" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_lists_new_commands(tmp_path, monkeypatch):
    db_path = tmp_path / "hl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = {c.get("cmd") for c in (h.get("commands") or [])}
                assert "hp" in cmds, cmds
                assert "xp" in cmds, cmds
                assert "unequip" in cmds, cmds
                assert "lastwhisper" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_target_afk_still_works(tmp_path, monkeypatch):
    """Regression: AFK whisper flag from v0.5.65."""
    db_path = tmp_path / "w.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "Wa", "WAfkA")
        tb, cb = register_char(base, "wb@ex.com", "Wb", "WAfkB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")
                await asyncio.sleep(0.85)
                await drain(wa)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "WAfkB", "text": "ping"})
                )
                m = await recv_until(wa, "chat", "error")
                assert m.get("target_afk") is True, m

        asyncio.run(flow())
    finally:
        stop_server(server)
