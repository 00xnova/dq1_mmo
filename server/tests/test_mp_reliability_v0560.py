"""v0.5.60 multiplayer reliability: move clears AFK for peers; sync rehydrates social state."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import IDLE_SOFT
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


def test_allow_move_clears_afk_flag_unit():
    """allow_move clears manual AFK (status pulse is covered by WS test)."""
    from network.websocket_manager import ConnectionManager

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        mgr = ConnectionManager()
        await mgr.connect(1, FakeWS(), name="A", x=2, y=2, map_id=0)
        assert mgr.set_afk(1, True)
        assert mgr.get_meta(1).get("afk") is True
        ok, _retry = mgr.allow_move(1)
        assert ok
        assert mgr.get_meta(1).get("afk") is False

    asyncio.run(scenario())


def test_sync_rehydrates_ignores_and_last_whisper(tmp_path, monkeypatch):
    db_path = tmp_path / "sync.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "SyncA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "SyncB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "whisper", "to": "SyncA", "text": "psst"})
                )
                await recv_until(wb, "chat", "error")
                await recv_until(wa, "chat", "error")
                await wa.send(json.dumps({"type": "ignore", "name": "SyncB"}))
                await recv_until(wa, "ignore", "error")

                await wa.send(json.dumps({"type": "sync"}))
                ws_msg = await recv_until(wa, "world_state", "error")
                assert ws_msg.get("type") == "world_state", ws_msg
                ignores = ws_msg.get("ignores") or []
                names = {str(c.get("name") or "").lower() for c in ignores}
                assert "syncb" in names, ignores
                lw = ws_msg.get("last_whisper")
                assert lw is not None, ws_msg
                assert str(lw.get("name") or "").lower() == "syncb", lw
                you = ws_msg.get("you") or {}
                assert "afk" in you and "idle" in you, you
                assert you.get("session_id") is not None, you
                assert ws_msg.get("session_id") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_move_clears_afk_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "mvafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ma@ex.com", "Ma", "MoveAfkA")
        tb, cb = register_char(base, "mb@ex.com", "Mb", "MoveAfkB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await drain(wb, 0.2)
                await wa.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                await recv_until(wa, "move_ok", "error")
                # Peer sees idle clear via player_update or online roster
                deadline = time.monotonic() + 2.5
                saw = False
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.3)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "player_update"
                            and m.get("player_id") == ca["id"]
                            and m.get("idle") is False
                        ):
                            saw = True
                            break
                        if m.get("type") == "online":
                            for card in m.get("roster") or []:
                                if (
                                    card.get("id") == ca["id"]
                                    and card.get("idle") is False
                                ):
                                    saw = True
                                    break
                            if saw:
                                break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                assert saw, "peer did not observe AFK clear after move"
                await wb.send(json.dumps({"type": "who"}))
                who = await recv_until(wb, "who")
                card = next(
                    (c for c in (who.get("roster") or []) if c.get("id") == ca["id"]),
                    None,
                )
                assert card is not None and card.get("idle") is False, card

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_three_player_zone_and_sync_still_green(tmp_path, monkeypatch):
    """Regression: zone delivery + sync under 3 clients."""
    db_path = tmp_path / "z3s.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "Za", "Z3A")
        tb, cb = register_char(base, "zb@ex.com", "Zb", "Z3B")
        tc, cc = register_char(base, "zc@ex.com", "Zc", "Z3C")

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
                await asyncio.sleep(0.85)
                await drain(wb)
                await drain(wc)
                await wa.send(
                    json.dumps({"type": "chat", "channel": "zone", "text": "z60"})
                )
                ma = await recv_until(wa, "chat", "error")
                mb = await recv_until(wb, "chat", "error")
                mc = await recv_until(wc, "chat", "error")
                assert ma.get("channel") == "zone", ma
                assert mb.get("text") == "z60" and mc.get("text") == "z60"
                await wa.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wa, "world_state")
                assert int(snap.get("online") or 0) == 3, snap
                assert isinstance(snap.get("ignores"), list), snap
                assert snap.get("session_id") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)
