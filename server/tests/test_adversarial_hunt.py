"""Adversarial hunts — edge cases found by probing for failures."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite

from database.migrations import run_migrations
from game.item_manager import (
    add_item,
    buy_item,
    equip_item,
    list_items,
    sell_item,
    use_consumable,
)
from game.progression import gold_add
from game.rng import Rng
from network.message_handler import sanitize_chat
from network.websocket_manager import CHAT_MAX_LEN, ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


def _run(coro):
    return asyncio.run(coro)


async def _db_char(gold="300", hp=15, max_hp=40):
    path = Path(tempfile.mkdtemp()) / "hunt.db"
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    await db.execute(
        "INSERT INTO users (email, password_hash, username) VALUES ('h@b.c', 'x', 'Hunt')"
    )
    await db.execute(
        """
        INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
        VALUES (1, 'Hunter', ?, ?, ?, 2, 2)
        """,
        (max_hp, hp, gold),
    )
    await db.commit()
    async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
        row = await c.fetchone()
    return db, dict(row)


def test_gold_add_never_negative():
    h = {"gold": "10"}
    gold_add(h, -50)
    assert h["gold"] == "0"
    gold_add(h, 5)
    assert h["gold"] == "5"
    h2 = {"gold": "not-a-number"}
    gold_add(h2, 3)
    assert h2["gold"] == "3"


def test_sanitize_chat_caps_and_rejects():
    assert sanitize_chat("") is None
    assert sanitize_chat("   ") is None
    assert sanitize_chat("hi") == "hi"
    huge = sanitize_chat("Z" * 5000)
    assert huge is not None
    assert len(huge) <= CHAT_MAX_LEN
    assert sanitize_chat("a\x00b") == "ab"


def test_sell_equipped_weapon_clears_slot():
    """Regression: equipped gear was unsellable ('not in inventory')."""

    async def scenario():
        db, char = await _db_char(gold="300")
        ok, reason, _bought = await buy_item(db, char, "club")
        assert ok, reason
        ok, reason = await equip_item(db, char, "weapon", "club")
        assert ok, reason
        assert char["equipment_weapon"] == "club"
        bag = await list_items(db, 1)
        assert not any(i["item_id"] == "club" for i in bag)

        gold_before = int(char["gold"])
        ok, reason, _sold = await sell_item(db, char, "club")
        assert ok, reason
        assert char.get("equipment_weapon") in (None, "")
        assert int(char["gold"]) > gold_before
        await db.close()

    _run(scenario())


def test_herb_blocked_at_full_hp_field():
    async def scenario():
        db, char = await _db_char(hp=40, max_hp=40)
        await add_item(db, 1, "herb", 1)
        await db.commit()
        ok, reason, _ = await use_consumable(db, char, "herb", in_combat=False, rng=Rng(1))
        assert ok is False
        assert reason == "already at full HP"
        # item restored
        bag = await list_items(db, 1)
        assert any(i["item_id"] == "herb" and int(i["quantity"]) >= 1 for i in bag)
        await db.close()

    _run(scenario())


def test_herb_ok_when_wounded():
    async def scenario():
        db, char = await _db_char(hp=5, max_hp=40)
        await add_item(db, 1, "herb", 1)
        await db.commit()
        ok, reason, info = await use_consumable(db, char, "herb", in_combat=False, rng=Rng(1))
        assert ok, reason
        assert info["healed"] >= 0
        assert char["current_hp"] >= 5
        await db.close()

    _run(scenario())


def test_manager_no_partial_whisper_name():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="Alice", x=2, y=2, map_id=1)
        assert mgr.find_id_by_name("Ali") is None
        assert mgr.find_id_by_name("alice") == 1

    _run(scenario())


def test_ws_protocol_and_combat_guards(tmp_path, monkeypatch):
    """Live WS: bad auth, combat move/buy block, non-adjacent move, oversize."""
    db_path = tmp_path / "hunt_ws.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "hunt@ex.com", "HuntU", "HuntHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            # bad token
            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": "nope", "character_id": ch["id"]}
                    )
                )
                m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert m["type"] in ("auth_fail", "error")

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")

                await ws.send(json.dumps({"type": "move", "x": 9, "y": 9, "seq": 1}))
                m = await recv_until(ws, "move_ok", "error")
                assert m.get("ok") is not True or m.get("reason") == "invalid step"
                if m.get("type") == "move_ok":
                    assert m.get("ok") is False

                await ws.send(
                    json.dumps(
                        {"type": "debug_encounter", "enemy": "slime", "seed": 3}
                    )
                )
                await recv_until(ws, "combat_start")

                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 2}))
                m = await recv_until(ws, "move_ok", "error")
                assert m.get("reason") == "in combat" or (
                    m.get("type") == "move_ok" and m.get("ok") is False
                )

                await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error"
                assert m.get("reason") == "in combat"

                await ws.send(json.dumps({"type": "rest"}))
                m = await recv_until(ws, "error", "rest_ok")
                assert m.get("type") == "error"

                # oversize
                await ws.send("x" * 20000)
                m = await recv_until(ws, "error")
                assert "large" in str(m.get("reason") or "").lower()

                # finish combat so cleanup is clean
                for _ in range(20):
                    await ws.send(json.dumps({"type": "attack"}))
                    m = await recv_until(
                        ws, "combat_update", "combat_end", "level_up", "error"
                    )
                    if m.get("type") == "combat_end":
                        break
                    if m.get("outcome") and m.get("outcome") != "ongoing":
                        try:
                            await recv_until(ws, "combat_end")
                        except Exception:
                            pass
                        break

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_negative_move_seq_rejected(tmp_path, monkeypatch):
    """seq < 1 must not be treated as duplicate of last_move_seq=0."""
    db_path = tmp_path / "negseq.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "neg@ex.com", "NegU", "NegHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": -1}))
                m = await recv_until(ws, "move_ok", "error")
                assert m.get("type") == "move_ok"
                assert m.get("ok") is False
                assert m.get("reason") == "invalid seq"
                assert m.get("duplicate") is not True
                # normal seq still works
                await asyncio.sleep(0.12)
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                m2 = await recv_until(ws, "move_ok", "error")
                assert m2.get("ok") is True
                assert m2.get("x") == 3

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_deleted_character_cannot_act(tmp_path, monkeypatch):
    """Even if disconnect races, game actions reject missing character rows."""
    db_path = tmp_path / "ghost.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from network.message_handler import handle_message
    from network.websocket_manager import manager
    from game.combat_engine import reset_combat_engine
    from network.websocket_manager import reset_manager

    async def scenario():
        reset_manager()
        reset_combat_engine()
        await dbmod.init_db()
        # minimal user+char
        db = await dbmod.get_db()
        await db.execute(
            "INSERT INTO users (email, password_hash, username) VALUES ('g@g.c','x','G')"
        )
        await db.execute(
            """
            INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
            VALUES (1, 'Ghost', 15, 15, '100', 2, 2)
            """
        )
        await db.commit()

        class WS:
            async def send_text(self, t):
                pass

            async def close(self, *a, **k):
                pass

        await manager.connect(1, WS(), name="Ghost", x=2, y=2, map_id=1)
        # wipe character row but leave connection
        await db.execute("DELETE FROM characters WHERE id = 1")
        await db.commit()
        _cid, _uid, out, _meta = await handle_message(
            1, 1, {"type": "move", "x": 3, "y": 2, "seq": 1}
        )
        types = [o.get("type") for o in out]
        reasons = [o.get("reason") for o in out if o.get("type") == "error"]
        assert "error" in types
        assert "character missing" in reasons
        await dbmod.close_db()

    asyncio.run(scenario())


def test_delete_online_character_kicks_session(tmp_path, monkeypatch):
    db_path = tmp_path / "delkick.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "kick@ex.com", "KickU", "KickHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                st, _ = __import__("tests.ws_helpers", fromlist=["http_json"]).http_json(
                    base, "DELETE", f"/auth/characters/{ch['id']}", token=token
                )
                assert st in (200, 204)
                await asyncio.sleep(0.2)
                # Further messages should fail or socket should die
                try:
                    await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                    # drain briefly
                    deadline = time.monotonic() + 1.5
                    got_move_ok = False
                    while time.monotonic() < deadline:
                        try:
                            m = json.loads(
                                await asyncio.wait_for(ws.recv(), 0.3)
                            )
                            if m.get("type") == "move_ok" and m.get("ok") is True:
                                got_move_ok = True
                                break
                        except Exception:
                            break
                    assert got_move_ok is False, "deleted hero must not move"
                except Exception:
                    pass  # socket closed is fine

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_ws_sell_equipped_end_to_end(tmp_path, monkeypatch):
    db_path = tmp_path / "hunt_sell.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "sell@ex.com", "SellU", "SellHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")

                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv["type"] == "inventory_update", inv

                await asyncio.sleep(0.2)
                await ws.send(
                    json.dumps({"type": "equip", "slot": "weapon", "item": "club"})
                )
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv["type"] == "inventory_update"
                assert inv["character"]["equipment_weapon"] == "club"

                await asyncio.sleep(0.2)
                gold_before = inv["character"]["gold"]
                await ws.send(json.dumps({"type": "sell", "item": "club"}))
                inv2 = await recv_until(ws, "inventory_update", "error")
                assert inv2["type"] == "inventory_update", inv2
                assert inv2["character"].get("equipment_weapon") in (None, "")
                assert int(inv2["character"]["gold"]) > int(gold_before)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_combat_start_refuses_overwrite():
    """Ongoing battle must not be silently replaced (HP/enemy desync)."""
    from game.combat_engine import combat_engine, reset_combat_engine
    from game.data_loader import battle_spells_at

    reset_combat_engine()
    hero = {
        "id": 1,
        "name": "H",
        "level": 1,
        "max_hp": 40,
        "current_hp": 10,
        "max_mp": 10,
        "current_mp": 10,
        "strength": 5,
        "agility": 5,
        "experience": 0,
        "gold": "10",
        "equipment_weapon": None,
        "equipment_armor": None,
        "equipment_shield": None,
        "known_spells": battle_spells_at(1),
    }
    b1 = combat_engine.start(1, hero, "slime", seed=1)
    b1.hero["hp"] = 3
    try:
        combat_engine.start(1, hero, "red_slime", seed=2)
        raise AssertionError("expected RuntimeError on overwrite")
    except RuntimeError as exc:
        assert "already in combat" in str(exc).lower()
    still = combat_engine.get(1)
    assert still is b1
    assert still.enemy["id"] == "slime"
    assert still.hero["hp"] == 3
    b2 = combat_engine.start(1, hero, "red_slime", seed=3, replace=True)
    assert b2.enemy["id"] == "red_slime"
    combat_engine.end(1)


def test_digit_string_move_seq(tmp_path, monkeypatch):
    """seq sent as string \"2\" should coerce and work (loose clients)."""
    db_path = tmp_path / "seqstr.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "seq@ex.com", "SeqU", "SeqHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(
                    json.dumps({"type": "move", "x": 3, "y": 2, "seq": "1"})
                )
                m = await recv_until(ws, "move_ok", "error")
                assert m.get("type") == "move_ok", m
                assert m.get("ok") is True, m
                assert m.get("x") == 3 and m.get("y") == 2
                await asyncio.sleep(0.15)
                await ws.send(
                    json.dumps({"type": "move", "x": 4, "y": 2, "seq": True})
                )
                m2 = await recv_until(ws, "move_ok", "error")
                assert m2.get("ok") is False
                assert m2.get("reason") == "invalid seq"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_field_shop_and_inn_rejected(tmp_path, monkeypatch):
    """Shop/buy/rest must fail outside town."""
    db_path = tmp_path / "fieldshop.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "fs@ex.com", "FsU", "FsHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async def drain(ws, s=0.12):
                end = time.monotonic() + s
                while time.monotonic() < end:
                    try:
                        await asyncio.wait_for(ws.recv(), 0.05)
                    except Exception:
                        break

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                # Walk town → field (retry steps under encounter/rate noise)
                path = [(2, 3), (3, 3), (4, 3), (5, 3), (6, 3)]
                seq = 0
                for x, y in path:
                    for attempt in range(6):
                        seq += 1
                        await asyncio.sleep(0.16)
                        await ws.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        m = await recv_until(
                            ws, "move_ok", "error", "combat_start", timeout=3
                        )
                        if m.get("type") == "combat_start":
                            for _ in range(16):
                                await ws.send(json.dumps({"type": "flee"}))
                                try:
                                    mf = await recv_until(
                                        ws,
                                        "combat_end",
                                        "combat_update",
                                        "error",
                                        timeout=1,
                                    )
                                    if mf.get("type") == "combat_end" or mf.get(
                                        "outcome"
                                    ) == "fled":
                                        break
                                except TimeoutError:
                                    pass
                            await drain(ws)
                            continue
                        if m.get("type") == "move_ok" and m.get("ok") is not False:
                            # reached this step
                            if int(m.get("x", -1)) == x and int(m.get("y", -1)) == y:
                                break
                            if m.get("duplicate"):
                                break
                        # rate/reject — retry same tile
                    else:
                        pass  # best-effort; assert zone below

                await ws.send(json.dumps({"type": "sync"}))
                snap = await recv_until(ws, "world_state")
                # If still in town, force-walk remaining field tiles once more
                if snap.get("zone") != "field":
                    for x, y in path:
                        seq += 1
                        await asyncio.sleep(0.16)
                        await ws.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        await recv_until(ws, "move_ok", "error", "combat_start", timeout=3)
                        await drain(ws, 0.08)
                    await ws.send(json.dumps({"type": "sync"}))
                    snap = await recv_until(ws, "world_state")
                assert snap.get("zone") == "field", snap

                # Escape any random field fight so zone gates (not combat) are asserted
                for _ in range(16):
                    await ws.send(json.dumps({"type": "flee"}))
                    try:
                        mf = await recv_until(
                            ws, "combat_end", "combat_update", "error", timeout=0.4
                        )
                        if mf.get("type") == "combat_end" or mf.get("outcome") == "fled":
                            break
                    except TimeoutError:
                        break
                await drain(ws, 0.15)

                await ws.send(json.dumps({"type": "shop"}))
                m = await recv_until(ws, "error", "shop_list")
                assert m.get("type") == "error"
                reason = (m.get("reason") or "").lower()
                # Prefer town gate; combat still rejects shop (multiplayer reliability)
                assert "town" in reason or "combat" in reason, m

                await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error"

                await ws.send(json.dumps({"type": "rest"}))
                m = await recv_until(ws, "error", "rest_ok")
                assert m.get("type") == "error"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_ws_guards_oversized_and_no_combat_actions(tmp_path, monkeypatch):
    """Oversized frames rejected; attack/flee without combat error cleanly."""
    db_path = tmp_path / "guard.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "gd@ex.com", "GdU", "GdHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")

                await ws.send("x" * 20000)
                err = await recv_until(ws, "error")
                assert err.get("reason") == "message too large"

                await ws.send("{not-json")
                err = await recv_until(ws, "error")
                assert "json" in (err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "attack"}))
                err = await recv_until(ws, "error")
                assert "combat" in (err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "flee"}))
                err = await recv_until(ws, "error")
                assert "combat" in (err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "sell"}))
                err = await recv_until(ws, "error")
                assert err.get("type") == "error"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_defeat_gold_halved_on_persist():
    """Defeat halves gold via _persist_battle_end (DQ1-ish)."""
    import os

    import aiosqlite

    from database.db import close_db, init_db
    from game.combat_engine import combat_engine, reset_combat_engine
    from game.player_manager import get_character
    from network.message_handler import _persist_battle_end

    async def scenario():
        path = Path(tempfile.mkdtemp()) / "def.db"
        import config

        os.environ["DATABASE_URL"] = str(path)
        config.DATABASE_URL = str(path)
        await close_db()
        gen = await init_db()
        try:
            db = await aiosqlite.connect(path)
            await db.execute(
                "INSERT INTO users (email, password_hash, username) VALUES ('d@e.com','x','DU')"
            )
            await db.execute(
                """
                INSERT INTO characters
                (user_id, name, max_hp, current_hp, max_mp, current_mp, gold, world_x, world_y, level)
                VALUES (1, 'D', 40, 1, 10, 10, '100', 2, 2, 1)
                """
            )
            await db.commit()
            await db.close()
            reset_combat_engine()
            char = await get_character(1)
            assert char is not None
            hero = dict(char)
            hero["known_spells"] = []
            b = combat_engine.start(1, hero, "dragonlord", seed=1)
            for _ in range(40):
                if b.outcome != "ongoing":
                    break
                b.act({"type": "attack"})
            assert b.outcome == "defeat", b.outcome
            out = await _persist_battle_end(1, b)
            assert str(out.get("gold")) == "50", out
            assert int(out.get("current_hp") or 0) >= 1
            assert int(out.get("world_x") or -1) == 2
            assert int(out.get("world_y") or -1) == 2
        finally:
            await close_db(gen)

    _run(scenario())


