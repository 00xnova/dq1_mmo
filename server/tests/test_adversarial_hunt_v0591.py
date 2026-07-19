"""v0.5.91 adversarial hunt: force failures on id coercion, AFK, social edges."""

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
    out = []
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


def test_unit_coerce_and_afk_sanitize():
    from network.websocket_manager import (
        coerce_character_id,
        manager,
        sanitize_afk_message,
    )

    assert coerce_character_id(True) is None
    assert coerce_character_id(False) is None
    assert coerce_character_id(1.7) is None
    assert coerce_character_id(-1) is None
    assert coerce_character_id(0) is None
    assert coerce_character_id(3) == 3
    assert coerce_character_id(3.0) == 3
    assert coerce_character_id("7") == 7
    assert coerce_character_id("  7  ") == 7
    assert coerce_character_id("7.5") is None
    assert coerce_character_id(None) is None

    assert sanitize_afk_message(True) is None
    assert sanitize_afk_message(123) is None
    assert sanitize_afk_message(["x"]) is None
    assert sanitize_afk_message("  lunch  ") == "lunch"
    assert sanitize_afk_message("x" * 100) == "x" * 48

    class W:
        pass

    manager._connections.clear()
    manager._meta.clear()
    manager._connections[1] = W()
    manager._meta[1] = {"id": 1, "name": "Hero"}
    assert manager.find_id_by_player_id(True) is None
    assert manager.find_id_by_player_id(1.9) is None
    assert manager.find_id_by_player_id(1) == 1
    assert manager.find_id_by_player_id("1") == 1
    manager._connections.clear()
    manager._meta.clear()


