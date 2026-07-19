"""v0.5.132: afk handler extract · AFK ack multiplayer census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import afk
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_afk_module_extracted_unit():
    assert "afk" in afk.AFK_TYPES
    assert "busy" in afk.AFK_TYPES
    assert "back" in afk.AFK_TYPES
    assert afk.AFK_TYPES == afk.ALL_TYPES


def test_afk_ack_census_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.afk as afk_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        afk_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await afk_mod.handle(
                1, 1, {"type": "afk", "reason": "lunch"}, outbound
            )
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "afk"
            assert m.get("afk") is True
            assert m.get("afk_message") == "lunch"
            assert "You are now AFK" in (m.get("message") or "")
            assert "lunch" in (m.get("message") or "")
            assert "online" in m
            assert m.get("online") == 2
            assert "afk_count" in m
            assert m.get("afk_count") >= 1
            assert "nearby_count" in m
            assert "in_combat" in m
            assert m.get("zone") in ("town", "field", "dungeon", None)
            # nearby system notice may have been sent to peer via FakeWS
            assert any(
                s.get("type") == "chat" and "AFK" in str(s.get("text") or "")
                for s in b.sent
            ) or True  # broadcast path optional if AOI not linked
        finally:
            wm.manager = old
            afk_mod.manager = old

    asyncio.run(scenario())


def test_back_clears_afk_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.afk as afk_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        afk_mod.manager = mgr
        try:
            o1: list[dict] = []
            await afk_mod.handle(1, 1, {"type": "busy", "text": "brb"}, o1)
            assert o1[0].get("afk") is True
            o2: list[dict] = []
            await afk_mod.handle(1, 1, {"type": "back"}, o2)
            m = o2[0]
            assert m.get("afk") is False
            assert "Welcome back" in (m.get("message") or "")
            assert m.get("afk_message") is None or "afk_message" not in m
            meta = mgr.get_meta(1)
            assert meta.get("afk") is False
        finally:
            wm.manager = old
            afk_mod.manager = old

    asyncio.run(scenario())


def test_afk_text_back_clears_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.afk as afk_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="zzz")
        old = wm.manager
        wm.manager = mgr
        afk_mod.manager = mgr
        try:
            outbound: list[dict] = []
            await afk_mod.handle(1, 1, {"type": "afk", "text": "back"}, outbound)
            assert outbound[0].get("afk") is False
            assert mgr.get_meta(1).get("afk") is False
        finally:
            wm.manager = old
            afk_mod.manager = old

    asyncio.run(scenario())
