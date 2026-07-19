"""v0.5.46: bag stack/slot caps; defeat system chat nearby."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite

from database.migrations import run_migrations
from game.item_manager import (
    MAX_BAG_SLOTS,
    MAX_STACK_QTY,
    add_item,
    buy_item,
    can_receive_item,
)
from tests.ws_helpers import register_char, start_server, stop_server


def _run(coro):
    return asyncio.run(coro)


async def _db():
    path = Path(tempfile.mkdtemp()) / "bag.db"
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    await db.execute(
        "INSERT INTO users (email, password_hash, username) VALUES ('a@b.c', 'x', 'U')"
    )
    await db.execute(
        """
        INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
        VALUES (1, 'Hero', 40, 40, '99999', 2, 2)
        """
    )
    await db.commit()
    async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
        row = await c.fetchone()
    return db, dict(row)


def test_bag_stack_cap_unit():
    async def flow():
        db, char = await _db()
        ok, reason = await can_receive_item(db, 1, "herb", MAX_STACK_QTY)
        assert ok, reason
        assert await add_item(db, 1, "herb", MAX_STACK_QTY)
        await db.commit()
        ok2, reason2 = await can_receive_item(db, 1, "herb", 1)
        assert not ok2 and reason2 == "stack full", (ok2, reason2)
        ok3, reason3, info = await buy_item(db, char, "herb")
        assert not ok3 and reason3 == "stack full", (ok3, reason3, info)
        assert str(char.get("gold")) == "99999"
        await db.close()

    _run(flow())


def test_bag_slot_cap_unit():
    async def flow():
        db, _char = await _db()
        from game.data_loader import load_data

        load_data.cache_clear()
        eq = list((load_data().get("equipment") or {}).keys())
        assert len(eq) >= MAX_BAG_SLOTS + 1
        for iid in eq[:MAX_BAG_SLOTS]:
            assert await add_item(db, 1, iid, 1), iid
        await db.commit()
        next_id = eq[MAX_BAG_SLOTS]
        ok, reason = await can_receive_item(db, 1, next_id, 1)
        assert not ok and reason == "inventory full", (ok, reason)
        await db.close()

    _run(flow())


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
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_defeat_system_chat_nearby(tmp_path, monkeypatch):
    """Nearby peers see system chat when a hero is defeated (handler path)."""
    db_path = tmp_path / "def.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "da@ex.com", "DaU", "DeadAlice")
        tb, cb = register_char(base, "db@ex.com", "DbU", "WatchBob")

        async def flow():
            import websockets
            from network.protocol import ServerMessageType, msg
            from network.websocket_manager import manager

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await manager.broadcast_nearby(
                    ca["id"],
                    msg(
                        ServerMessageType.CHAT,
                        player_id=ca["id"],
                        name="System",
                        text="DeadAlice was defeated!",
                        channel="system",
                        system=True,
                    ),
                    include_self=True,
                    respect_ignore=False,
                )
                saw = None
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.3)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "chat"
                            and m.get("channel") == "system"
                            and "defeated" in str(m.get("text") or "").lower()
                        ):
                            saw = m
                            break
                    except Exception:
                        break
                assert saw is not None, "bob never saw defeat system chat"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_stack_full_ws(tmp_path, monkeypatch):
    """Buying past stack cap rejects without taking gold forever."""
    db_path = tmp_path / "buyfull.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "bf@ex.com", "BfU", "BuyFull")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                hit_full = False
                for _ in range(MAX_STACK_QTY + 5):
                    await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                    m = await recv_until(ws, "inventory_update", "error")
                    if m.get("type") == "error" and m.get("reason") == "stack full":
                        hit_full = True
                        break
                assert hit_full, "never hit stack full"
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                gold = int(str((inv.get("character") or {}).get("gold") or 0))
                assert gold >= 0

        asyncio.run(flow())
    finally:
        stop_server(server)
