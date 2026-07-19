"""v0.5.128: self_peeks extract · multiplayer context on gold/vitals/buffs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import self_peeks


def test_self_peeks_module_extracted_unit():
    assert "gold" in self_peeks.GOLD_TYPES
    assert "vitals" in self_peeks.VITALS_TYPES or "hp" in self_peeks.VITALS_TYPES
    assert "xp" in self_peeks.XP_TYPES
    assert "spells" in self_peeks.SPELLS_TYPES
    assert "buffs" in self_peeks.BUFFS_TYPES


def test_gold_vitals_buffs_mp_context(tmp_path, monkeypatch):
    import asyncio
    import json
    import time

    from tests.ws_helpers import register_char, start_server, stop_server

    db_path = tmp_path / "sp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sp@ex.com", "Sp", "PeekA")
        tb, cb = register_char(base, "sp2@ex.com", "Sq", "PeekB")

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": cid})
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") == "auth_ok":
                        return

            async def recv_type(ws, *types):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as wa, websockets.connect(
                ws_url
            ) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.25)
                await wa.send(json.dumps({"type": "gold"}))
                g = await recv_type(wa, "gold", "error")
                assert g.get("type") == "gold", g
                assert "gold" in g
                assert "nearby_count" in g or "online" in g
                assert isinstance(g.get("message"), str)
                await wa.send(json.dumps({"type": "vitals"}))
                v = await recv_type(wa, "vitals", "error")
                assert v.get("type") == "vitals"
                assert "nearby_count" in v or "zone" in v
                await wa.send(json.dumps({"type": "buffs"}))
                b = await recv_type(wa, "buffs", "error")
                assert b.get("type") == "buffs"
                assert "nearby_count" in b or "online" in b

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_xp_spells_zone_message(tmp_path, monkeypatch):
    import asyncio
    import json
    import time

    from tests.ws_helpers import register_char, start_server, stop_server

    db_path = tmp_path / "spx.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "spx@ex.com", "Sx", "PeekX")

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": cid})
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") == "auth_ok":
                        return

            async def recv_type(ws, *types):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "xp"}))
                x = await recv_type(ws, "xp", "error")
                assert x.get("type") == "xp"
                assert "Level" in str(x.get("message") or "")
                await ws.send(json.dumps({"type": "spells"}))
                s = await recv_type(ws, "spells", "error")
                assert s.get("type") == "spells"
                assert "Battle" in str(s.get("message") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)
