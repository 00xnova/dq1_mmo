"""v0.5.74 adversarial lock-in: combat gates, chat overrides, qty/move edges, peeks."""

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


def test_double_combat_and_combat_gates(tmp_path, monkeypatch):
    """Second encounter rejected; equip/shop/inn blocked mid-fight; flee OOC."""
    db_path = tmp_path / "cbt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CbtHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                st = await recv_until(ws, "combat_start", "error")
                assert st.get("type") == "combat_start", st

                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                m = await recv_until(ws, "error", "combat_start")
                assert m.get("type") == "error" and "combat" in str(m.get("reason")), m

                await ws.send(json.dumps({"type": "shop"}))
                m = await recv_until(ws, "error", "shop_list")
                assert m.get("type") == "error" and m.get("reason") == "in combat", m

                await ws.send(json.dumps({"type": "rest", "preview": True}))
                m = await recv_until(ws, "error", "rest_ok")
                assert m.get("type") == "error" and m.get("reason") == "in combat", m

                await ws.send(json.dumps({"type": "equip", "item": "club", "slot": "weapon"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and m.get("reason") == "in combat", m

                await ws.send(json.dumps({"type": "flee"}))
                await drain(ws, 0.4)

                await ws.send(json.dumps({"type": "flee"}))
                m = await recv_until(ws, "error", "combat_end")
                assert m.get("type") == "error" and "combat" in str(m.get("reason")), m

                await ws.send(json.dumps({"type": "attack"}))
                m = await recv_until(ws, "error", "combat_update")
                assert m.get("type") == "error" and "combat" in str(m.get("reason")), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_chat_channel_overrides_and_sanitize(tmp_path, monkeypatch):
    """type g/s respect channel override; control chars stripped; whisper needs target."""
    db_path = tmp_path / "ch.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ch@ex.com", "Ch", "ChatHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "chat", "text": "hi\x00\x01there"}))
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert "\x00" not in str(m.get("text")) and "hithere" in str(m.get("text")).replace(
                    " ", ""
                ), m

                await asyncio.sleep(0.85)
                await ws.send(
                    json.dumps({"type": "g", "text": "zone via g", "channel": "zone"})
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat" and m.get("channel") == "zone", m

                await asyncio.sleep(0.85)
                await ws.send(
                    json.dumps({"type": "s", "text": "global via s", "channel": "global"})
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat" and m.get("channel") == "global", m

                await asyncio.sleep(0.85)
                await ws.send(
                    json.dumps({"type": "chat", "text": "nope", "channel": "whisper"})
                )
                m = await recv_until(ws, "error", "chat")
                assert m.get("type") == "error" and "target" in str(m.get("reason")), m

                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "g", "text": "  \t  "}))
                m = await recv_until(ws, "error", "chat")
                assert m.get("type") == "error" and m.get("reason") == "empty chat", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_qty_move_find_edges(tmp_path, monkeypatch):
    """Bad qty strings, wall/far moves, invalid idle filter, find empty."""
    db_path = tmp_path / "qty.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "q@ex.com", "Qq", "QtyHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(
                    json.dumps({"type": "discard", "item": "herb", "quantity": "abc"})
                )
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and m.get("reason") == "bad quantity", m

                await ws.send(json.dumps({"type": "buy", "item": "herb", "quantity": "0"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and m.get("reason") == "bad quantity", m

                await ws.send(json.dumps({"type": "buy", "item": "herb", "quantity": True}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and m.get("reason") == "bad quantity", m

                await ws.send(json.dumps({"type": "move", "x": 0, "y": 0, "seq": 5}))
                m = await recv_until(ws, "move_ok", "error")
                assert (m.get("type") == "error") or (
                    m.get("type") == "move_ok" and m.get("ok") is False
                ), m

                await ws.send(json.dumps({"type": "move", "x": 15, "y": 10, "seq": 6}))
                m = await recv_until(ws, "move_ok", "error")
                assert (m.get("type") == "error") or (
                    m.get("type") == "move_ok" and m.get("ok") is False
                ), m
                await drain(ws, 0.2)

                await ws.send(json.dumps({"type": "find", "query": "idle:maybe"}))
                m = await recv_until(ws, "error", "find")
                assert m.get("type") == "error" and "idle" in str(m.get("reason")), m

                await ws.send(json.dumps({"type": "find", "query": ""}))
                m = await recv_until(ws, "error", "find")
                assert m.get("type") == "error", m

                await ws.send(json.dumps({"type": "find", "query": "'; DROP--"}))
                m = await recv_until(ws, "find", "error")
                assert m.get("type") in ("find", "error"), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_played_aliases_and_herb_full_order(tmp_path, monkeypatch):
    """played aliases; herb at full HP errors before inventory_update; peeks under spam."""
    db_path = tmp_path / "pl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PlayAdv")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for t in ("online_time", "session_time", "played"):
                    await ws.send(json.dumps({"type": t}))
                    m = await recv_until(ws, "played", "error")
                    assert m.get("type") == "played", m
                    assert int(m.get("seconds") or 0) >= 0
                    assert m.get("session_id") is not None
                    assert "zone" in m

                await ws.send(json.dumps({"type": "use_item", "item": "herb"}))
                m1 = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                m2 = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                assert m1.get("type") == "error" and "full" in str(m1.get("reason")), m1
                assert m2.get("type") == "inventory_update", m2

                # rate-exempt played spam
                for _ in range(20):
                    await ws.send(json.dumps({"type": "played"}))
                ok_n = err_n = 0
                end = time.monotonic() + 2.0
                while time.monotonic() < end:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 0.2))
                        if m.get("type") == "played":
                            ok_n += 1
                        if m.get("type") == "error" and m.get("reason") == "rate_limit":
                            err_n += 1
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert err_n == 0 and ok_n >= 10, (ok_n, err_n)

                await ws.send(json.dumps({"type": "mapinfo"}))
                z = await recv_until(ws, "zone", "error")
                assert z.get("type") == "zone" and z.get("session_id") is not None, z

                await ws.send(json.dumps({"type": "pos"}))
                assert (await recv_until(ws, "zone", "error")).get("type") == "zone"

                await ws.send(json.dumps({"type": "player_info"}))
                assert (await recv_until(ws, "look", "error")).get("type") == "look"

                await ws.send(json.dumps({"type": "unequip", "slot": "helmet"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m

                await ws.send(json.dumps({"type": "reply", "text": ""}))
                m = await recv_until(ws, "error", "chat")
                assert m.get("type") == "error", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_afk_whisper_and_failed_whisper_no_block(tmp_path, monkeypatch):
    """Whisper to AFK sets target_afk; failed whisper does not block next chat."""
    db_path = tmp_path / "afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AfkTgt")
        tb, cb = register_char(base, "b@ex.com", "Bb", "Talker")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)

                await wb.send(
                    json.dumps({"type": "whisper", "to": "AfkTgt", "text": "ping"})
                )
                echo = await recv_until(wb, "chat", "error")
                assert echo.get("type") == "chat" and echo.get("channel") == "whisper", echo
                assert echo.get("target_afk") is True, echo
                recv = await recv_until(wa, "chat", "error")
                assert recv.get("text") == "ping" and recv.get("target_afk") is not True

                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "whisper", "to": "NoSuchHero", "text": "x"})
                )
                err = await recv_until(wb, "error", "chat")
                assert err.get("type") == "error", err
                await wb.send(json.dumps({"type": "chat", "text": "still works"}))
                ok = await recv_until(wb, "chat", "error")
                assert ok.get("type") == "chat" and ok.get("text") == "still works", ok

                # channel=whisper with to= also flags AFK
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "whisper",
                            "to": "AfkTgt",
                            "text": "via-ch",
                        }
                    )
                )
                e2 = await recv_until(wb, "chat", "error")
                assert e2.get("channel") == "whisper" and e2.get("target_afk") is True, e2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_socket_replace_and_auth_failures(tmp_path, monkeypatch):
    """Triple replace keeps who healthy; bad token/char rejected."""
    db_path = tmp_path / "rp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RepHero")

        async def flow():
            import websockets

            socks = []
            try:
                for _ in range(3):
                    ws = await websockets.connect(ws_url)
                    socks.append(ws)
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": ta, "character_id": ca["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok", "auth_fail")
                await socks[-1].send(json.dumps({"type": "who"}))
                who = await recv_until(socks[-1], "who", "error")
                assert who.get("type") == "who" and int(who.get("online") or 0) >= 1, who
            finally:
                for ws in socks:
                    try:
                        await ws.close()
                    except Exception:
                        pass

            async with websockets.connect(ws_url) as bad:
                await bad.send(
                    json.dumps(
                        {"type": "auth", "token": "nope", "character_id": ca["id"]}
                    )
                )
                m = await recv_until(bad, "auth_fail", "error", "auth_ok")
                assert m.get("type") in ("auth_fail", "error"), m

            async with websockets.connect(ws_url) as bad:
                await bad.send(
                    json.dumps({"type": "auth", "token": ta, "character_id": 999999})
                )
                m = await recv_until(bad, "auth_fail", "error", "auth_ok")
                assert m.get("type") in ("auth_fail", "error"), m

        asyncio.run(flow())
    finally:
        stop_server(server)
