"""v0.5.63 multiplayer reliability: force online on leave; session_id on social; look/who AFK."""

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
    await drain(ws, 0.12)
    return m


def test_disconnect_forces_online_pulse_unit():
    """Leave must force online pulse (not only debounced)."""
    mgr = ConnectionManager()

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t) if isinstance(t, str) else t)

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        # Saturate debounce window
        mgr._last_online_pulse = time.monotonic()
        b.sent.clear()
        await mgr.disconnect(1, a, reason="disconnect")
        # B should still receive an online pulse with count 1
        onlines = [m for m in b.sent if m.get("type") == "online"]
        assert onlines, f"no online pulse on leave: {b.sent}"
        assert int(onlines[-1].get("online") or 0) == 1, onlines[-1]
        roster = onlines[-1].get("roster") or []
        names = {str(c.get("name") or "") for c in roster}
        assert "A" not in names and "B" in names, roster

    asyncio.run(scenario())


def test_chat_and_emote_include_session_id(tmp_path, monkeypatch):
    db_path = tmp_path / "sid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "SidA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "SidB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                aa = await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                sid = aa.get("session_id")
                await asyncio.sleep(0.85)
                await drain(wb)
                await wa.send(
                    json.dumps(
                        {"type": "chat", "channel": "nearby", "text": "sid-chat"}
                    )
                )
                ma = await recv_until(wa, "chat", "error")
                assert ma.get("type") == "chat", ma
                assert ma.get("session_id") == sid, ma
                mb = await recv_until(wb, "chat", "error")
                assert mb.get("text") == "sid-chat" and mb.get("session_id") == sid, mb

                await asyncio.sleep(0.85)
                await drain(wb)
                await wa.send(json.dumps({"type": "emote", "emote": "wave"}))
                ea = await recv_until(wa, "emote", "error")
                assert ea.get("type") == "emote" and ea.get("session_id") == sid, ea
                eb = await recv_until(wb, "emote", "error")
                assert eb.get("emote") == "wave" and eb.get("session_id") == sid, eb

                await asyncio.sleep(0.85)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "SidB", "text": "psst"})
                )
                wa_w = await recv_until(wa, "chat", "error")
                assert wa_w.get("channel") == "whisper" and wa_w.get("session_id") == sid

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_look_includes_session_and_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "look.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "la@ex.com", "La", "LookA")
        tb, cb = register_char(base, "lb@ex.com", "Lb", "LookB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                ab = await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")
                await wa.send(json.dumps({"type": "look", "name": "LookB"}))
                m = await recv_until(wa, "look", "error")
                assert m.get("type") == "look", m
                p = m.get("player") or {}
                assert p.get("session_id") == ab.get("session_id"), p
                assert p.get("afk") is True or p.get("idle") is True, p
                assert "nearby" in p

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_who_you_includes_afk_and_session(tmp_path, monkeypatch):
    db_path = tmp_path / "who.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "Wa", "WhoYouA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                aa = await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk"}))
                await recv_until(ws, "afk", "error")
                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who")
                you = who.get("you") or {}
                assert you.get("session_id") == aa.get("session_id"), you
                assert you.get("afk") is True, you
                assert you.get("idle") is True, you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_two_player_leave_online_count(tmp_path, monkeypatch):
    """When one of two players quits, the remaining sees online=1 promptly."""
    db_path = tmp_path / "lv.db"
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
                    await recv_until(wa, "quit", "error")
                # StayB should get forced online pulse soon
                deadline = time.monotonic() + 2.0
                saw = False
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.3)
                        m = json.loads(raw)
                        if m.get("type") == "online" and int(m.get("online") or 0) == 1:
                            saw = True
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                if not saw:
                    await wb.send(json.dumps({"type": "counts"}))
                    c = await recv_until(wb, "counts")
                    assert int(c.get("online") or 0) == 1, c
                else:
                    assert saw

        asyncio.run(flow())
    finally:
        stop_server(server)
