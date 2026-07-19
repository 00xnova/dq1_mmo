"""v0.5.41: shop blocked in combat; mid-tier gear in shop catalog."""

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


def test_shop_catalog_includes_mid_tier():
    from game.data_loader import load_data
    from game.item_manager import shop_catalog

    load_data.cache_clear()
    data = load_data()
    shop = data["shop"]
    assert "broad_sword" in shop
    assert "half_plate" in shop
    ids = {i["id"] for i in shop_catalog()}
    assert "broad_sword" in ids
    assert "half_plate" in ids
    # priced correctly from equipment defs
    by_id = {i["id"]: i for i in shop_catalog()}
    assert int(by_id["broad_sword"]["price"]) == 1500
    assert int(by_id["half_plate"]["price"]) == 1000


def test_shop_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "shopc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "sc@ex.com", "ScU", "ShopCombat")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.15)

                # Outside combat: shop works in town
                await ws.send(json.dumps({"type": "shop"}))
                ok = await recv_until(ws, "shop_list", "error")
                assert ok.get("type") == "shop_list", ok
                ids = {i.get("id") for i in (ok.get("items") or [])}
                assert "broad_sword" in ids and "half_plate" in ids

                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                start = await recv_until(ws, "combat_start", "error")
                assert start.get("type") == "combat_start", start
                await drain(ws, 0.15)  # clear combat_update noise

                await ws.send(json.dumps({"type": "shop"}))
                err = await recv_until(ws, "error", "shop_list")
                assert err.get("type") == "error", err
                assert err.get("reason") == "in combat", err

                await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                err2 = await recv_until(ws, "error", "inventory_update")
                assert err2.get("type") == "error", err2
                assert err2.get("reason") == "in combat", err2

                # inventory view still allowed
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv

                await ws.send(json.dumps({"type": "flee"}))
                await drain(ws, 0.5)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_broad_sword(tmp_path, monkeypatch):
    db_path = tmp_path / "bsw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "bs@ex.com", "BsU", "BroadBuyer")

        async def flow():
            import websockets
            import database.db as dbm

            # Give enough gold for broad sword (1500)
            async with dbm.db_write() as db:
                await db.execute(
                    "UPDATE characters SET gold = ? WHERE id = ?",
                    ("5000", ch["id"]),
                )
                await db.commit()

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)
                await ws.send(json.dumps({"type": "buy", "item": "broad_sword"}))
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                bought = m.get("bought") or {}
                assert bought.get("item_id") == "broad_sword"
                assert int(bought.get("gold_spent") or 0) == 1500
                await ws.send(
                    json.dumps(
                        {"type": "equip", "slot": "weapon", "item": "broad_sword"}
                    )
                )
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                char = inv.get("character") or {}
                assert char.get("equipment_weapon") == "broad_sword", char

        asyncio.run(flow())
    finally:
        stop_server(server)
