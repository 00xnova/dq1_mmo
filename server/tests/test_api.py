"""Integration tests against running app (in-process)."""

import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from main import app

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def _start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=0.2)
            return server
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("server did not start")


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_full_flow(tmp_path, monkeypatch):
    # isolate DB
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    # re-import config is already loaded — set on config module
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    # reset db singleton
    asyncio.run(dbmod.close_db())

    server = _start_server()
    try:
        st, health = req("GET", "/health")
        assert st == 200 and health["status"] == "ok"

        st, reg = req(
            "POST",
            "/auth/register",
            {"email": "t@ex.com", "password": "password", "username": "Tester"},
        )
        assert st == 201, reg
        token = reg["access_token"]

        st, bad = req("POST", "/auth/login", {"email": "t@ex.com", "password": "nope"})
        assert st == 401

        st, ch = req("POST", "/auth/characters", {"name": "HeroT"}, token=token)
        assert st == 201
        assert ch["gold"] == str(config.STARTING_GOLD)

        st, chars = req("GET", "/auth/characters", token=token)
        assert st == 200 and len(chars) == 1

        async def ws_flow():
            import websockets

            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                m1 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                m2 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert m1["type"] == "auth_ok"
                assert m2["type"] == "world_state"
                assert "bonuses" in m1["character"]

                # stay in town, buy club
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                inv = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if inv["type"] == "error":
                    inv = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert inv["type"] == "inventory_update"
                assert any(i["item_id"] == "club" for i in inv["items"])

                await ws.send(json.dumps({"type": "equip", "slot": "weapon", "item": "club"}))
                inv2 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if inv2["type"] == "error":
                    inv2 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert inv2["character"]["equipment_weapon"] == "club"
                assert inv2["character"]["bonuses"]["attack_power"] == 8

                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 11})
                )
                start = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert start["type"] == "combat_start"
                # drain update
                await asyncio.wait_for(ws.recv(), 3)

                for _ in range(15):
                    await ws.send(json.dumps({"type": "attack"}))
                    m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    while m["type"] == "level_up":
                        m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    if m["type"] == "combat_end":
                        assert m["result"] == "victory"
                        assert m["character"]["equipment_weapon"] == "club"
                        return
                    if m.get("outcome") == "victory":
                        m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                        assert m["type"] == "combat_end"
                        return
                raise AssertionError("battle did not end")

        asyncio.run(ws_flow())
    finally:
        server.should_exit = True
        time.sleep(0.2)
