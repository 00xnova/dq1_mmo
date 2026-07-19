"""v0.5.112 multiplayer reliability: nearby/far social cards, whisper private delivery."""

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


def test_pending_nearby_far_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        # near: (2,2) and (5,5)
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(1)
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        pend = next(m for m in out if m.get("type") == "pending")
        outg = pend.get("outgoing") or {}
        assert outg.get("nearby") is True, outg
        assert "near" in str(pend.get("message") or "").lower(), pend
        assert "x" not in outg and "y" not in outg, outg

        # far: retarget to C — Chebyshev > VISIBILITY_RANGE (10)
        c = FakeWS()
        await wm.manager.connect(3, c, name="C", x=18, y=2, map_id=0)
        assert 3 not in wm.manager.ids_nearby(1)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "C"})
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "pending"})
        pend2 = next(m for m in out2 if m.get("type") == "pending")
        outg2 = pend2.get("outgoing") or {}
        assert outg2.get("nearby") is False, outg2
        assert "far" in str(pend2.get("message") or "").lower(), pend2
        assert "x" not in outg2 and "y" not in outg2, outg2

    asyncio.run(scenario())


def test_lastinvite_nearby_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=1, y=1, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 1 not in wm.manager.ids_nearby(2)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(2, 20, {"type": "lastinvite"})
        li = next(m for m in out if m.get("type") == "lastinvite")
        peer = li.get("peer") or {}
        assert peer.get("name") == "A", li
        assert peer.get("nearby") is False, peer
        assert "far" in str(li.get("message") or "").lower(), li

    asyncio.run(scenario())


def test_lastemote_nearby_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastemote"})
        le = next(m for m in out if m.get("type") == "lastemote")
        peer = le.get("peer") or {}
        assert peer.get("nearby") is True, peer
        assert "near" in str(le.get("message") or "").lower(), le

    asyncio.run(scenario())


def test_whisper_uses_private_delivery_fail_unit():
    """Dead socket → refund_chat path via private_social_delivery (no hang)."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    class DeadWS(FakeWS):
        async def send_text(self, t):
            raise ConnectionError("gone")

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), DeadWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        wm.manager.set_afk(1, True, message="lunch")
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "B", "text": "hi"}
        )
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online", out
        # AFK restored after failed private delivery
        meta = wm.manager.get_meta(1)
        assert meta and meta.get("afk") is True, meta

    asyncio.run(scenario())


def test_social_peer_card_no_coords_unit():
    from network.handlers._common import peer_status_suffix, social_peer_card
    from network import websocket_manager as wm

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        card = social_peer_card(wm.manager, 2, "B", viewer_id=1)
        assert card and card.get("nearby") is True
        assert "x" not in card and "y" not in card
        assert "near" in peer_status_suffix(card)

    asyncio.run(scenario())


def test_accept_far_coords_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=1, y=1, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 1 not in wm.manager.ids_nearby(2)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        rep = next(m for m in out if m.get("type") == "invite_reply")
        assert rep.get("nearby") is False
        assert "x" not in rep and "y" not in rep
        assert rep.get("zone") in ("town", "field", "dungeon")

    asyncio.run(scenario())
