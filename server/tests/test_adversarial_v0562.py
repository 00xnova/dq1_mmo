"""v0.5.62 adversarial: fractional qty rejected; digit-string qty ok; parse helper."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.message_handler import _parse_positive_qty
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


def test_parse_positive_qty_unit():
    assert _parse_positive_qty(1) == 1
    assert _parse_positive_qty(8) == 8
    assert _parse_positive_qty("2") == 2
    assert _parse_positive_qty(" 3 ") == 3
    assert _parse_positive_qty(2.0) == 2
    assert _parse_positive_qty(0) is None
    assert _parse_positive_qty(-1) is None
    assert _parse_positive_qty(2.5) is None
    assert _parse_positive_qty(True) is None
    assert _parse_positive_qty(False) is None
    assert _parse_positive_qty("nope") is None
    assert _parse_positive_qty(None) is None
    assert _parse_positive_qty(float("nan")) is None


def test_buy_fractional_qty_rejected(tmp_path, monkeypatch):
    """Regression: quantity 2.5 used to silently become 2 via int()."""
    db_path = tmp_path / "bf.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "bf@ex.com", "Bfu", "BuyFrac")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                gold0 = str((inv.get("character") or {}).get("gold"))
                herbs0 = next(
                    (i for i in (inv.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                h0 = int((herbs0 or {}).get("quantity") or 0)

                await ws.send(
                    json.dumps({"type": "buy", "item": "herb", "quantity": 2.5})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

                await ws.send(json.dumps({"type": "inventory"}))
                inv2 = await recv_until(ws, "inventory_update")
                assert str((inv2.get("character") or {}).get("gold")) == gold0
                herbs1 = next(
                    (
                        i
                        for i in (inv2.get("items") or [])
                        if i.get("item_id") == "herb"
                    ),
                    None,
                )
                assert int((herbs1 or {}).get("quantity") or 0) == h0

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_integer_float_and_string_ok(tmp_path, monkeypatch):
    db_path = tmp_path / "bi.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "bi@ex.com", "Biu", "BuyInt")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "buy", "item": "herb", "quantity": 2.0})
                )
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                assert int((m.get("bought") or {}).get("quantity") or 0) == 2, m
                await ws.send(
                    json.dumps({"type": "buy", "item": "herb", "quantity": "1"})
                )
                m2 = await recv_until(ws, "inventory_update", "error")
                assert m2.get("type") == "inventory_update", m2
                assert int((m2.get("bought") or {}).get("quantity") or 0) == 1, m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sell_and_discard_fractional_qty(tmp_path, monkeypatch):
    db_path = tmp_path / "sf.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sf@ex.com", "Sfu", "SellFrac")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "sell", "item": "herb", "quantity": 1.5})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                await ws.send(
                    json.dumps({"type": "discard", "item": "herb", "quantity": 3.2})
                )
                m2 = await recv_until(ws, "error", "inventory_update")
                assert m2.get("type") == "error", m2

        asyncio.run(flow())
    finally:
        stop_server(server)