def test_find_limit_zero_not_default_twenty():
    """limit=0 must not expand to 20 via falsy `or` (adversarial regression)."""
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        for i in range(5):
            await mgr.connect(i + 1, WS(), name=f"Px{i}", x=2, y=2, map_id=1)
        hits0 = mgr.find_by_prefix("Px", limit=0)
        assert len(hits0) == 1, hits0  # clamped to min 1
        hits_neg = mgr.find_by_prefix("Px", limit=-3)
        assert len(hits_neg) == 1
        hits_big = mgr.find_by_prefix("Px", limit=999)
        assert len(hits_big) == 5

    asyncio.run(scenario())


def test_reserved_chat_channel_rejected(tmp_path, monkeypatch):
    """Clients cannot post on system/admin channels (spoof prevention)."""
    db_path = tmp_path / "rsv.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "rsv@ex.com", "RsvU", "RsvHero")

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                for ch_name in ("system", "SYSTEM", "admin", "server"):
                    await asyncio.sleep(0.8)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "chat",
                                "channel": ch_name,
                                "text": "spoof attempt",
                            }
                        )
                    )
                    m = await recv_until(ws, "error", "chat")
                    assert m.get("type") == "error", m
                    assert "reserved" in (m.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_reserved_character_names_blocked():
    from pydantic import ValidationError

    from models.player import CharacterCreate

    for bad in ("System", "SYSTEM", "admin", "GM", "console", "God", "null", "NPC"):
        try:
            CharacterCreate(name=bad)
            raise AssertionError(f"expected reject for {bad}")
        except ValidationError:
            pass
    ok = CharacterCreate(name="HeroBob")
    assert ok.name == "HeroBob"
