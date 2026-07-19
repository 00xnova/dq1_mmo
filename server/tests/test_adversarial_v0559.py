"""v0.5.59 adversarial: sell qty=0 must not sell; multi-sell; bad qty."""

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


def test_sell_qty_zero_does_not_sell(tmp_path, monkeypatch):
    """Regression: quantity:0 used to sell one unit (ignored qty)."""
    db_path = tmp_path / "s0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s0@ex.com", "S0u", "SellZero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                herbs = next(
                    (i for i in (inv.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                assert herbs is not None, inv
                before = int(herbs.get("quantity") or 0)
                gold_before = str((inv.get("character") or {}).get("gold"))

                await ws.send(
                    json.dumps({"type": "sell", "item": "herb", "quantity": 0})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

                await ws.send(json.dumps({"type": "inventory"}))
                inv2 = await recv_until(ws, "inventory_update")
                herbs2 = next(
                    (
                        i
                        for i in (inv2.get("items") or [])
                        if i.get("item_id") == "herb"
                    ),
                    None,
                )
                assert herbs2 is not None
                assert int(herbs2.get("quantity") or 0) == before
                assert str((inv2.get("character") or {}).get("gold")) == gold_before

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sell_qty_negative(tmp_path, monkeypatch):
    db_path = tmp_path / "sn.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sn@ex.com", "Snu", "SellNeg")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "sell", "item": "herb", "quantity": -3})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sell_multi_qty(tmp_path, monkeypatch):
    db_path = tmp_path / "sm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sm@ex.com", "Smu", "SellMulti")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                herbs = next(
                    (i for i in (inv.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                assert herbs and int(herbs.get("quantity") or 0) >= 2, inv
                before = int(herbs["quantity"])
                gold0 = int(str((inv.get("character") or {}).get("gold") or 0))

                await ws.send(
                    json.dumps({"type": "sell", "item": "herb", "quantity": 2})
                )
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                sold = m.get("sold") or {}
                assert int(sold.get("quantity") or 0) == 2, sold
                assert int(sold.get("gold_gained") or 0) > 0, sold
                herbs2 = next(
                    (i for i in (m.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                if herbs2:
                    assert int(herbs2.get("quantity") or 0) == before - 2
                else:
                    assert before == 2
                gold1 = int(str((m.get("character") or {}).get("gold") or 0))
                assert gold1 == gold0 + int(sold["gold_gained"])

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sell_item_unit_bad_qty():
    import asyncio
    import aiosqlite
    import tempfile
    from pathlib import Path

    from database.migrations import run_migrations
    from game.item_manager import add_item, sell_item

    async def scenario():
        path = Path(tempfile.mkdtemp()) / "u.db"
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        await run_migrations(db)
        await db.execute(
            "INSERT INTO users (email, password_hash, username) VALUES ('u@b.c', 'x', 'U')"
        )
        await db.execute(
            """
            INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
            VALUES (1, 'U', 40, 40, '300', 2, 2)
            """
        )
        await db.commit()
        async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
            char = dict(await c.fetchone())
        await add_item(db, 1, "herb", 3)
        ok, reason, info = await sell_item(db, char, "herb", quantity=0)
        assert not ok and reason == "bad quantity", (ok, reason, info)
        ok, reason, info = await sell_item(db, char, "herb", quantity=-1)
        assert not ok and reason == "bad quantity"
        ok, reason, info = await sell_item(db, char, "herb", quantity=2)
        assert ok, reason
        assert info.get("quantity") == 2
        assert int(info.get("gold_gained") or 0) == 24  # 12*2
        await db.close()

    asyncio.run(scenario())


def test_sell_bool_qty_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "sb.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sb@ex.com", "Sbu", "SellBool")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "sell", "item": "herb", "quantity": True})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)
