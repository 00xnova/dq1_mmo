"""v0.5.42 multiplayer: live name resolve, /near, join welcome, who.nearby_count."""

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


async def drain(ws, seconds=0.15):
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
    return await drain(ws, 0.2)


def test_find_id_by_name_skips_orphan_meta():
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()
    mgr._meta[1] = {
        "id": 1,
        "name": "Ghost",
        "x": 2.0,
        "y": 2.0,
        "map_id": 0,
        "level": 1,
        "last_seen": time.monotonic(),
        "visible": set(),
    }
    # no live socket for 1
    assert mgr.find_id_by_name("Ghost") is None
    mgr._connections[1] = object()  # type: ignore
    assert mgr.find_id_by_name("Ghost") == 1
    assert mgr.find_id_by_name("ghost") == 1
    assert mgr.find_id_by_name("Nobody") is None


def test_near_and_who_nearby_count(tmp_path, monkeypatch):
    db_path = tmp_path / "near.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "n1@ex.com", "N1", "NearA")
        tb, cb = register_char(base, "n2@ex.com", "N2", "NearB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.1)

                await wa.send(json.dumps({"type": "near"}))
                near = await recv_until(wa, "near", "error")
                assert near.get("type") == "near", near
                assert "nearby_count" in near
                assert "players" in near
                assert near.get("zone") in ("town", None) or near.get("zone") == "town"
                # Both spawn town AOI — B should be nearby
                assert int(near.get("nearby_count") or 0) >= 1
                names = {p.get("name") for p in (near.get("players") or [])}
                assert "NearB" in names

                await wa.send(json.dumps({"type": "here"}))
                near2 = await recv_until(wa, "near", "error")
                assert near2.get("type") == "near", near2

                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who")
                assert "nearby_count" in who
                assert int(who.get("nearby_count") or 0) == len(who.get("players") or [])

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_join_welcome_on_auth_ok(tmp_path, monkeypatch):
    db_path = tmp_path / "welc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "w@ex.com", "WU", "WelcomeHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": t, "character_id": ch["id"]}
                    )
                )
                auth = await recv_until(ws, "auth_ok")
                welcome = str(auth.get("welcome") or "")
                assert "WelcomeHero" in welcome, auth
                assert "online" in welcome.lower(), welcome
                assert int(auth.get("online") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_orphan_name_fails(tmp_path, monkeypatch):
    """Name match against dead meta must not succeed after find_id_by_name fix."""
    db_path = tmp_path / "orph.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "o@ex.com", "OU", "OrphanWhisper")

        async def flow():
            import websockets
            from network.websocket_manager import manager

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                # Inject orphan meta with a fake online-looking name
                manager._meta[999] = {
                    "id": 999,
                    "name": "Phantom",
                    "x": 2.0,
                    "y": 2.0,
                    "map_id": 0,
                    "level": 1,
                    "last_seen": time.monotonic(),
                    "visible": set(),
                }
                assert manager.find_id_by_name("Phantom") is None
                await ws.send(
                    json.dumps(
                        {"type": "whisper", "to": "Phantom", "text": "hello ghost"}
                    )
                )
                err = await recv_until(ws, "error", "chat")
                assert err.get("type") == "error", err
                assert "online" in str(err.get("reason") or "").lower() or "not" in str(
                    err.get("reason") or ""
                ).lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
