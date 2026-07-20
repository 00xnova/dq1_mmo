"""v0.5.147: inventory extract · combat gate · AFK clear · qty · census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import inventory
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
    import network.handlers.inventory as inv

    old = (wm.manager, common.manager, inv.manager)
    wm.manager = mgr
    common.manager = mgr
    inv.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.inventory as inv

    wm.manager, common.manager, inv.manager = old


def test_inventory_module_extracted_unit():
    assert "bag" in inventory.BAG_TYPES or "inventory" in inventory.ALL_TYPES
    assert "equip" in inventory.EQUIP_TYPES
    assert "discard" in inventory.DISCARD_TYPES
    assert "unequip" in inventory.UNEQUIP_TYPES


def test_bag_peek_census_unit():
    async def scenario():
        import network.handlers.inventory as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch(
                "network.handlers.inventory._inventory_msg", side_effect=fake_inv
            ):
                outbound: list[dict] = []
                await inv.handle(1, 1, {"type": "bag"}, outbound)
                m = outbound[0]
                assert m.get("type") == "inventory_update"
                assert "online" in m and "nearby_count" in m
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_equip_combat_blocked_unit():
    async def scenario():
        import network.handlers.inventory as inv
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=True):
                outbound: list[dict] = []
                await inv.handle(
                    1, 1, {"type": "equip", "item": "club"}, outbound
                )
                assert outbound[0].get("reason") == "in combat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_discard_bad_qty_unit():
    async def scenario():
        import network.handlers.inventory as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(
                1,
                1,
                {"type": "discard", "item": "herb", "quantity": 0},
                outbound,
            )
            assert outbound[0].get("reason") == "bad quantity"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_equip_clears_afk_unit():
    async def scenario():
        import network.handlers.inventory as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {"id": cid, "level": 1}

            async def fake_equip(db, char, slot, item_id):
                return True, None

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch(
                "network.handlers.inventory.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.inventory.equip_item", side_effect=fake_equip
            ), patch(
                "network.handlers.inventory.get_equipment_def",
                return_value={"slot": "armor"},
            ), patch("network.handlers.inventory.db_write") as dbw, patch(
                "network.handlers.inventory._inventory_msg", side_effect=fake_inv
            ):

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await inv.handle(
                    1, 1, {"type": "equip", "item": "clothes"}, outbound
                )
                m = outbound[0]
                assert m.get("equipped") or "Equipped" in str(m.get("message") or "")
                assert mgr.get_meta(1).get("afk") is not True
                assert "online" in m
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_discard_clears_afk_unit():
    async def scenario():
        import network.handlers.inventory as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="brb")
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {"id": cid}

            async def fake_discard(db, char, item_id, qty):
                return True, None, {
                    "item_id": item_id,
                    "item_name": "Herb",
                    "quantity": qty,
                }

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch(
                "network.handlers.inventory.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.inventory.discard_item", side_effect=fake_discard
            ), patch("network.handlers.inventory.db_write") as dbw, patch(
                "network.handlers.inventory._inventory_msg", side_effect=fake_inv
            ):

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await inv.handle(
                    1,
                    1,
                    {"type": "discard", "item": "herb", "quantity": 1},
                    outbound,
                )
                m = outbound[0]
                assert m.get("discarded")
                assert "Discarded" in str(m.get("message") or "")
                assert mgr.get_meta(1).get("afk") is not True
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_item_required_unit():
    async def scenario():
        import network.handlers.inventory as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "equip"}, outbound)
            assert outbound[0].get("reason") in ("item required", "unknown item")
            out2: list[dict] = []
            await inv.handle(1, 1, {"type": "discard"}, out2)
            assert out2[0].get("reason") in ("item required", "unknown item")
        finally:
            _restore(old)

    asyncio.run(scenario())
