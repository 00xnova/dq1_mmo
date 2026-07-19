"""v0.5.90 multiplayer: emote shortcuts, last-emote @last, nearby_combat, busy."""

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


def test_wave_shortcut_and_lastemote(tmp_path, monkeypatch):
    db_path = tmp_path / "wave.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "WaveA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "WaveB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Bare lastemote empty
                await wa.send(json.dumps({"type": "lastemote"}))
                le0 = await recv_until(wa, "lastemote", "error")
                assert le0.get("type") == "lastemote", le0
                assert le0.get("peer") is None

                # Shortcut directed wave
                await wa.send(json.dumps({"type": "wave", "to": "WaveB"}))
                em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em
                assert em.get("emote") == "wave"
                assert em.get("to") == "WaveB"
                assert em.get("to_id") == cb["id"]
                assert "WaveB" in str(em.get("message") or "")

                peer = await recv_until(wb, "emote", "error")
                assert peer.get("type") == "emote"
                assert peer.get("to") == "WaveB"

                # lastemote remembers target
                await wa.send(json.dumps({"type": "lastemote"}))
                le = await recv_until(wa, "lastemote", "error")
                assert le.get("type") == "lastemote"
                assert (le.get("peer") or {}).get("id") == cb["id"]
                assert (le.get("peer") or {}).get("name") == "WaveB"
                assert (le.get("peer") or {}).get("online") is True

                await asyncio.sleep(0.85)

                # @last directed emote
                await wa.send(json.dumps({"type": "bow", "to": "@last"}))
                em2 = await recv_until(wa, "emote", "error")
                assert em2.get("type") == "emote", em2
                assert em2.get("emote") == "bow"
                assert em2.get("to") == "WaveB"
                await recv_until(wb, "emote", "error")

                # reply:true form
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "cheer", "reply": True}))
                em3 = await recv_until(wa, "emote", "error")
                assert em3.get("type") == "emote"
                assert em3.get("emote") == "cheer"
                assert em3.get("to_id") == cb["id"]

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_nearby_combat_census(tmp_path, monkeypatch):
    db_path = tmp_path / "ncombat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c1@ex.com", "C1", "FightA")
        tb, cb = register_char(base, "c2@ex.com", "C2", "FightB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "near"}))
                n0 = await recv_until(wa, "near", "error")
                assert "nearby_combat" in n0, n0
                assert int(n0.get("nearby_combat") or 0) == 0

                await wb.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 1})
                )
                await recv_until(wb, "combat_start", "error")

                await wa.send(json.dumps({"type": "near"}))
                n1 = await recv_until(wa, "near", "error")
                assert int(n1.get("nearby_combat") or 0) >= 1, n1

                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who", "error")
                assert int(who.get("nearby_combat") or 0) >= 1, who

                await wa.send(json.dumps({"type": "counts"}))
                c = await recv_until(wa, "counts", "error")
                assert int(c.get("nearby_combat") or 0) >= 1, c

                await wa.send(json.dumps({"type": "ping", "t": 1}))
                pong = await recv_until(wa, "pong", "error")
                assert int(pong.get("nearby_combat") or 0) >= 1, pong

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_busy_afk_and_soft_lastemote(tmp_path, monkeypatch):
    db_path = tmp_path / "busy.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b1@ex.com", "B1", "BusyA")
        tb, cb = register_char(base, "b2@ex.com", "B2", "BusyB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "busy", "text": "brb"}))
                afk = await recv_until(wa, "afk", "error")
                assert afk.get("type") == "afk"
                assert afk.get("afk") is True
                assert afk.get("afk_message") == "brb"

                await wa.send(json.dumps({"type": "status"}))
                st = await recv_until(wa, "status")
                assert (st.get("you") or {}).get("afk") is True

                await wa.send(json.dumps({"type": "back"}))
                await recv_until(wa, "afk")

                # Directed emote then soft reconnect keeps lastemote
                await wa.send(json.dumps({"type": "wave", "to": "BusyB"}))
                await recv_until(wa, "emote", "error")
                await recv_until(wb, "emote", "error")

                await wa.close()
                await asyncio.sleep(0.25)

                async with websockets.connect(ws_url) as wa2:
                    await auth(wa2, ta, ca["id"])
                    await drain(wa2, 0.15)
                    await wa2.send(json.dumps({"type": "lastemote"}))
                    le = await recv_until(wa2, "lastemote", "error")
                    assert (le.get("peer") or {}).get("name") == "BusyB", le
                    assert (le.get("peer") or {}).get("online") is True

                    await asyncio.sleep(0.85)
                    await wa2.send(json.dumps({"type": "wave", "to": "last"}))
                    em = await recv_until(wa2, "emote", "error")
                    assert em.get("type") == "emote", em
                    assert em.get("to") == "BusyB"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_mp_regressions_whisper_yell(tmp_path, monkeypatch):
    db_path = tmp_path / "reg90.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "Reg90A")
        tb, cb = register_char(base, "s@ex.com", "Ss", "Reg90B")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps({"type": "whisper", "to": "Reg90B", "text": "hi"})
                )
                e = await recv_until(wa, "chat", "error")
                assert e.get("channel") == "whisper"
                await recv_until(wb, "chat", "error")

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "yell", "text": "yo zone"}))
                y = await recv_until(wa, "chat", "error")
                assert y.get("channel") == "zone"

                await wa.send(json.dumps({"type": "sync"}))
                ws = await recv_until(wa, "world_state", "error")
                assert "nearby_combat" in ws, ws

        asyncio.run(flow())
    finally:
        stop_server(server)
