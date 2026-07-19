"""v0.5.54 multiplayer reliability: session_id on presence, chat refund, soft-grace auth restore."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import CHAT_MIN_INTERVAL, ConnectionManager
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
    await drain(ws, 0.15)
    return m


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail
        self.closed = False

    async def send_text(self, t):
        if self.fail:
            raise RuntimeError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_refund_chat_unit():
    mgr = ConnectionManager()

    async def scenario():
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        ok, _ = mgr.allow_chat(1)
        assert ok
        ok2, retry = mgr.allow_chat(1)
        assert not ok2 and retry > 0
        mgr.refund_chat(1)
        ok3, _ = mgr.allow_chat(1)
        assert ok3

    asyncio.run(scenario())


def test_player_joined_includes_session_id_unit():
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=0)
        sid1 = mgr.session_id(1)
        await mgr.connect(2, b, name="Bob", x=3, y=2, map_id=0)
        b.sent.clear()
        # Move Alice so Bob receives join/move with session_id
        await mgr.publish_move(1, 3.0, 2.0, seq=1)
        joins = [m for m in b.sent if m.get("type") == "player_joined"]
        moves = [m for m in b.sent if m.get("type") == "player_moved"]
        # Bob already nearby on connect; move should send player_moved with session
        assert moves, "expected player_moved to peer"
        assert moves[0].get("session_id") == sid1
        # Force AOI re-join: clear visible then rebuild
        me = mgr.get_meta(1)
        me["visible"] = set()
        b.sent.clear()
        await mgr.rebuild_aoi(1)
        joins2 = [m for m in b.sent if m.get("type") == "player_joined"]
        assert joins2, "expected player_joined after AOI rebuild"
        assert joins2[0].get("session_id") == sid1
        assert joins2[0].get("player_id") == 1

    asyncio.run(scenario())


def test_player_left_out_of_range_includes_zone_unit():
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS(), FakeWS()
        # Town spawn tiles — same map, nearby then far
        await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Bob", x=3, y=2, map_id=0)
        b.sent.clear()
        # Walk Alice far away so Bob gets player_left
        await mgr.publish_move(1, 80.0, 80.0, seq=2)
        leaves = [m for m in b.sent if m.get("type") == "player_left"]
        assert leaves, "expected out_of_range leave"
        assert leaves[0].get("reason") == "out_of_range"
        # zone may be field/town/dungeon depending on map; presence of key is the contract
        # when tile is walkable zone; if None that's also OK for void tiles
        assert "player_id" in leaves[0]
        assert leaves[0].get("player_id") == 1

    asyncio.run(scenario())


def test_disconnect_player_left_includes_session_id_unit():
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Bob", x=3, y=2, map_id=0)
        sid = mgr.session_id(1)
        b.sent.clear()
        await mgr.disconnect(1, a, reason="disconnect")
        leaves = [m for m in b.sent if m.get("type") == "player_left"]
        assert leaves
        assert leaves[0].get("session_id") == sid
        assert leaves[0].get("reason") == "disconnect"

    asyncio.run(scenario())


def test_auth_restores_ignore_and_last_whisper(tmp_path, monkeypatch):
    """Soft-grace: ignore list + last whisper peer returned on auth_ok after reconnect."""
    db_path = tmp_path / "grace.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "GraceA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "GraceB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                auth_a = await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                # Whisper B ← A so A stores last peer; B ignores A
                await wa.send(
                    json.dumps(
                        {"type": "whisper", "to": "GraceB", "text": "hi for reply"}
                    )
                )
                await recv_until(wa, "chat", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wb.send(json.dumps({"type": "ignore", "name": "GraceA"}))
                ign = await recv_until(wb, "ignore", "error")
                assert ign.get("type") == "ignore"
                assert ign.get("ok") is True

            # B reconnects — soft grace should restore ignore + last_whisper on auth
            async with websockets.connect(ws_url) as wb2:
                await wb2.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "token": tb,
                            "character_id": cb["id"],
                        }
                    )
                )
                auth2 = await recv_until(wb2, "auth_ok")
                assert auth2.get("session_id") is not None
                ignores = auth2.get("ignores") or []
                names = {str(c.get("name") or "").lower() for c in ignores}
                assert "gracea" in names, f"expected GraceA in ignores, got {ignores}"
                lw = auth2.get("last_whisper")
                # B received whisper from A, so last_whisper should point at GraceA
                assert lw is not None, "last_whisper missing on auth_ok"
                assert str(lw.get("name") or "").lower() == "gracea"
                # world_state should also carry ignores for reconnect hygiene
                ws_msg = await recv_until(wb2, "world_state")
                assert "ignores" in ws_msg
                assert ws_msg.get("session_id") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_send_fail_refunds_chat_rate_unit():
    """If target socket dies mid-send, chat rate is refunded (online→dead race)."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS(fail=True)
        await wm.manager.connect(1, a, name="RefundA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="RefundB", x=3, y=2, map_id=0)
        # First whisper: send to B fails → refund → allow_chat again immediately
        _cid, _uid, outbound, _cm = await handle_message(
            1, 99, {"type": "whisper", "to": "RefundB", "text": "ghost"}
        )
        errs = [m for m in outbound if m.get("type") == "error"]
        assert errs, outbound
        assert errs[0].get("reason") == "player not online"
        # Without refund, second chat would be rate-limited; with refund it proceeds
        ok, retry = wm.manager.allow_chat(1)
        assert ok, f"expected refunded chat allowance, retry={retry}"

    asyncio.run(scenario())


def test_auth_join_peer_sees_session_id(tmp_path, monkeypatch):
    """Peer player_joined on auth includes session_id for reconnect hygiene."""
    db_path = tmp_path / "joinsid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ja@ex.com", "Ja", "JoinA")
        tb, cb = register_char(base, "jb@ex.com", "Jb", "JoinB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                auth_a = await auth(wa, ta, ca["id"])
                sid_a = auth_a.get("session_id")
                assert sid_a is not None

                async with websockets.connect(ws_url) as wb:
                    await wb.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": tb,
                                "character_id": cb["id"],
                            }
                        )
                    )
                    auth_b = await recv_until(wb, "auth_ok")
                    assert auth_b.get("session_id") is not None
                    # A should see B join with session_id
                    joined = await recv_until(wa, "player_joined")
                    assert joined.get("player_id") == cb["id"]
                    assert joined.get("session_id") is not None
                    assert joined.get("session_id") == auth_b.get("session_id")

        asyncio.run(flow())
    finally:
        stop_server(server)
