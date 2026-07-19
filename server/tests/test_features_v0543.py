"""v0.5.43: /zone, wings/respawn zone, high-tier shop gear, fairy water field."""

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
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_shop_has_full_plate_and_silver_shield():
    from game.data_loader import load_data
    from game.item_manager import shop_catalog

    load_data.cache_clear()
    ids = {i["id"] for i in shop_catalog()}
    assert "full_plate" in ids
    assert "silver_shield" in ids
    by = {i["id"]: i for i in shop_catalog()}
    assert int(by["full_plate"]["price"]) == 3000
    assert int(by["silver_shield"]["price"]) == 14800


def test_zone_command(tmp_path, monkeypatch):
    db_path = tmp_path / "zone.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "z@ex.com", "ZU", "ZoneHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                for typ in ("zone", "where", "area"):
                    await ws.send(json.dumps({"type": typ}))
                    m = await recv_until(ws, "zone", "error")
                    assert m.get("type") == "zone", m
                    assert m.get("zone") == "town", m
                    assert "zones" in m
                    assert m["zones"].get("town", 0) >= 1
                    assert m.get("x") is not None and m.get("y") is not None
                    assert "town" in str(m.get("message") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_fairy_water_sets_repel(tmp_path, monkeypatch):
    db_path = tmp_path / "fw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, port, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "fw@ex.com", "FW", "FairyHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "buy", "item": "fairy_water"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                await drain(ws, 0.08)
                await ws.send(json.dumps({"type": "use_item", "item": "fairy_water"}))
                used = await recv_until(ws, "item_used", "error")
                assert used.get("type") == "item_used", used
                assert int(used.get("repel_steps") or 0) == 64
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                assert int((st.get("you") or {}).get("repel") or 0) == 64

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_wings_move_ok_includes_zone(tmp_path, monkeypatch):
    db_path = tmp_path / "wg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, port, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "wg@ex.com", "WG", "WingHero")

        async def flow():
            import websockets
            import network.message_handler as mh

            orig = mh.roll_encounter
            mh.roll_encounter = lambda *a, **k: None  # type: ignore
            try:
                async with websockets.connect(ws_url) as ws:
                    await auth(ws, t, ch["id"])
                    await ws.send(json.dumps({"type": "buy", "item": "wing"}))
                    await recv_until(ws, "inventory_update", "error")
                    # Walk to field
                    seq = 0
                    for x, y in ((2, 3), (3, 3), (4, 3), (5, 3)):
                        seq += 1
                        await asyncio.sleep(0.08)
                        await ws.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        await drain(ws, 0.08)
                    await ws.send(json.dumps({"type": "use_item", "item": "wing"}))
                    # Collect item_used + move_ok
                    saw_move = None
                    deadline = time.monotonic() + 3.0
                    while time.monotonic() < deadline:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), 0.5)
                        except (asyncio.TimeoutError, TimeoutError):
                            continue
                        m = json.loads(raw)
                        if m.get("type") == "move_ok" and m.get("reason") == "wings":
                            saw_move = m
                            break
                    assert saw_move is not None, "no wings move_ok"
                    assert saw_move.get("zone") == "town", saw_move
                    assert saw_move.get("x") == 2 and saw_move.get("y") == 2
            finally:
                mh.roll_encounter = orig

        asyncio.run(flow())
    finally:
        stop_server(server)
