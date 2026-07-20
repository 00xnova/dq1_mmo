"""v0.5.146: shop extract · town gate · combat gate · AFK clear · qty."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import shop
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.shop as sh

    old = (wm.manager, common.manager, sh.manager)
    wm.manager = mgr
    common.manager = mgr
    sh.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.shop as sh

    wm.manager, common.manager, sh.manager = old


def test_shop_module_extracted_unit():
    assert "shop" in shop.SHOP_LIST_TYPES or "shop" in shop.ALL_TYPES
    assert "buy" in shop.BUY_TYPES
    assert "sell" in shop.SELL_TYPES


def test_shop_list_town_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await sh.handle(1, 1, {"type": "shop"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "shop_list" or m.get("items") is not None
            assert m.get("zone") == "town"
            assert "online" in m
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_shop_not_in_town_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        # field-ish far coords
        await mgr.connect(1, a, name="Hero", x=12, y=12, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await sh.handle(1, 1, {"type": "shop"}, outbound)
            # may be field depending on map — if not town, expect error
            from game.world_manager import zone_at

            z = zone_at(12, 12)
            if z != "town":
                assert outbound[0].get("reason") == "shop only in town"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_buy_bad_qty_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await sh.handle(
                1, 1, {"type": "buy", "item": "herb", "quantity": 0}, outbound
            )
            assert outbound[0].get("reason") == "bad quantity"
            outbound2: list[dict] = []
            await sh.handle(
                1, 1, {"type": "buy", "item": "herb", "qty": -3}, outbound2
            )
            assert outbound2[0].get("reason") == "bad quantity"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_buy_item_required_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await sh.handle(1, 1, {"type": "buy"}, outbound)
            assert outbound[0].get("reason") in ("item required", "unknown item")
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_shop_combat_blocked_unit():
    async def scenario():
        import network.handlers.shop as sh
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            # Force in-combat flag if API allows
            with patch.object(combat_engine, "is_in_combat", return_value=True):
                outbound: list[dict] = []
                await sh.handle(1, 1, {"type": "shop"}, outbound)
                assert outbound[0].get("reason") == "in combat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_buy_clears_afk_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")
        old = _bind(mgr)
        try:
            # Mock successful buy without full DB
            async def fake_buy(db, char, item_id, quantity=1):
                return True, None, {
                    "item_id": item_id,
                    "item_name": "Herb",
                    "quantity": quantity,
                    "gold_spent": 10,
                }

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 1,
                    "gold": "100",
                    "current_hp": 10,
                    "max_hp": 10,
                }

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch("network.handlers.shop.get_character", side_effect=fake_get), patch(
                "network.handlers.shop.buy_item", side_effect=fake_buy
            ), patch(
                "network.handlers.shop.db_write"
            ) as dbw, patch(
                "network.handlers.shop._inventory_msg", side_effect=fake_inv
            ):
                # async context manager mock
                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await sh.handle(
                    1, 1, {"type": "buy", "item": "herb", "quantity": 1}, outbound
                )
                m = outbound[0]
                assert m.get("bought") or "Bought" in str(m.get("message") or "")
                assert mgr.get_meta(1).get("afk") is not True
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_sell_success_message_unit():
    async def scenario():
        import network.handlers.shop as sh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_sell(db, char, item_id, quantity=1):
                return True, None, {
                    "item_id": item_id,
                    "item_name": "Herb",
                    "quantity": quantity,
                    "gold_gained": 5,
                }

            async def fake_get(cid):
                return {"id": cid, "level": 1, "gold": "100"}

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch("network.handlers.shop.get_character", side_effect=fake_get), patch(
                "network.handlers.shop.sell_item", side_effect=fake_sell
            ), patch("network.handlers.shop.db_write") as dbw, patch(
                "network.handlers.shop._inventory_msg", side_effect=fake_inv
            ):

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await sh.handle(
                    1, 1, {"type": "sell", "item": "herb", "quantity": 1}, outbound
                )
                m = outbound[0]
                assert m.get("sold")
                assert "Sold" in str(m.get("message") or "")
                assert m.get("zone") == "town"
                assert "online" in m
        finally:
            _restore(old)

    asyncio.run(scenario())
