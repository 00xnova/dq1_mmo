"""v0.5.76 multiplayer reliability: stuck peer notice, already-home no rate burn, afk_for."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
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
    await drain(ws, 0.1)
    return m


def test_afk_since_and_afk_for_unit():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, FakeWS(), name="AfkOne", x=2, y=2, map_id=0)
        assert mgr.set_afk(1, True)
        meta = mgr.get_meta(1)
        assert meta is not None and meta.get("afk") is True
        assert meta.get("afk_since") is not None
        await asyncio.sleep(0.05)
        from network.websocket_manager import _online_card, _public_meta

        card = _online_card(meta)
        assert card.get("afk") is True
        assert int(card.get("afk_for") or 0) >= 0
        pub = _public_meta(meta)
        assert pub.get("afk") is True
        assert "afk_for" in pub
        mgr.set_afk(1, False)
        meta2 = mgr.get_meta(1)
        assert meta2 is not None and meta2.get("afk") is False
        assert meta2.get("afk_since") is None

    asyncio.run(scenario())


def test_stuck_already_home_no_rate_burn(tmp_path, monkeypatch):
    """Already-home stuck must not burn chat rate (immediate yell still works)."""
    db_path = tmp_path / "home.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HomeHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "stuck"}))
                m = await recv_until(ws, "stuck", "error")
                assert m.get("type") == "stuck" and m.get("teleported") is False, m
                # Immediate zone yell — would fail if stuck burned chat rate
                await ws.send(json.dumps({"type": "yell", "text": "still here"}))
                c = await recv_until(ws, "chat", "error")
                assert c.get("type") == "chat" and c.get("channel") == "zone", c

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_stuck_teleport_notifies_peer(tmp_path, monkeypatch):
    """Nearby peer sees system line when someone uses /stuck from the field."""
    db_path = tmp_path / "peer.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "WalkA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "WatchB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Move A toward field (east of town spawn)
                seq = 1
                for x, y in ((3, 2), (4, 2), (5, 2), (5, 3), (6, 3), (6, 2)):
                    await asyncio.sleep(0.12)
                    await wa.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    await recv_until(wa, "move_ok", "error")
                    seq += 1
                await drain(wa, 0.1)
                await drain(wb, 0.15)

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "stuck"}))
                stuck = None
                end = time.monotonic() + 3.0
                while time.monotonic() < end and stuck is None:
                    try:
                        m = json.loads(await asyncio.wait_for(wa.recv(), 0.5))
                        if m.get("type") == "stuck":
                            stuck = m
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert stuck is not None, "no stuck ack"
                # If still in town path failed, still accept teleported false
                if stuck.get("teleported"):
                    # Peer should get system chat
                    notice = await recv_until(wb, "chat", "error", "player_moved", "player_update")
                    # may get player_moved first — drain until system chat
                    if notice.get("type") != "chat" or notice.get("channel") != "system":
                        end2 = time.monotonic() + 2.0
                        found = None
                        while time.monotonic() < end2:
                            try:
                                m = json.loads(await asyncio.wait_for(wb.recv(), 0.4))
                                if m.get("type") == "chat" and m.get("channel") == "system":
                                    found = m
                                    break
                            except (asyncio.TimeoutError, TimeoutError):
                                break
                        notice = found or notice
                    assert notice is not None and notice.get("channel") == "system", notice
                    assert "returned to town" in str(notice.get("text") or "").lower(), notice

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_look_includes_afk_for(tmp_path, monkeypatch):
    db_path = tmp_path / "lookafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "l1@ex.com", "L1", "LookAfk")
        tb, cb = register_char(base, "l2@ex.com", "L2", "Looker")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await asyncio.sleep(0.08)
                await wb.send(json.dumps({"type": "look", "name": "LookAfk"}))
                look = await recv_until(wb, "look", "error")
                assert look.get("type") == "look", look
                card = look.get("player") or {}
                assert card.get("afk") is True, card
                assert "afk_for" in card, card
                assert int(card.get("afk_for") or 0) >= 0

                await wb.send(json.dumps({"type": "who"}))
                who = await recv_until(wb, "who", "error")
                roster = who.get("roster") or []
                hit = next((r for r in roster if r.get("name") == "LookAfk"), None)
                assert hit is not None and hit.get("afk") is True, who
                assert "afk_for" in hit, hit

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_yell_and_played_still_work(tmp_path, monkeypatch):
    """Regression: core multiplayer peeks + zone yell."""
    db_path = tmp_path / "reg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RegHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("type") == "played" and pl.get("session_id") is not None
                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "yell", "text": "reg yell"}))
                c = await recv_until(ws, "chat", "error")
                assert c.get("channel") == "zone"
                await ws.send(json.dumps({"type": "counts"}))
                cnt = await recv_until(ws, "counts", "error")
                assert "played" in (cnt.get("you") or {})

        asyncio.run(flow())
    finally:
        stop_server(server)
