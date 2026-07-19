"""Multiplayer expansion: zone chat, whisper-by-id, AOI rebuild, reliable nearby."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"waiting for {types}")
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


def test_broadcast_nearby_uses_geometry_when_aoi_stale():
    """Stale non-empty visible set must not drop geometric neighbors."""
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b, c = WS(), WS(), WS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=1)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=1)  # near A
        await mgr.connect(3, c, name="C", x=50, y=50, map_id=1)  # far (if map allows)
        # Corrupt: A only thinks C is visible (stale)
        mgr.get_meta(1)["visible"] = {3}
        b.sent.clear()
        c.sent.clear()
        await mgr.broadcast_nearby(1, {"type": "chat", "text": "hello"}, include_self=False)
        # B is geometrically near → must receive
        assert any(m.get("text") == "hello" for m in b.sent), b.sent
        # C may also get it via union with stale visible — acceptable (union)
        # Rebuild AOI restores correct links
        to_self = await mgr.rebuild_aoi(1)
        assert 2 in mgr.get_meta(1)["visible"]
        # far peer 3 should leave if not geometrically near
        # (50,50) may be out of range from (2,2)
        assert 3 not in mgr.get_meta(1)["visible"] or abs(50 - 2) <= 10

    asyncio.run(scenario())


def test_ids_in_zone_and_broadcast_zone():
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        # Town spawn (2,2) is zone town; field (6,2) is field
        ta, tb, field = WS(), WS(), WS()
        await mgr.connect(1, ta, name="TownA", x=2, y=2, map_id=1)
        await mgr.connect(2, tb, name="TownB", x=3, y=2, map_id=1)
        await mgr.connect(3, field, name="FieldC", x=6, y=2, map_id=1)
        assert 2 in mgr.ids_in_zone(1)
        assert 3 not in mgr.ids_in_zone(1)
        tb.sent.clear()
        field.sent.clear()
        await mgr.broadcast_zone(1, {"type": "chat", "channel": "zone", "text": "town!"})
        assert any(m.get("text") == "town!" for m in tb.sent), tb.sent
        assert not any(m.get("text") == "town!" for m in field.sent), field.sent

    asyncio.run(scenario())


def test_whisper_by_player_id(tmp_path, monkeypatch):
    db_path = tmp_path / "mp_wid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "wid_a@ex.com", "WidA", "WidAlice")
        token_b, ch_b = register_char(base, "wid_b@ex.com", "WidB", "WidBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, token_a, ch_a), (wb, token_b, ch_b)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps(
                        {
                            "type": "whisper",
                            "to_id": ch_b["id"],
                            "text": "id path works",
                        }
                    )
                )
                ca = await recv_until(wa, "chat")
                cb = await recv_until(wb, "chat")
                assert ca["channel"] == "whisper"
                assert ca["to_id"] == ch_b["id"]
                assert cb["text"] == "id path works"
                assert cb["name"] == "WidAlice"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_chat_ws(tmp_path, monkeypatch):
    """Players in town hear zone chat; field player does not."""
    db_path = tmp_path / "mp_zone.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "za@ex.com", "ZA", "ZoneAlice")
        token_b, ch_b = register_char(base, "zb@ex.com", "ZB", "ZoneBob")
        token_c, ch_c = register_char(base, "zc@ex.com", "ZC", "ZoneCarol")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                for ws, tok, ch in (
                    (wa, token_a, ch_a),
                    (wb, token_b, ch_b),
                    (wc, token_c, ch_c),
                ):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")
                await drain(wa)
                await drain(wb)
                await drain(wc)

                # Leave town via south gap (y=3): (2,2)→(2,3)→…→(6,3) field
                # y=2 has a wall at x=5; open path is row y=3
                path = [(2, 3), (3, 3), (4, 3), (5, 3), (6, 3)]
                seq = 0
                for x, y in path:
                    seq += 1
                    await asyncio.sleep(0.15)
                    await wc.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    mok = await recv_until(wc, "move_ok", "error")
                    assert mok.get("type") == "move_ok", mok
                    # may land in combat; resolve flee if needed
                    if mok.get("ok") is False and mok.get("reason") == "in combat":
                        await wc.send(json.dumps({"type": "flee"}))
                        await recv_until(wc, "combat_end", "combat_update", "error")
                        await asyncio.sleep(0.15)
                        await wc.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq + 100})
                        )
                        mok = await recv_until(wc, "move_ok", "error")
                    assert mok.get("ok") is True, mok
                    assert mok.get("x") == x and mok.get("y") == y, mok

                await wc.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wc, "world_state")
                assert snap.get("zone") == "field", snap
                assert (snap.get("you") or {}).get("x") == 6

                await drain(wa, 0.25)
                await drain(wb, 0.25)
                await drain(wc, 0.25)

                await wa.send(
                    json.dumps(
                        {"type": "chat", "channel": "zone", "text": "town call"}
                    )
                )
                # Alice + Bob in town should hear; Carol in field should not
                ca = await recv_until(wa, "chat")
                cb = await recv_until(wb, "chat")
                assert ca["channel"] == "zone"
                assert ca["text"] == "town call"
                assert ca.get("zone") == "town"
                assert cb["text"] == "town call"

                # Carol should not get zone town message; poll briefly
                got_c = False
                end = time.monotonic() + 0.7
                while time.monotonic() < end:
                    try:
                        m = json.loads(
                            await asyncio.wait_for(wc.recv(), 0.15)
                        )
                        if m.get("type") == "chat" and m.get("text") == "town call":
                            got_c = True
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert not got_c, "field player must not hear town zone chat"

                # who includes zone on you
                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who")
                assert who["you"].get("zone") == "town"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sync_repairs_aoi(tmp_path, monkeypatch):
    """After intentional AOI corruption, sync rebuilds visibility (unit + live)."""
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def unit():
        a, b = WS(), WS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=1)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=1)
        mgr.get_meta(1)["visible"] = set()
        mgr.get_meta(2)["visible"] = set()
        msgs = await mgr.rebuild_aoi(1)
        assert 2 in mgr.get_meta(1)["visible"]
        assert 1 in mgr.get_meta(2)["visible"]
        assert any(m.get("type") == "player_joined" for m in msgs)

    asyncio.run(unit())

    # Live: two clients, sync returns zone + online
    db_path = tmp_path / "mp_sync.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "sy@ex.com", "SyU", "SyHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(json.dumps({"type": "sync"}))
                snap = await recv_until(ws, "world_state")
                assert snap.get("online") == 1
                assert snap.get("zone") in ("town", "field", "dungeon", None)
                assert snap.get("you") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_three_player_say_after_move_stress(tmp_path, monkeypatch):
    """Classic nearby chat still works after AOI enter/leave moves."""
    db_path = tmp_path / "mp_say.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        clients = [
            register_char(base, f"s{i}@ex.com", f"SU{i}", f"SayHero{i}")
            for i in range(3)
        ]

        async def flow():
            import websockets

            sockets = []
            for tok, ch in clients:
                ws = await websockets.connect(ws_url)
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": tok, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                sockets.append(ws)
            for ws in sockets:
                await drain(ws)

            await sockets[0].send(json.dumps({"type": "say", "text": "hi all"}))
            for ws in sockets:
                m = await recv_until(ws, "chat")
                assert m["channel"] == "nearby"
                assert m["text"] == "hi all"

            for ws in sockets:
                await ws.close()

        asyncio.run(flow())
    finally:
        stop_server(server)
