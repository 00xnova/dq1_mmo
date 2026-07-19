"""v0.5.125: ignore_list online near/far + soft reconnect mute hygiene."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_ignore_list_nearby_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        ok, _ = mgr.ignore_player(1, 2)
        assert ok
        lst = mgr.ignore_list(1)
        assert len(lst) == 1
        card = lst[0]
        assert card.get("name") == "B"
        assert card.get("online") is True
        assert card.get("nearby") is True, card
        assert card.get("offline") is False

    asyncio.run(scenario())


def test_ignore_list_far_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 2 not in mgr.ids_nearby(1)
        ok, _ = mgr.ignore_player(1, 2)
        assert ok
        card = mgr.ignore_list(1)[0]
        assert card.get("online") is True
        assert card.get("nearby") is False, card

    asyncio.run(scenario())


def test_ignore_list_offline_soft_grace_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        mgr.ignore_player(1, 2)
        await mgr.disconnect(2, b)
        card = mgr.ignore_list(1)[0]
        assert card.get("name") == "B"
        assert card.get("online") is False
        assert card.get("offline") is True
        assert card.get("nearby") is False

    asyncio.run(scenario())


def test_ignore_soft_reconnect_list_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        mgr.ignore_player(1, 2)
        await mgr.disconnect(1, a)
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        lst = mgr.ignore_list(1)
        assert len(lst) == 1 and lst[0].get("name") == "B"
        assert lst[0].get("online") is True
        assert lst[0].get("nearby") is True

    asyncio.run(scenario())


def test_ignores_message_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        wm.manager.ignore_player(1, 2)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "ignores"})
        msg = next(m for m in out if m.get("type") == "ignore")
        assert msg.get("action") == "list"
        assert msg.get("count") == 1
        assert msg.get("online_count") == 1
        assert "far" in str(msg.get("message") or "").lower()
        assert "B" in str(msg.get("message") or "")

    asyncio.run(scenario())
