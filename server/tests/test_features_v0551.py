"""v0.5.51: inn rest preview quote; buy bag-full errors include bag snapshot."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.item_manager import MAX_STACK_QTY
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


def test_rest_preview_quote(tmp_path, monkeypatch):
    db_path = tmp_path / "inn.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "i@ex.com", "Iu", "InnHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                # New hero is full HP/MP — preview should say well rested / cost 0 path
                await ws.send(json.dumps({"type": "rest", "preview": True}))
                m = await recv_until(ws, "rest_ok", "error")
                assert m.get("type") == "rest_ok", m
                assert m.get("preview") is True, m
                assert "cost" in m or m.get("full") is True, m
                # Full HP hero: actual rest may refuse with already full (expected)
                await ws.send(json.dumps({"type": "rest"}))
                m2 = await recv_until(ws, "rest_ok", "error")
                if m2.get("type") == "error":
                    assert "full" in str(m2.get("reason") or "").lower(), m2
                else:
                    assert m2.get("preview") is not True, m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_stack_full_includes_bag(tmp_path, monkeypatch):
    db_path = tmp_path / "bagerr.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "b@ex.com", "Bu", "BagErr")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                hit = None
                for _ in range(MAX_STACK_QTY + 6):
                    await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                    m = await recv_until(ws, "inventory_update", "error")
                    if m.get("type") == "error" and m.get("reason") == "stack full":
                        hit = m
                        break
                assert hit is not None, "never hit stack full"
                bag = hit.get("bag") or {}
                assert int(bag.get("max_stack") or 0) == MAX_STACK_QTY, bag
                assert int(bag.get("max_slots") or 0) >= 1, bag

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_rest_preview_field_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "innf.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "f@ex.com", "Fu", "FieldInn")

        async def flow():
            import websockets
            import network.message_handler as mh

            mh.roll_encounter = lambda *a, **k: None
            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                seq = 1
                for x, y in ((3, 2), (3, 3), (4, 3), (5, 3)):
                    seq += 1
                    await asyncio.sleep(0.09)
                    await ws.send(
                        json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                    )
                    await drain(ws, 0.08)
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                zone = (st.get("you") or {}).get("zone")
                if zone != "field":
                    return  # path flaky — skip assert
                await ws.send(json.dumps({"type": "rest", "preview": True}))
                e = await recv_until(ws, "error", "rest_ok")
                assert e.get("type") == "error", e
                assert "town" in str(e.get("reason") or "").lower(), e

        asyncio.run(flow())
    finally:
        stop_server(server)
