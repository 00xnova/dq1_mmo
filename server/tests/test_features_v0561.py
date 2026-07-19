"""v0.5.61: buy qty=0 rejected; multi-buy; whereami/coords; stats alias."""

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


def test_buy_qty_zero_does_not_buy(tmp_path, monkeypatch):
    """Regression: quantity:0 used to buy one unit (ignored qty)."""
    db_path = tmp_path / "b0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b0@ex.com", "B0u", "BuyZero")

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
                before = int((herbs or {}).get("quantity") or 0)
                gold_before = str((inv.get("character") or {}).get("gold"))

                await ws.send(
                    json.dumps({"type": "buy", "item": "herb", "quantity": 0})
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
                after = int((herbs2 or {}).get("quantity") or 0)
                assert after == before
                assert str((inv2.get("character") or {}).get("gold")) == gold_before

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_qty_negative_and_bool(tmp_path, monkeypatch):
    db_path = tmp_path / "bn.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "bn@ex.com", "Bnu", "BuyNeg")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for qty in (-2, True, False):
                    await ws.send(
                        json.dumps({"type": "buy", "item": "herb", "quantity": qty})
                    )
                    m = await recv_until(ws, "error", "inventory_update")
                    assert m.get("type") == "error", (qty, m)
                    assert "quantity" in str(m.get("reason") or "").lower(), (qty, m)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_multi_qty(tmp_path, monkeypatch):
    db_path = tmp_path / "bm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "bm@ex.com", "Bmu", "BuyMulti")

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
                before = int((herbs or {}).get("quantity") or 0)
                gold0 = int(str((inv.get("character") or {}).get("gold") or 0))

                await ws.send(
                    json.dumps({"type": "buy", "item": "herb", "quantity": 2})
                )
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                bought = m.get("bought") or {}
                assert int(bought.get("quantity") or 0) == 2, bought
                assert int(bought.get("gold_spent") or 0) == 48, bought  # 24*2
                herbs2 = next(
                    (i for i in (m.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                assert int((herbs2 or {}).get("quantity") or 0) == before + 2
                gold1 = int(str((m.get("character") or {}).get("gold") or 0))
                assert gold1 == gold0 - 48

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whereami_and_coords(tmp_path, monkeypatch):
    db_path = tmp_path / "wh.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wh@ex.com", "Whu", "WhereHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for t in ("whereami", "coords", "pos"):
                    await ws.send(json.dumps({"type": t}))
                    m = await recv_until(ws, "zone", "error")
                    assert m.get("type") == "zone", (t, m)
                    assert m.get("x") is not None and m.get("y") is not None, m
                    assert m.get("zone") in ("town", "field", "dungeon", None)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_stats_alias_for_status(tmp_path, monkeypatch):
    db_path = tmp_path / "st.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "st@ex.com", "Stu", "StatsHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "stats"}))
                m = await recv_until(ws, "status", "error")
                assert m.get("type") == "status", m
                assert (m.get("character") or {}).get("name") == "StatsHero"
                await ws.send(json.dumps({"type": "sheet"}))
                m2 = await recv_until(ws, "status", "error")
                assert m2.get("type") == "status", m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_item_unit_bad_qty():
    import asyncio
    import aiosqlite
    import tempfile
    from pathlib import Path

    from database.migrations import run_migrations
    from game.item_manager import buy_item

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
        ok, reason, info = await buy_item(db, char, "herb", quantity=0)
        assert not ok and reason == "bad quantity", (ok, reason, info)
        ok, reason, info = await buy_item(db, char, "herb", quantity=2)
        assert ok, reason
        assert info.get("quantity") == 2
        assert int(info.get("gold_spent") or 0) == 48
        await db.close()

    asyncio.run(scenario())
