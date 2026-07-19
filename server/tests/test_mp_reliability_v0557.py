"""v0.5.57 multiplayer reliability: look offline reason, roster session_id, idle clear, zone gate."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, IDLE_SOFT, _online_card, _public_meta
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


def test_online_card_includes_session_id_unit():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=0)
        meta = mgr.get_meta(1)
        assert meta is not None
        card = _online_card(meta)
        assert card.get("session_id") == mgr.session_id(1)
        pub = _public_meta(meta)
        assert pub.get("session_id") == mgr.session_id(1)

    asyncio.run(scenario())


def test_look_offline_name_reason(tmp_path, monkeypatch):
    """Named look of offline player → player not online (not not found)."""
    db_path = tmp_path / "lookoff.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "LookerA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "GoneBob")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
                async with websockets.connect(ws_url) as wb:
                    await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.35)
                await wa.send(json.dumps({"type": "look", "name": "GoneBob"}))
                m = await recv_until(wa, "look", "error")
                assert m.get("type") == "error", m
                assert m.get("reason") == "player not online", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_who_roster_has_session_id(tmp_path, monkeypatch):
    db_path = tmp_path / "whosid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "Wa", "WhoSidA")
        tb, cb = register_char(base, "wb@ex.com", "Wb", "WhoSidB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                aa = await auth(wa, ta, ca["id"])
                ab = await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who")
                roster = who.get("roster") or []
                assert len(roster) >= 2, who
                by_id = {int(c["id"]): c for c in roster if c.get("id") is not None}
                assert by_id[ca["id"]].get("session_id") == aa.get("session_id")
                assert by_id[cb["id"]].get("session_id") == ab.get("session_id")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_chat_clears_idle_badge_for_peer_unit():
    """After AFK, chatting publishes player_update with idle=False to AOI peers."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t) if isinstance(t, str) else t)

        async def close(self, *a, **k):
            pass

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="IdleA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="IdleB", x=3, y=2, map_id=0)
        # Mutual AOI
        meta_a = wm.manager.get_meta(1)
        meta_b = wm.manager.get_meta(2)
        assert meta_a and meta_b
        meta_a["visible"] = {2}
        meta_b["visible"] = {1}
        meta_a["last_seen"] = time.monotonic() - (IDLE_SOFT + 5)
        b.sent.clear()
        _cid, _uid, outbound, _cm = await handle_message(
            1, 1, {"type": "chat", "channel": "global", "text": "back online"}
        )
        chats = [m for m in outbound if m.get("type") == "chat"]
        assert chats, outbound
        updates = [
            m
            for m in b.sent
            if m.get("type") == "player_update"
            and m.get("player_id") == 1
            and m.get("idle") is False
        ]
        assert updates, f"peer missing idle-clear update: {b.sent}"

    asyncio.run(scenario())


def test_emote_includes_zone(tmp_path, monkeypatch):
    db_path = tmp_path / "emz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ea@ex.com", "Ea", "EmoteA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                m = await recv_until(ws, "emote", "error")
                assert m.get("type") == "emote", m
                assert m.get("zone") in ("town", "field", "dungeon"), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_chat_not_in_zone_unit():
    """Zone chat from non-walkable tile is rejected (no silent empty room)."""
    from network.message_handler import handle_message
    from network import websocket_manager as wm

    async def scenario():
        wm.reset_manager()

        class FakeWS:
            def __init__(self):
                self.sent = []

            async def send_text(self, t):
                self.sent.append(json.loads(t) if isinstance(t, str) else t)

            async def close(self, *a, **k):
                pass

        a = FakeWS()
        await wm.manager.connect(1, a, name="WallHero", x=0, y=0, map_id=0)
        # Tile 0,0 is blocked — not town/field/dungeon
        _cid, _uid, outbound, _cm = await handle_message(
            1, 1, {"type": "chat", "channel": "zone", "text": "hello wall"}
        )
        errs = [m for m in outbound if m.get("type") == "error"]
        assert errs, outbound
        assert errs[0].get("reason") == "not in a zone", errs

    asyncio.run(scenario())


def test_three_player_zone_chat_still_works(tmp_path, monkeypatch):
    db_path = tmp_path / "z3.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "Za", "ZoneA")
        tb, cb = register_char(base, "zb@ex.com", "Zb", "ZoneB")
        tc, cc = register_char(base, "zc@ex.com", "Zc", "ZoneC")

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
                    json.dumps(
                        {"type": "chat", "channel": "zone", "text": "z3-hi"}
                    )
                )
                ma = await recv_until(wa, "chat", "error")
                assert ma.get("type") == "chat" and ma.get("channel") == "zone", ma
                mb = await recv_until(wb, "chat", "error")
                mc = await recv_until(wc, "chat", "error")
                assert mb.get("text") == "z3-hi", mb
                assert mc.get("text") == "z3-hi", mc

        asyncio.run(flow())
    finally:
        stop_server(server)
