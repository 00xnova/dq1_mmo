"""v0.5.75: /stuck home recall, yell/shout zone chat, emote list catalog."""

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
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_stuck_returns_to_town(tmp_path, monkeypatch):
    db_path = tmp_path / "stuck.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "StuckHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Already at town spawn → no teleport
                await ws.send(json.dumps({"type": "stuck"}))
                m = await recv_until(ws, "stuck", "error")
                assert m.get("type") == "stuck", m
                assert m.get("teleported") is False, m
                assert "already" in str(m.get("message") or "").lower(), m

                # Walk into field then stuck
                await asyncio.sleep(0.15)
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                await recv_until(ws, "move_ok", "error")
                await asyncio.sleep(0.15)
                # Path toward field: keep walking east if possible
                seq = 2
                for x, y in ((4, 2), (5, 2), (5, 3), (6, 3), (6, 2)):
                    await asyncio.sleep(0.12)
                    await ws.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    await recv_until(ws, "move_ok", "error")
                    seq += 1
                await drain(ws, 0.15)

                await asyncio.sleep(0.85)  # chat rate for stuck
                await ws.send(json.dumps({"type": "home"}))
                # may get move_ok then stuck
                got = []
                end = time.monotonic() + 3.0
                while time.monotonic() < end and not any(
                    g.get("type") == "stuck" for g in got
                ):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 0.5)
                        got.append(json.loads(raw))
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                stuck = next((g for g in got if g.get("type") == "stuck"), None)
                assert stuck is not None, got
                assert stuck.get("ok") is True
                assert int(stuck.get("x") or 0) == 2 and int(stuck.get("y") or 0) == 2
                # If we moved away, teleported True; if still town, False is ok
                if stuck.get("teleported"):
                    assert stuck.get("zone") == "town"

                # Combat blocks stuck
                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                st = await recv_until(ws, "combat_start", "error")
                if st.get("type") == "combat_start":
                    await ws.send(json.dumps({"type": "unstuck"}))
                    err = await recv_until(ws, "error", "stuck")
                    assert err.get("type") == "error" and err.get("reason") == "in combat", err
                    await ws.send(json.dumps({"type": "flee"}))
                    await drain(ws, 0.3)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_yell_and_shout_zone_chat(tmp_path, monkeypatch):
    db_path = tmp_path / "yell.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "y1@ex.com", "Y1", "YellA")
        tb, cb = register_char(base, "y2@ex.com", "Y2", "YellB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "yell", "text": "hello zone"}))
                echo = await recv_until(wa, "chat", "error")
                assert echo.get("type") == "chat" and echo.get("channel") == "zone", echo
                peer = await recv_until(wb, "chat", "error")
                assert peer.get("channel") == "zone" and peer.get("text") == "hello zone"

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "shout", "text": "shout zone"}))
                e2 = await recv_until(wa, "chat", "error")
                assert e2.get("channel") == "zone", e2

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "yell", "text": "   "}))
                err = await recv_until(wa, "error", "chat")
                assert err.get("type") == "error" and err.get("reason") == "empty chat", err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_emote_list_catalog(tmp_path, monkeypatch):
    db_path = tmp_path / "em.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EmoteHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "emotes"}))
                m = await recv_until(ws, "emotes", "error", "emote")
                assert m.get("type") == "emotes", m
                em = m.get("emotes") or []
                assert "wave" in em and "bow" in em and len(em) >= 5, em
                assert "Emotes:" in str(m.get("message") or ""), m

                await ws.send(json.dumps({"type": "emote", "emote": "list"}))
                m2 = await recv_until(ws, "emotes", "error", "emote")
                assert m2.get("type") == "emotes", m2

                # bare emote still waves (API compat)
                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "emote"}))
                e = await recv_until(ws, "emote", "error")
                assert e.get("type") == "emote" and e.get("emote") == "wave", e

                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "emote", "emote": "notreal"}))
                err = await recv_until(ws, "error", "emote")
                assert err.get("type") == "error" and "emote" in str(err.get("reason")), err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_mentions_stuck_and_yell(tmp_path, monkeypatch):
    db_path = tmp_path / "hlp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpStuck")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h).lower()
                assert "stuck" in blob
                assert "yell" in blob or "shout" in blob

        asyncio.run(flow())
    finally:
        stop_server(server)
