"""v0.5.36: buy reports gold_spent; not-enough-gold includes cost."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
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


def test_buy_includes_gold_spent(tmp_path, monkeypatch):
    db_path = tmp_path / "buy.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "bu@ex.com", "BuU", "BuyHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                gold0 = int(str((inv.get("character") or {}).get("gold") or 0))

                await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                bought = m.get("bought") or {}
                assert int(bought.get("gold_spent") or 0) == 24, bought
                assert bought.get("item_id") == "herb"
                gold1 = int(str((m.get("character") or {}).get("gold") or 0))
                assert gold1 == gold0 - 24
                assert "Bought" in str(m.get("message") or "")

                # Drain gold with gear buys (herb stacks cap at 8 — cannot drain via herbs alone)
                hit = False
                for _ in range(40):
                    await ws.send(json.dumps({"type": "buy", "item": "copper_sword"}))
                    m2 = await recv_until(ws, "error", "inventory_update")
                    if m2.get("type") == "error" and m2.get("reason") == "not enough gold":
                        assert m2.get("cost") is not None
                        hit = True
                        break
                    # sold/stack/inventory full still leave cost path for next attempt
                assert hit, "never hit not enough gold"

        asyncio.run(flow())
    finally:
        stop_server(server)
