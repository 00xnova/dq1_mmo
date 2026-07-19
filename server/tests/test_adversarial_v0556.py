"""v0.5.56 adversarial: roll sides truthiness; discard qty=0; invalid sides refund."""

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


def test_roll_sides_zero_not_d100(tmp_path, monkeypatch):
    """Regression: sides=0 used `or 100` and rolled d100."""
    db_path = tmp_path / "r0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r0@ex.com", "R0u", "RollZero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "roll", "sides": 0}))
                m = await recv_until(ws, "error", "chat")
                assert m.get("type") == "error", m
                assert "sides" in str(m.get("reason") or "").lower(), m
                # Refund allows immediate valid roll
                await ws.send(json.dumps({"type": "roll", "sides": 20}))
                m2 = await recv_until(ws, "chat", "error")
                assert m2.get("type") == "chat", m2
                assert (m2.get("roll") or {}).get("sides") == 20, m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_roll_sides_invalid_matrix(tmp_path, monkeypatch):
    db_path = tmp_path / "ri.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ri@ex.com", "Riu", "RollInv")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for sides in (1, -5, 1001, False, "nope"):
                    await asyncio.sleep(0.05)
                    await ws.send(json.dumps({"type": "roll", "sides": sides}))
                    m = await recv_until(ws, "error", "chat")
                    assert m.get("type") == "error", (sides, m)
                    assert "sides" in str(m.get("reason") or "").lower(), (sides, m)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_discard_qty_zero_does_not_remove(tmp_path, monkeypatch):
    """Regression: quantity=0 used `or 1` and discarded one unit."""
    db_path = tmp_path / "d0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "d0@ex.com", "D0u", "DiscZero")

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
                assert before >= 1, herbs

                await ws.send(
                    json.dumps({"type": "discard", "item": "herb", "quantity": 0})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

                await ws.send(json.dumps({"type": "inventory"}))
                inv2 = await recv_until(ws, "inventory_update")
                herbs2 = next(
                    (i for i in (inv2.get("items") or []) if i.get("item_id") == "herb"),
                    None,
                )
                assert herbs2 is not None, inv2
                assert int(herbs2.get("quantity") or 0) == before, (before, herbs2)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_discard_qty_negative(tmp_path, monkeypatch):
    db_path = tmp_path / "dn.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "dn@ex.com", "Dnu", "DiscNeg")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "discard", "item": "herb", "quantity": -2})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m
                assert "quantity" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_default_roll_still_d100(tmp_path, monkeypatch):
    db_path = tmp_path / "rd.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "rd@ex.com", "Rdu", "RollDef")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "roll"}))
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert (m.get("roll") or {}).get("sides") == 100, m
                val = int((m.get("roll") or {}).get("value") or 0)
                assert 1 <= val <= 100, m

        asyncio.run(flow())
    finally:
        stop_server(server)
