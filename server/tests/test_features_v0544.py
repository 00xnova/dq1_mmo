"""v0.5.44: whisper invalid targets must not burn chat rate; global self-echo."""

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
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_whisper_self_does_not_block_global(tmp_path, monkeypatch):
    """Invalid self-whisper must not consume chat rate → immediate global still works."""
    db_path = tmp_path / "wself_rate.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "wr@ex.com", "WrU", "WhRate")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                await ws.send(
                    json.dumps(
                        {"type": "whisper", "to": "WhRate", "text": "hello me"}
                    )
                )
                err = await recv_until(ws, "error")
                assert err.get("reason") == "cannot whisper yourself", err

                # Immediate global must succeed (not chat_rate_limit)
                await ws.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "global",
                            "text": "still here",
                        }
                    )
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert m.get("channel") == "global", m
                assert m.get("text") == "still here", m
                assert m.get("name") == "WhRate", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_offline_does_not_block_global(tmp_path, monkeypatch):
    """Offline whisper target must not burn chat rate."""
    db_path = tmp_path / "woff_rate.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "wo@ex.com", "WoU", "WhOff")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                await ws.send(
                    json.dumps(
                        {"type": "whisper", "to": "NobodyOnline", "text": "hi"}
                    )
                )
                err = await recv_until(ws, "error")
                assert err.get("reason") == "player not online", err

                await ws.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "global",
                            "text": "after offline whisper",
                        }
                    )
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert m.get("text") == "after offline whisper", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_global_chat_self_echo(tmp_path, monkeypatch):
    """Sender must receive their own global chat (reliable self-echo)."""
    db_path = tmp_path / "gecho.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "ge@ex.com", "GeU", "EchoHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                await ws.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "global",
                            "text": "echo check",
                        }
                    )
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                assert m.get("channel") == "global", m
                assert m.get("text") == "echo check", m
                assert m.get("name") == "EchoHero", m
                # No double-delivery (broadcast excludes self; outbound once)
                extras = await drain(ws, 0.25)
                dups = [
                    x
                    for x in extras
                    if x.get("type") == "chat" and x.get("text") == "echo check"
                ]
                assert not dups, dups

        asyncio.run(flow())
    finally:
        stop_server(server)
