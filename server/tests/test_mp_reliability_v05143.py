"""v0.5.143: emote extract · AOI · far private delivery · soft-grace memory."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import emote
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.closed = False
        self.fail = fail

    async def send_text(self, t):
        if self.fail:
            raise ConnectionError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.emote as em

    old = (wm.manager, common.manager, em.manager)
    wm.manager = mgr
    common.manager = mgr
    em.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.emote as em

    wm.manager, common.manager, em.manager = old


def test_emote_module_extracted_unit():
    assert "wave" in emote.EMOTE_SHORTCUTS
    assert "emote" in emote.EMOTE_TYPES or "emote" in emote.ALL_TYPES
    assert "bow" in emote.EMOTE_SHORTCUTS


def test_undirected_wave_aoi_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await em.handle(1, 1, {"type": "emote", "emote": "wave"}, outbound)
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "emote"
            assert m.get("emote") == "wave"
            assert "online" in m and "nearby_count" in m
            peer = next(s for s in b.sent if s.get("type") == "emote")
            assert peer.get("emote") == "wave"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_directed_near_emote_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "wave", "to": "Guest"}, outbound)
            m = outbound[0]
            assert m.get("type") == "emote"
            assert m.get("emote") == "wave"
            assert m.get("to") == "Guest"
            assert m.get("nearby") is True
            assert "waves at" in (m.get("message") or "")
            peer = next(s for s in b.sent if s.get("type") == "emote")
            assert peer.get("to") == "Guest"
            assert mgr.last_emote_to(1)[0] == 2
            assert mgr.last_emote_from(2)[0] == 1
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_directed_far_emote_private_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        assert 2 not in mgr.ids_nearby(1)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "wave", "to": "Far"}, outbound)
            m = outbound[0]
            assert m.get("type") == "emote"
            assert m.get("nearby") is False
            peer = next(s for s in b.sent if s.get("type") == "emote")
            assert peer.get("emote") == "wave"
            assert peer.get("to") == "Far"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_far_emote_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "wave", "to": "Far"}, outbound)
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
            # Failed far must not stamp recipient emote_from
            assert mgr.last_emote_from(2)[0] is None
            assert mgr.last_emote_to(1)[0] is None
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())


def test_emote_list_no_rate_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "emotes"}, outbound)
            assert outbound[0].get("type") == "emotes"
            assert "wave" in outbound[0].get("emotes", [])
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_unknown_emote_blocked_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "emote", "emote": "floss"}, outbound)
            assert outbound[0].get("reason") == "unknown emote"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_self_emote_blocked_unit():
    async def scenario():
        import network.handlers.emote as em

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await em.handle(1, 1, {"type": "wave", "to": "Hero"}, outbound)
            assert outbound[0].get("reason") == "cannot emote yourself"
        finally:
            _restore(old)

    asyncio.run(scenario())
