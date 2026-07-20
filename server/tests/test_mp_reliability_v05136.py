"""v0.5.136: poke handler extract · private delivery · near/far echo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import poke
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_poke_module_extracted_unit():
    assert "poke" in poke.POKE_TYPES
    assert "nudge" in poke.POKE_TYPES
    assert poke.POKE_TYPES == poke.ALL_TYPES


def _bind_managers(mgr):
    """Point module-level manager refs at test ConnectionManager."""
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.poke as poke_mod

    old = (wm.manager, common.manager, poke_mod.manager)
    wm.manager = mgr
    common.manager = mgr
    poke_mod.manager = mgr
    return old


def _restore_managers(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.poke as poke_mod

    wm.manager, common.manager, poke_mod.manager = old


def test_poke_echo_near_far_unit():
    async def scenario():
        import network.handlers.poke as poke_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = _bind_managers(mgr)
        try:
            outbound: list[dict] = []
            res = await poke_mod.handle(
                1, 1, {"type": "poke", "to": "Other"}, outbound
            )
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "poke", m
            assert "You poked" in (m.get("message") or ""), m
            assert m.get("to_id") == 2
            assert m.get("nearby") is True, m
            assert "online" in m
            assert "nearby_count" in m
            assert any(s.get("type") == "poke" for s in b.sent)
        finally:
            _restore_managers(old)

    asyncio.run(scenario())


def test_poke_self_blocked_unit():
    async def scenario():
        import network.handlers.poke as poke_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind_managers(mgr)
        try:
            outbound: list[dict] = []
            await poke_mod.handle(1, 1, {"type": "nudge", "to": "Hero"}, outbound)
            assert outbound[0].get("reason") == "cannot poke yourself"
        finally:
            _restore_managers(old)

    asyncio.run(scenario())


def test_poke_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.poke as poke_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind_managers(mgr)
        try:
            outbound: list[dict] = []
            await poke_mod.handle(1, 1, {"type": "poke", "to": "Other"}, outbound)
            assert any(o.get("reason") == "player not online" for o in outbound), outbound
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore_managers(old)

    asyncio.run(scenario())
