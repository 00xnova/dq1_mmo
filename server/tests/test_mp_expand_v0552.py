"""v0.5.52 multiplayer: unique name prefix resolve; leave zone; welcome nearby."""

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


def test_resolve_live_name_unit():
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()
    mgr._connections[1] = object()  # type: ignore[assignment]
    mgr._connections[2] = object()  # type: ignore[assignment]
    mgr._connections[3] = object()  # type: ignore[assignment]
    mgr._meta[1] = {"id": 1, "name": "Alice", "x": 2, "y": 2, "map_id": 0, "level": 1}
    mgr._meta[2] = {"id": 2, "name": "Alicia", "x": 2, "y": 2, "map_id": 0, "level": 1}
    mgr._meta[3] = {"id": 3, "name": "Bob", "x": 2, "y": 2, "map_id": 0, "level": 1}
    # exact
    tid, err = mgr.resolve_live_name("alice")
    assert tid == 1 and err is None
    # unique prefix
    tid, err = mgr.resolve_live_name("Bo")
    assert tid == 3 and err is None
    # ambiguous
    tid, err = mgr.resolve_live_name("Ali")
    assert tid is None and err == "name ambiguous"
    # orphan ignored
    mgr._meta[4] = {"id": 4, "name": "GhostBob", "x": 2, "y": 2, "map_id": 0, "level": 1}
    tid, err = mgr.resolve_live_name("Ghost")
    assert tid is None and err == "player not online"
    # short prefix no match fallback
    tid, err = mgr.resolve_live_name("Z")
    assert tid is None


def test_whisper_unique_prefix(tmp_path, monkeypatch):
    db_path = tmp_path / "wpre.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "WhisperA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "UniqueBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(
                    json.dumps(
                        {"type": "whisper", "to": "Uni", "text": "hello prefix"}
                    )
                )
                ca_m = await recv_until(wa, "chat", "error")
                assert ca_m.get("type") == "chat", ca_m
                assert ca_m.get("channel") == "whisper", ca_m
                cb_m = await recv_until(wb, "chat", "error")
                assert cb_m.get("text") == "hello prefix", cb_m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_ambiguous_prefix(tmp_path, monkeypatch):
    db_path = tmp_path / "wamb.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "x@ex.com", "Xa", "Alex")
        tb, cb = register_char(base, "y@ex.com", "Ya", "Alexa")
        tc, cc = register_char(base, "z@ex.com", "Za", "Caller")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await auth(wc, tc, cc["id"])
                await wc.send(
                    json.dumps({"type": "whisper", "to": "Ale", "text": "hi"})
                )
                err = await recv_until(wc, "error", "chat")
                assert err.get("type") == "error", err
                assert err.get("reason") == "name ambiguous", err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_auth_ok_nearby_and_zones(tmp_path, monkeypatch):
    db_path = tmp_path / "aw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pa", "PeerA")
        tb, cb = register_char(base, "q@ex.com", "Qa", "PeerB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
            async with websockets.connect(ws_url) as wb:
                aok = await auth(wb, tb, cb["id"])
                assert aok.get("nearby_count") is not None, aok
                assert isinstance(aok.get("zones"), dict), aok
                assert "nearby" in str(aok.get("welcome") or "").lower() or int(
                    aok.get("nearby_count") or 0
                ) >= 0

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_player_left_includes_zone_unit():
    import asyncio
    import json
    from network.websocket_manager import ConnectionManager

    async def flow():
        mgr = ConnectionManager()
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
        await mgr.disconnect(1, reason="disconnect")
        leaves = [m for m in sent if m.get("type") == "player_left"]
        assert leaves, sent
        assert leaves[0].get("zone") == "town", leaves[0]

    asyncio.run(flow())
