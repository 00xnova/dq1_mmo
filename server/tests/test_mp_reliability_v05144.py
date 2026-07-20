"""v0.5.144: whisper extract · private delivery · near/far · soft-grace /r."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import whisper
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
    import network.handlers.whisper as wh

    old = (wm.manager, common.manager, wh.manager)
    wm.manager = mgr
    common.manager = mgr
    wh.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.whisper as wh

    wm.manager, common.manager, wh.manager = old


def test_whisper_module_extracted_unit():
    assert "whisper" in whisper.WHISPER_TYPES or "whisper" in whisper.ALL_TYPES
    assert "r" in whisper.REPLY_TYPES
    assert "tell" in whisper.ALL_TYPES


def test_whisper_echo_near_far_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await wh.handle(
                1, 1, {"type": "whisper", "to": "Guest", "text": "hi"}, outbound
            )
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("channel") == "whisper"
            assert m.get("text") == "hi"
            assert m.get("to") == "Guest"
            assert m.get("nearby") is True
            assert "online" in m and "nearby_count" in m
            peer = next(
                s for s in b.sent if s.get("channel") == "whisper" or s.get("type") == "chat"
            )
            assert peer.get("text") == "hi"
            assert mgr.last_whisper_from(2)[0] == 1
            assert mgr.last_whisper_from(1)[0] == 2
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_whisper_far_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Far", "text": "psst"}, outbound
            )
            m = outbound[0]
            assert m.get("channel") == "whisper"
            assert m.get("nearby") is False
            peer = next(s for s in b.sent if s.get("text") == "psst")
            assert peer.get("channel") == "whisper"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_reply_uses_last_whisper_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Guest", "text": "hi"}, []
            )
            mgr.refund_chat(2)
            outbound: list[dict] = []
            await wh.handle(2, 2, {"type": "r", "text": "yo"}, outbound)
            m = outbound[0]
            assert m.get("channel") == "whisper"
            assert m.get("text") == "yo"
            assert m.get("to") == "Hero"
            peer = next(s for s in a.sent if s.get("text") == "yo")
            assert peer.get("channel") == "whisper"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_whisper_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Guest", "text": "hi"}, outbound
            )
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())


def test_whisper_self_blocked_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Hero", "text": "me"}, outbound
            )
            assert outbound[0].get("reason") == "cannot whisper yourself"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_whisper_empty_blocked_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Guest", "text": ""}, outbound
            )
            assert outbound[0].get("reason") == "empty chat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_whisper_target_afk_tip_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        mgr.set_afk(2, True, message="brb")
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(
                1, 1, {"type": "whisper", "to": "Guest", "text": "hi"}, outbound
            )
            m = outbound[0]
            assert m.get("target_afk") is True
            assert m.get("target_afk_message") == "brb"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_no_one_to_reply_unit():
    async def scenario():
        import network.handlers.whisper as wh

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await wh.handle(1, 1, {"type": "r", "text": "hi"}, outbound)
            assert outbound[0].get("reason") == "no one to reply to"
        finally:
            _restore(old)

    asyncio.run(scenario())
