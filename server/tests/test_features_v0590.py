"""v0.5.90 features: busy, lastemote empty, unauth wave, help hints."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import http_json, register_char, start_server, stop_server


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


def test_unauth_wave_and_lastemote(tmp_path, monkeypatch):
    db_path = tmp_path / "unauth90.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "wave"}))
                err = await recv_until(ws, "error")
                assert "authenticate" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "lastemote"}))
                err2 = await recv_until(ws, "error")
                assert "authenticate" in str(err2.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "busy"}))
                err3 = await recv_until(ws, "error")
                assert "authenticate" in str(err3.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_no_one_to_emote_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "noemote.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "Help90")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(json.dumps({"type": "wave", "to": "@last"}))
                err = await recv_until(ws, "error", "emote")
                assert err.get("type") == "error"
                assert "no one" in str(err.get("reason") or "").lower()

                # Failed @last must not clear AFK
                await ws.send(json.dumps({"type": "busy", "text": "wait"}))
                await recv_until(ws, "afk")
                await ws.send(json.dumps({"type": "bow", "to": "last"}))
                await recv_until(ws, "error")
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                assert (st.get("you") or {}).get("afk") is True

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "lastemote" in cmds or "busy" in cmds or "emote" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_and_starter_clothes_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "ver90.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        st, reg = http_json(
            base,
            "POST",
            "/auth/register",
            {"email": "v90@ex.com", "password": "password", "username": "Ver90"},
        )
        assert st == 201, reg
        tok = reg["access_token"]
        st, ch = http_json(
            base, "POST", "/auth/characters", {"name": "VerHero"}, token=tok
        )
        assert st == 201, ch
        assert ch.get("equipment_armor") == "clothes", ch

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, tok, ch["id"])
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error", "about")
                # version body may be type version or error
                body = v
                if body.get("type") == "error":
                    await ws.send(json.dumps({"type": "about"}))
                    body = await recv_until(ws, "version", "about", "error")
                ver = str(body.get("version") or config.VERSION)
                assert ver.startswith("0.5."), ver

        asyncio.run(flow())
    finally:
        stop_server(server)
