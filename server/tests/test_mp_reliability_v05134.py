"""v0.5.134: find handler extract · plain message · nearby census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import find
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_find_module_extracted_unit():
    assert "find" in find.FIND_TYPES or "search" in find.FIND_TYPES
    assert find.FIND_TYPES == find.ALL_TYPES


def test_find_message_and_census_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.find as find_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Alpha", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="BetaHero", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        find_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await find_mod.handle(
                1, 1, {"type": "find", "q": "Bet"}, outbound
            )
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "find"
            assert m.get("count") >= 1
            assert isinstance(m.get("message"), str)
            assert "Found" in m["message"] or "online" in m["message"]
            assert "nearby_count" in m
            assert "online" in m
            assert m.get("online") == 2
            assert "combat_count" in m
            assert "zones" in m
        finally:
            wm.manager = old
            find_mod.manager = old

    asyncio.run(scenario())


def test_find_empty_query_error_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.find as find_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        find_mod.manager = mgr
        try:
            outbound: list[dict] = []
            await find_mod.handle(1, 1, {"type": "find", "q": ""}, outbound)
            assert outbound[0].get("reason") == "find query required"
        finally:
            wm.manager = old
            find_mod.manager = old

    asyncio.run(scenario())


def test_find_zone_filter_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.find as find_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        find_mod.manager = mgr
        try:
            outbound: list[dict] = []
            await find_mod.handle(
                1, 1, {"type": "find", "q": "zone:town"}, outbound
            )
            m = outbound[0]
            assert m.get("type") == "find"
            assert m.get("zone") == "town"
            assert isinstance(m.get("message"), str)
            assert m.get("count") >= 1  # self in town
        finally:
            wm.manager = old
            find_mod.manager = old

    asyncio.run(scenario())


def test_find_invalid_zone_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.find as find_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        find_mod.manager = mgr
        try:
            outbound: list[dict] = []
            await find_mod.handle(
                1, 1, {"type": "find", "q": "zone:moon"}, outbound
            )
            assert outbound[0].get("reason") == "invalid zone"
        finally:
            wm.manager = old
            find_mod.manager = old

    asyncio.run(scenario())
