"""v0.5.50 multiplayer: census, combat outcome notices, disconnect reason idle, find zones."""

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


def test_counts_census(tmp_path, monkeypatch):
    db_path = tmp_path / "cen.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cu", "CensusA")
        tb, cb = register_char(base, "c2@ex.com", "C2", "CensusB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                for typ in ("counts", "census", "population"):
                    await wa.send(json.dumps({"type": typ}))
                    m = await recv_until(wa, "counts", "error")
                    assert m.get("type") == "counts", m
                    assert int(m.get("online") or 0) >= 2, m
                    assert isinstance(m.get("zones"), dict), m
                    assert m.get("zones").get("town", 0) >= 1, m
                    assert m.get("nearby_count") is not None, m
                    assert "online" in str(m.get("message") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_includes_zones(tmp_path, monkeypatch):
    db_path = tmp_path / "fz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "f@ex.com", "Fu", "FindZ")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "find", "q": "Find"}))
                m = await recv_until(ws, "find", "error")
                assert m.get("type") == "find", m
                assert isinstance(m.get("zones"), dict), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_combat_victory_system_chat(tmp_path, monkeypatch):
    """Nearby peers see victory system chat after combat ends in victory."""
    db_path = tmp_path / "vic.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vu", "VicHero")
        tb, cb = register_char(base, "w@ex.com", "Wu", "WatchVic")

        async def flow():
            import websockets
            from network.message_handler import _announce_combat_outcome
            from network.websocket_manager import manager

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await _announce_combat_outcome(ca["id"], "victory")
                saw = None
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.35)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "chat"
                            and m.get("channel") == "system"
                            and "victorious" in str(m.get("text") or "").lower()
                        ):
                            saw = m
                            break
                    except Exception:
                        break
                assert saw is not None, "peer never saw victory system chat"
                # Flee line (drain any online pulses first)
                await drain(wb, 0.15)
                await _announce_combat_outcome(ca["id"], "fled")
                saw2 = None
                deadline = time.monotonic() + 2.5
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.4)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "chat"
                            and m.get("channel") == "system"
                            and "fled" in str(m.get("text") or "").lower()
                        ):
                            saw2 = m
                            break
                    except Exception:
                        continue
                assert saw2 is not None, "peer never saw flee system chat"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_disconnect_reason_idle_unit():
    """disconnect(reason=idle) surfaces idle on player_left payload shape."""
    import asyncio
    from network.websocket_manager import ConnectionManager

    async def flow():
        mgr = ConnectionManager()
        # Simulate with a fake that records leave
        sent = []

        class FakeWS:
            async def send_text(self, payload):
                sent.append(json.loads(payload))

        mgr._connections[1] = FakeWS()  # type: ignore[assignment]
        mgr._connections[2] = FakeWS()  # type: ignore[assignment]
        now = time.monotonic()
        mgr._meta[1] = {
            "id": 1,
            "name": "A",
            "x": 2.0,
            "y": 2.0,
            "map_id": 0,
            "level": 1,
            "in_combat": False,
            "last_seen": now,
            "visible": {2},
            "ignore": set(),
            "ignore_names": {},
            "repel_steps": 0,
            "radiant_steps": 0,
        }
        mgr._meta[2] = {
            "id": 2,
            "name": "B",
            "x": 3.0,
            "y": 2.0,
            "map_id": 0,
            "level": 1,
            "in_combat": False,
            "last_seen": now,
            "visible": {1},
            "ignore": set(),
            "ignore_names": {},
            "repel_steps": 0,
            "radiant_steps": 0,
        }
        left = await mgr.disconnect(1, reason="idle")
        assert left is not None
        assert left["name"] == "A"
        # Peer 2 should have been sent player_left with reason idle
        leaves = [m for m in sent if m.get("type") == "player_left"]
        assert leaves, sent
        assert leaves[0].get("reason") == "idle", leaves[0]

    asyncio.run(flow())


def test_help_mentions_counts(tmp_path, monkeypatch):
    db_path = tmp_path / "hc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "h@ex.com", "Hu", "HelpCounts")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help")
                cmds = [c.get("cmd") for c in (h.get("commands") or [])]
                assert "counts" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)
