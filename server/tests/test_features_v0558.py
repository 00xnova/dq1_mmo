"""v0.5.58: MOTD, AFK/back, block alias, quit leave."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, _is_idle
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


def test_is_idle_respects_manual_afk_unit():
    meta = {
        "id": 1,
        "name": "A",
        "last_seen": time.monotonic(),
        "afk": True,
    }
    assert _is_idle(meta) is True
    meta["afk"] = False
    assert _is_idle(meta) is False


def test_set_afk_unit():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=0)
        assert mgr.set_afk(1, True) is True
        assert mgr.get_meta(1).get("afk") is True
        assert _is_idle(mgr.get_meta(1)) is True
        assert mgr.set_afk(1, False) is True
        assert mgr.get_meta(1).get("afk") is False
        assert mgr.set_afk(99, True) is False

    asyncio.run(scenario())


def test_motd(tmp_path, monkeypatch):
    db_path = tmp_path / "motd.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "m@ex.com", "Mu", "MotdHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "motd"}))
                m = await recv_until(ws, "motd", "error")
                assert m.get("type") == "motd", m
                assert m.get("text"), m
                assert m.get("version") == config.VERSION, m
                assert isinstance(m.get("online"), int), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_afk_and_back(tmp_path, monkeypatch):
    db_path = tmp_path / "afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Au", "AfkHero")
        tb, cb = register_char(base, "b@ex.com", "Bu", "PeerHero")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wb)
                await wa.send(json.dumps({"type": "afk"}))
                m = await recv_until(wa, "afk", "error")
                assert m.get("type") == "afk" and m.get("afk") is True, m
                # Peer should see idle update
                deadline = time.monotonic() + 2.0
                saw_idle = False
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.25)
                        msg = json.loads(raw)
                        if (
                            msg.get("type") == "player_update"
                            and msg.get("player_id") == ca["id"]
                            and msg.get("idle") is True
                        ):
                            saw_idle = True
                            break
                        if msg.get("type") == "online":
                            for card in msg.get("roster") or []:
                                if card.get("id") == ca["id"] and card.get("idle"):
                                    saw_idle = True
                                    break
                            if saw_idle:
                                break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                assert saw_idle, "peer did not see AFK idle"

                await wa.send(json.dumps({"type": "back"}))
                m2 = await recv_until(wa, "afk", "error")
                assert m2.get("type") == "afk" and m2.get("afk") is False, m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_block_alias_for_ignore(tmp_path, monkeypatch):
    db_path = tmp_path / "blk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ba@ex.com", "Ba", "BlockA")
        tb, cb = register_char(base, "bb@ex.com", "Bb", "BlockB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "block", "name": "BlockB"}))
                m = await recv_until(wa, "ignore", "error")
                assert m.get("type") == "ignore" and m.get("ok") is True, m
                assert m.get("action") == "ignore", m
                await wa.send(json.dumps({"type": "unblock", "name": "BlockB"}))
                m2 = await recv_until(wa, "ignore", "error")
                assert m2.get("type") == "ignore" and m2.get("action") == "unignore", m2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_quit_leaves_world(tmp_path, monkeypatch):
    db_path = tmp_path / "quit.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "qa@ex.com", "Qa", "QuitA")
        tb, cb = register_char(base, "qb@ex.com", "Qb", "StayB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await auth(wb, tb, cb["id"])
                async with websockets.connect(ws_url) as wa:
                    await auth(wa, ta, ca["id"])
                    await wa.send(json.dumps({"type": "quit"}))
                    m = await recv_until(wa, "quit", "error")
                    assert m.get("type") == "quit" and m.get("ok") is True, m
                await asyncio.sleep(0.4)
                await wb.send(json.dumps({"type": "who"}))
                who = await recv_until(wb, "who")
                assert int(who.get("online") or 0) == 1, who
                names = {
                    str(c.get("name") or "").lower() for c in (who.get("roster") or [])
                }
                assert "quita" not in names, names

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_mentions_motd_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "hlp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hu", "Help58")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                m = await recv_until(ws, "help")
                cmds = {c.get("cmd") for c in (m.get("commands") or [])}
                assert "motd" in cmds, cmds
                assert "afk" in cmds, cmds
                assert "quit" in cmds, cmds
                assert "block" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_chat_clears_manual_afk_unit():
    """allow_chat clears afk flag (social activity)."""
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
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        wm.manager.set_afk(1, True)
        assert wm.manager.get_meta(1).get("afk") is True
        _c, _u, outbound, _ = await handle_message(
            1, 1, {"type": "chat", "channel": "global", "text": "hi"}
        )
        assert any(m.get("type") == "chat" for m in outbound), outbound
        assert wm.manager.get_meta(1).get("afk") is False

    asyncio.run(scenario())