def test_bool_to_id_cannot_target_player_one(tmp_path, monkeypatch):
    """Classic Python trap: int(True)==1 must not whisper/wave player #1."""
    db_path = tmp_path / "boolid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "BoolA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "BoolB")
        # Ensure first char is id 1-ish; we only care bool does not resolve
        assert ca["id"] >= 1

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Whisper with to_id: true must fail (not hit player 1)
                await wa.send(
                    json.dumps(
                        {
                            "type": "whisper",
                            "to_id": True,
                            "text": "bool trap",
                        }
                    )
                )
                err = await recv_until(wa, "error", "chat")
                assert err.get("type") == "error", err
                assert err.get("channel") != "whisper"
                # Peer must not receive
                leaked = await drain(wb, 0.2)
                assert not any(
                    m.get("type") == "chat" and m.get("channel") == "whisper"
                    for m in leaked
                ), leaked

                # Wave with to_id float 1.7 → must error, not undirected success
                await wa.send(json.dumps({"type": "wave", "to_id": 1.7}))
                err2 = await recv_until(wa, "error", "emote")
                assert err2.get("type") == "error", err2
                assert err2.get("reason") in (
                    "player not found",
                    "player not online",
                ), err2

                await wa.send(json.dumps({"type": "wave", "to_id": True}))
                err2b = await recv_until(wa, "error", "emote")
                assert err2b.get("type") == "error", err2b
                assert "not found" in str(err2b.get("reason") or "").lower(), err2b

                # Look with id:true must not open player 1 card
                await wa.send(json.dumps({"type": "look", "id": True}))
                err3 = await recv_until(wa, "error", "look")
                assert err3.get("type") == "error", err3
                assert "not found" in str(err3.get("reason") or "").lower(), err3

                # Valid digit-string id still works
                await wa.send(json.dumps({"type": "look", "player_id": str(cb["id"])}))
                ok = await recv_until(wa, "look", "error")
                assert ok.get("type") == "look", ok
                assert (ok.get("player") or {}).get("id") == cb["id"]

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_afk_bool_reason_not_stringified(tmp_path, monkeypatch):
    db_path = tmp_path / "afkbool.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "z@ex.com", "Zz", "AfkBool")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # text: true must not become AFK reason "True"
                await ws.send(json.dumps({"type": "afk", "text": True}))
                ack = await recv_until(ws, "afk", "error")
                assert ack.get("type") == "afk"
                assert ack.get("afk") is True
                assert not ack.get("afk_message"), ack
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                you = st.get("you") or {}
                assert you.get("afk") is True
                assert not you.get("afk_message"), you

                await ws.send(json.dumps({"type": "back"}))
                await recv_until(ws, "afk")

                await ws.send(json.dumps({"type": "busy", "reason": 99}))
                ack2 = await recv_until(ws, "afk", "error")
                assert ack2.get("afk") is True
                assert not ack2.get("afk_message"), ack2

                await ws.send(json.dumps({"type": "busy", "text": "real reason"}))
                ack3 = await recv_until(ws, "afk", "error")
                assert ack3.get("afk_message") == "real reason"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_lastemote_offline_target_and_nearby_combat_self(tmp_path, monkeypatch):
    db_path = tmp_path / "lastoff.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "l@ex.com", "Ll", "LastOffA")
        tb, cb = register_char(base, "m@ex.com", "Mm", "LastOffB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "wave", "to": "LastOffB"}))
                await recv_until(wa, "emote", "error")
                await recv_until(wb, "emote", "error")

                # B disconnects — @last must fail cleanly, not crash
                await wb.close()
                await asyncio.sleep(0.2)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "wave", "to": "@last"}))
                err = await recv_until(wa, "error", "emote")
                assert err.get("type") == "error"
                assert "online" in str(err.get("reason") or "").lower()

                # Self in combat does not count as nearby_combat
                await wa.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 9})
                )
                await recv_until(wa, "combat_start", "error")
                await wa.send(json.dumps({"type": "near"}))
                n = await recv_until(wa, "near", "error")
                assert int(n.get("nearby_combat") or 0) == 0, n

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_concurrent_peeks_and_social_storm(tmp_path, monkeypatch):
    """Stress: burst peeks + chat must not desync or rate-limit domain peeks."""
    db_path = tmp_path / "storm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s1@ex.com", "S1", "StormA")
        tb, cb = register_char(base, "s2@ex.com", "S2", "StormB")
        tc, cc = register_char(base, "s3@ex.com", "S3", "StormC")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(
                ws_url
            ) as wb, websockets.connect(ws_url) as wc:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await auth(wc, tc, cc["id"])
                await drain(wa)
                await drain(wb)
                await drain(wc)

                peeks = [
                    "who",
                    "near",
                    "counts",
                    "zone",
                    "status",
                    "ping",
                    "lastemote",
                    "lastwhisper",
                    "version",
                    "played",
                ]
                for p in peeks * 3:
                    await wa.send(json.dumps({"type": p, "t": 1}))

                # Collect a window of responses — no rate_limit on peeks
                got = await drain(wa, 0.8)
                types = [m.get("type") for m in got]
                assert "rate_limit" not in types, types
                assert "error" not in [
                    t
                    for t, m in zip(types, got)
                    if m.get("reason") == "rate_limit"
                ]

                await asyncio.sleep(0.9)
                await wa.send(json.dumps({"type": "wave", "to": "StormB"}))
                em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em
                await recv_until(wb, "emote", "error")

                await asyncio.sleep(0.9)
                await wa.send(json.dumps({"type": "whisper", "to": "StormC", "text": "hi"}))
                wh = await recv_until(wa, "chat", "error")
                assert wh.get("channel") == "whisper", wh
                await recv_until(wc, "chat", "error")

                # Ambiguous prefix among Storm* (validate before rate)
                await wa.send(json.dumps({"type": "whisper", "to": "Storm", "text": "x"}))
                amb = await recv_until(wa, "error", "chat")
                assert amb.get("type") == "error", amb
                assert "ambiguous" in str(amb.get("reason") or "").lower(), amb

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_move_seq_bool_and_shop_combat_matrix(tmp_path, monkeypatch):
    db_path = tmp_path / "matrix.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "mx@ex.com", "Mx", "Matrix")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Bool seq rejected
                await ws.send(json.dumps({"type": "move", "x": 1, "y": 0, "seq": True}))
                m = await recv_until(ws, "move_ok", "error")
                # Should not accept as seq=1
                if m.get("type") == "move_ok":
                    assert m.get("ok") is False or m.get("duplicate") or m.get(
                        "reason"
                    ), m

                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 3})
                )
                await recv_until(ws, "combat_start", "error")

                for t in ("shop", "buy", "sell", "stuck", "wave", "emote"):
                    payload = {"type": t}
                    if t == "buy":
                        payload["item"] = "herb"
                    if t == "sell":
                        payload["item"] = "herb"
                    if t == "emote":
                        payload["emote"] = "wave"
                    await ws.send(json.dumps(payload))
                    err = await recv_until(ws, "error", "shop_list", "inventory_update", "emote", "stuck", "move_ok")
                    if err.get("type") != "error":
                        # shop_list must not arrive in combat
                        assert err.get("type") != "shop_list", err
                    else:
                        assert "combat" in str(err.get("reason") or "").lower() or err.get(
                            "reason"
                        ) in ("in combat", "chat_rate_limit"), err

        asyncio.run(flow())
    finally:
        stop_server(server)
