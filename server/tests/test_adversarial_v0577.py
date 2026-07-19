"""v0.5.77 adversarial lock-in: stuck edges, afk_for, ignore whisper, ambiguous names."""

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
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)
    return m


def test_stuck_auth_combat_and_home_rate(tmp_path, monkeypatch):
    db_path = tmp_path / "stk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "StuckAdv")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as bare:
                await bare.send(json.dumps({"type": "stuck"}))
                m = await recv_until(bare, "error", "stuck")
                assert m.get("type") == "error" and "auth" in str(m.get("reason")), m

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "stuck"}))
                home = await recv_until(ws, "stuck", "error")
                assert home.get("type") == "stuck" and home.get("teleported") is False, home
                # no rate burn
                await ws.send(json.dumps({"type": "yell", "text": "hi zone"}))
                c = await recv_until(ws, "chat", "error")
                assert c.get("type") == "chat" and c.get("channel") == "zone", c

                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                st = await recv_until(ws, "combat_start", "error")
                assert st.get("type") == "combat_start", st
                await ws.send(json.dumps({"type": "stuck"}))
                err = await recv_until(ws, "error", "stuck")
                assert err.get("type") == "error" and err.get("reason") == "in combat", err
                await ws.send(json.dumps({"type": "flee"}))
                await drain(ws, 0.35)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_ambiguous_prefix_and_afk_for_clean(tmp_path, monkeypatch):
    db_path = tmp_path / "amb.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AdvA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "AdvB")
        tc, cc = register_char(base, "c@ex.com", "Cc", "AdvC")

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
                await drain(wa)
                await drain(wb)
                await drain(wc)

                await wa.send(json.dumps({"type": "look", "name": "Adv"}))
                m = await recv_until(wa, "look", "error")
                assert m.get("type") == "error" and m.get("reason") == "name ambiguous", m

                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")
                await asyncio.sleep(0.08)
                await drain(wa)
                await wa.send(json.dumps({"type": "look", "name": "AdvB"}))
                look = await recv_until(wa, "look", "error")
                assert look.get("type") == "look", look
                card = look.get("player") or {}
                assert card.get("afk") is True and "afk_for" in card, card

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_to_ignorer_after_drain(tmp_path, monkeypatch):
    db_path = tmp_path / "ign.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "i1@ex.com", "I1", "IgnA")
        tb, cb = register_char(base, "i2@ex.com", "I2", "IgnB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "ignore", "name": "IgnB"}))
                await recv_until(wa, "ignore", "ignores", "error")
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "whisper", "to": "IgnA", "text": "blocked"})
                )
                m = await recv_until(wb, "error", "chat")
                assert m.get("type") == "error" and m.get("reason") == "player unavailable", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_g_zone_override_and_shout(tmp_path, monkeypatch):
    db_path = tmp_path / "ch.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ch@ex.com", "Ch", "ChatOvr")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await drain(ws)
                await ws.send(
                    json.dumps({"type": "g", "text": "zone via g", "channel": "zone"})
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat" and m.get("channel") == "zone", m

                await asyncio.sleep(0.85)
                await drain(ws)
                await ws.send(
                    json.dumps({"type": "chat", "text": "shout!", "channel": "shout"})
                )
                m2 = await recv_until(ws, "chat", "error")
                assert m2.get("type") == "chat" and m2.get("channel") == "zone", m2

                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "yell", "text": "  "}))
                err = await recv_until(ws, "error", "chat")
                assert err.get("type") == "error" and err.get("reason") == "empty chat", err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_peek_and_auth_edges(tmp_path, monkeypatch):
    db_path = tmp_path / "pk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PeekHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for t in ("played", "buffs", "counts", "mapinfo", "emotes", "version"):
                    await ws.send(json.dumps({"type": t}))
                got = set()
                end = time.monotonic() + 3.0
                while time.monotonic() < end and len(got) < 5:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 0.4))
                        got.add(m.get("type"))
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert len(got) >= 5, got
                assert "played" in got and "emotes" in got

            async with websockets.connect(ws_url) as bad:
                await bad.send(
                    json.dumps(
                        {"type": "auth", "token": "nope", "character_id": ca["id"]}
                    )
                )
                m = await recv_until(bad, "auth_fail", "error", "auth_ok")
                assert m.get("type") in ("auth_fail", "error"), m

        asyncio.run(flow())
    finally:
        stop_server(server)
