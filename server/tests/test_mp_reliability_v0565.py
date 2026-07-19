"""v0.5.65 multiplayer reliability: AFK on presence, whisper AFK, lastwhisper, soft reconnect."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, _online_card, _public_meta
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


def test_online_card_and_public_meta_include_afk():
    """Unit: roster / nearby cards always expose manual AFK."""
    meta = {
        "id": 1,
        "name": "Hero",
        "x": 2.0,
        "y": 2.0,
        "map_id": 0,
        "level": 3,
        "in_combat": False,
        "afk": True,
        "last_seen": time.monotonic(),
        "session_id": 9,
    }
    card = _online_card(meta)
    pub = _public_meta(meta)
    assert card.get("afk") is True and card.get("idle") is True, card
    assert pub.get("afk") is True and pub.get("idle") is True, pub
    assert card.get("session_id") == 9 and pub.get("session_id") == 9

    meta["afk"] = False
    card2 = _online_card(meta)
    assert card2.get("afk") is False, card2


def test_who_roster_and_player_update_show_afk(tmp_path, monkeypatch):
    """Peers see AFK on who roster and player_update after /afk."""
    db_path = tmp_path / "afk_pres.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AfkA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "AfkB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                # Same spawn → AOI so player_update reaches A
                await drain(wa, 0.15)
                await wb.send(json.dumps({"type": "afk"}))
                afk_ack = await recv_until(wb, "afk", "error")
                assert afk_ack.get("type") == "afk" and afk_ack.get("afk") is True
                assert afk_ack.get("session_id") is not None, afk_ack

                # A should see player_update with afk
                deadline = time.monotonic() + 2.0
                saw_update = False
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wa.recv(), 0.25)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "player_update"
                            and m.get("player_id") == cb["id"]
                            and m.get("afk") is True
                        ):
                            saw_update = True
                            break
                        if m.get("type") == "online":
                            roster = m.get("roster") or []
                            for c in roster:
                                if c.get("id") == cb["id"] and c.get("afk") is True:
                                    saw_update = True
                                    break
                            if saw_update:
                                break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                assert saw_update, "peer never saw AFK via player_update/online"

                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who")
                roster = who.get("players") or who.get("roster") or []
                b_card = next((c for c in roster if c.get("id") == cb["id"]), None)
                if b_card is None:
                    # some payloads nest under online
                    for key in ("players", "roster", "online_players"):
                        roster = who.get(key) or roster
                    b_card = next(
                        (c for c in roster if str(c.get("name") or "") == "AfkB"),
                        None,
                    )
                assert b_card is not None, who
                assert b_card.get("afk") is True, b_card
                assert b_card.get("idle") is True, b_card

                await wa.send(json.dumps({"type": "find", "q": "AfkB"}))
                fr = await recv_until(wa, "find", "error")
                assert fr.get("type") == "find", fr
                hits = fr.get("players") or fr.get("results") or []
                hit = next((h for h in hits if h.get("name") == "AfkB"), None)
                assert hit is not None and hit.get("afk") is True, fr

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_target_afk_flag_and_lastwhisper(tmp_path, monkeypatch):
    """Whisper to AFK peer flags target_afk; lastwhisper tracks peer for /r."""
    db_path = tmp_path / "wafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "Wa", "WhA")
        tb, cb = register_char(base, "wb@ex.com", "Wb", "WhB")

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

                await asyncio.sleep(0.85)
                await drain(wa)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "WhB", "text": "hey afk"})
                )
                m = await recv_until(wa, "chat", "error")
                assert m.get("type") == "chat" and m.get("channel") == "whisper", m
                assert m.get("target_afk") is True, m
                assert m.get("session_id") is not None, m

                # Target still receives whisper (no target_afk on their copy)
                mb = await recv_until(wb, "chat", "error")
                assert mb.get("text") == "hey afk" and mb.get("channel") == "whisper"
                assert mb.get("target_afk") is not True, mb

                await wa.send(json.dumps({"type": "lastwhisper"}))
                lw = await recv_until(wa, "lastwhisper", "error")
                assert lw.get("type") == "lastwhisper", lw
                peer = lw.get("peer") or {}
                assert peer.get("id") == cb["id"], lw
                assert peer.get("name") == "WhB", lw
                assert peer.get("online") is True, lw
                assert peer.get("afk") is True, lw
                assert peer.get("session_id") == ab.get("session_id"), peer

                # Empty lastwhisper for C is covered by no peer — B replies
                await asyncio.sleep(0.85)
                await drain(wb)
                await wb.send(json.dumps({"type": "back"}))
                await recv_until(wb, "afk", "error")
                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "reply", "text": "back now"})
                )
                r = await recv_until(wb, "chat", "error")
                assert r.get("type") == "chat" and r.get("text") == "back now", r
                ra = await recv_until(wa, "chat", "error")
                assert ra.get("text") == "back now", ra

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_lastwhisper_empty_and_soft_reconnect(tmp_path, monkeypatch):
    """lastwhisper empty when no peer; soft reconnect restores last whisper target."""
    db_path = tmp_path / "lwsoft.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "SoftA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "SoftB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
                await wa.send(json.dumps({"type": "last"}))
                empty = await recv_until(wa, "lastwhisper", "error")
                assert empty.get("type") == "lastwhisper", empty
                assert empty.get("peer") is None, empty

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.85)
                await drain(wa)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "SoftB", "text": "sticky"})
                )
                await recv_until(wa, "chat", "error")
                await recv_until(wb, "chat", "error")

            # Soft reconnect A — last whisper should survive grace
            async with websockets.connect(ws_url) as wa2:
                await auth(wa2, ta, ca["id"])
                await wa2.send(json.dumps({"type": "last_whisper"}))
                lw = await recv_until(wa2, "lastwhisper", "error")
                peer = lw.get("peer") or {}
                assert peer.get("name") == "SoftB", lw
                # SoftB not online now
                assert peer.get("online") is False, peer

                # reply while target offline fails cleanly
                await asyncio.sleep(0.85)
                await wa2.send(json.dumps({"type": "reply", "text": "miss you"}))
                err = await recv_until(wa2, "error", "chat")
                assert err.get("type") == "error"
                assert "online" in str(err.get("reason") or "").lower(), err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_leave_online_still_forces_pulse(tmp_path, monkeypatch):
    """Regression: forced online pulse on leave (old reliability path)."""
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
        # A goes AFK — online card must carry afk after status pulse path
        mgr.set_afk(1, True)
        card = _online_card(mgr.get_meta(1))
        assert card.get("afk") is True, card
        mgr._last_online_pulse = time.monotonic()
        b.sent.clear()
        await mgr.disconnect(1, a, reason="disconnect")
        onlines = [m for m in b.sent if m.get("type") == "online"]
        assert onlines, f"no online pulse: {b.sent}"
        assert int(onlines[-1].get("online") or 0) == 1
        names = {str(c.get("name") or "") for c in (onlines[-1].get("roster") or [])}
        assert "A" not in names and "B" in names

    asyncio.run(scenario())


def test_zone_roster_includes_afk(tmp_path, monkeypatch):
    """zone/whereami mates cards include afk for multiplayer overview."""
    db_path = tmp_path / "zoneafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "Za", "ZoneA")
        tb, cb = register_char(base, "zb@ex.com", "Zb", "ZoneB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")
                await wa.send(json.dumps({"type": "whereami"}))
                z = await recv_until(wa, "zone", "error")
                assert z.get("type") == "zone", z
                mates = z.get("players") or z.get("mates") or z.get("roster") or []
                b = next((p for p in mates if p.get("name") == "ZoneB"), None)
                assert b is not None, z
                assert b.get("afk") is True, b

        asyncio.run(flow())
    finally:
        stop_server(server)
