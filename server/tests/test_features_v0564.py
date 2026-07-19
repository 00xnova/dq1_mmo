"""v0.5.64: status.you afk/idle; bag/inv aliases; gold; spells."""

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
    await drain(ws, 0.12)
    return m


def test_status_you_includes_afk_when_afk(tmp_path, monkeypatch):
    """Regression: status.you omitted afk/idle after /afk."""
    db_path = tmp_path / "stafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "StatAfk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk"}))
                await recv_until(ws, "afk", "error")
                await ws.send(json.dumps({"type": "status"}))
                m = await recv_until(ws, "status", "error")
                assert m.get("type") == "status", m
                you = m.get("you") or {}
                assert you.get("afk") is True, you
                assert you.get("idle") is True, you
                assert you.get("session_id") is not None, you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_bag_inv_items_aliases(tmp_path, monkeypatch):
    db_path = tmp_path / "bag.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ba@ex.com", "Ba", "BagHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for t in ("bag", "inv", "items", "inventory"):
                    await ws.send(json.dumps({"type": t}))
                    m = await recv_until(ws, "inventory_update", "error")
                    assert m.get("type") == "inventory_update", (t, m)
                    assert isinstance(m.get("items"), list), m
                    assert isinstance(m.get("bag"), dict), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_gold_command(tmp_path, monkeypatch):
    db_path = tmp_path / "gold.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "g@ex.com", "Gu", "GoldHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for t in ("gold", "money", "wallet"):
                    await ws.send(json.dumps({"type": t}))
                    m = await recv_until(ws, "gold", "error")
                    assert m.get("type") == "gold", (t, m)
                    assert m.get("gold") is not None, m
                    assert "G" in str(m.get("message") or ""), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_spells_command(tmp_path, monkeypatch):
    db_path = tmp_path / "sp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sp@ex.com", "Spu", "SpellHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "spells"}))
                m = await recv_until(ws, "spells", "error")
                assert m.get("type") == "spells", m
                assert isinstance(m.get("battle"), list), m
                assert isinstance(m.get("field"), list), m
                assert int(m.get("level") or 0) >= 1, m
                assert m.get("message"), m
                await ws.send(json.dumps({"type": "magic"}))
                m2 = await recv_until(ws, "spells", "error")
                assert m2.get("type") == "spells", m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_mentions_gold_spells_bag(tmp_path, monkeypatch):
    db_path = tmp_path / "hlp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hu", "Help64")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                m = await recv_until(ws, "help")
                cmds = {c.get("cmd") for c in (m.get("commands") or [])}
                assert "gold" in cmds, cmds
                assert "spells" in cmds, cmds
                assert "inventory" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_status_you_not_afk_by_default(tmp_path, monkeypatch):
    db_path = tmp_path / "st0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s0@ex.com", "S0u", "StatOk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "status"}))
                m = await recv_until(ws, "status")
                you = m.get("you") or {}
                assert you.get("afk") is False, you
                assert you.get("idle") is False, you

        asyncio.run(flow())
    finally:
        stop_server(server)
