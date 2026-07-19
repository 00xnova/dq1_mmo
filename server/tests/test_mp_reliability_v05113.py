"""v0.5.113: far directed emote delivery refund; lastwhisper near/far; target_afk."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


class DeadWS(FakeWS):
    async def send_text(self, t):
        raise ConnectionError("gone")


def test_far_directed_emote_fail_refunds_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), DeadWS()
        # far: chebyshev > 10
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 2 not in wm.manager.ids_nearby(1)
        wm.manager.set_afk(1, True, message="lunch")
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "wave", "to": "B"}
        )
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online", out
        # must not remember a failed directed target as lastemote
        lid, _ = wm.manager.last_emote_to(1)
        assert lid is None, lid
        meta = wm.manager.get_meta(1)
        assert meta and meta.get("afk") is True, meta

    asyncio.run(scenario())


def test_far_directed_emote_ok_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "wave", "to": "B"})
        em = next(m for m in out if m.get("type") == "emote")
        assert em.get("to_id") == 2, em
        got = [m for m in b.sent if m.get("type") == "emote"]
        assert got and got[-1].get("to_id") == 2, got
        lid, lname = wm.manager.last_emote_to(1)
        assert lid == 2 and lname == "B"

    asyncio.run(scenario())


def test_near_directed_emote_target_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        wm.manager.set_afk(2, True, message="brb")
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "wave", "to": "B"})
        em = next(m for m in out if m.get("type") == "emote")
        assert em.get("target_afk") is True, em
        assert em.get("target_afk_message") == "brb", em

    asyncio.run(scenario())


def test_lastwhisper_near_far_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(3):
            wm.manager.refund_chat(1)
            wm.manager.refund_chat(2)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "hi"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "lastwhisper"})
        lw = next(m for m in out if m.get("type") == "lastwhisper")
        peer = lw.get("peer") or {}
        assert peer.get("name") == "A", lw
        assert peer.get("nearby") is True, peer
        assert "near" in str(lw.get("message") or "").lower(), lw
        assert "x" not in peer and "y" not in peer

        # move B far then peek still no coords
        await wm.manager.publish_move(2, 18, 2, seq=1)
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "lastwhisper"})
        lw2 = next(m for m in out2 if m.get("type") == "lastwhisper")
        peer2 = lw2.get("peer") or {}
        assert peer2.get("nearby") is False, peer2
        assert "far" in str(lw2.get("message") or "").lower(), lw2

    asyncio.run(scenario())


def test_pending_near_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        pend = next(m for m in out if m.get("type") == "pending")
        assert (pend.get("outgoing") or {}).get("nearby") is True

    asyncio.run(scenario())
