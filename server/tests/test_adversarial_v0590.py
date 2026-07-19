"""v0.5.90 adversarial: emote edges, ignore, combat gate, rate hygiene."""

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


def test_wave_self_offline_ignore_no_rate(tmp_path, monkeypatch):
    db_path = tmp_path / "adv90.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "x@ex.com", "Xx", "AdvA")
        tb, cb = register_char(base, "y@ex.com", "Yy", "AdvB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Self
                await wa.send(json.dumps({"type": "wave", "to": "AdvA"}))
                e1 = await recv_until(wa, "error", "emote")
                assert e1.get("type") == "error"
                assert "yourself" in str(e1.get("reason") or "").lower()
                assert e1.get("reason") != "chat_rate_limit"

                # Offline
                await wa.send(json.dumps({"type": "bow", "to": "NobodyHere"}))
                e2 = await recv_until(wa, "error", "emote")
                assert "online" in str(e2.get("reason") or "").lower()
                assert e2.get("reason") != "chat_rate_limit"

                # Ignore either way (response type is always "ignore")
                await wb.send(json.dumps({"type": "ignore", "name": "AdvA"}))
                await recv_until(wb, "ignore", "error")
                await wa.send(json.dumps({"type": "wave", "to": "AdvB"}))
                e3 = await recv_until(wa, "error", "emote")
                assert e3.get("type") == "error"
                assert "unavailable" in str(e3.get("reason") or "").lower()
                assert e3.get("reason") != "chat_rate_limit"

                await wb.send(json.dumps({"type": "unignore", "name": "AdvA"}))
                await recv_until(wb, "ignore", "error")

                await wa.send(json.dumps({"type": "ignore", "name": "AdvB"}))
                await recv_until(wa, "ignore", "error")
                await wa.send(json.dumps({"type": "wave", "to": "AdvB"}))
                e4 = await recv_until(wa, "error", "emote")
                assert "ignore" in str(e4.get("reason") or "").lower()
                assert e4.get("reason") != "chat_rate_limit"

                # Spam peeks then successful wave must not hit global rate_limit
                for _ in range(12):
                    await wa.send(json.dumps({"type": "who"}))
                    await recv_until(wa, "who", "error")
                await wa.send(json.dumps({"type": "unignore", "name": "AdvB"}))
                await recv_until(wa, "ignore", "error")
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "wave", "to": "AdvB"}))
                ok = await recv_until(wa, "emote", "error")
                assert ok.get("type") == "emote", ok

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_wave_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "adv90c.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "Fighter")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
                await wa.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 2})
                )
                await recv_until(wa, "combat_start", "error")

                await wa.send(json.dumps({"type": "wave"}))
                err = await recv_until(wa, "error", "emote")
                assert err.get("type") == "error"
                assert "combat" in str(err.get("reason") or "").lower()

                # Catalog still allowed mid-combat
                await wa.send(json.dumps({"type": "emotes"}))
                cat = await recv_until(wa, "emotes", "error")
                assert cat.get("type") == "emotes"
                assert "wave" in (cat.get("emotes") or [])

        asyncio.run(flow())
    finally:
        stop_server(server)
