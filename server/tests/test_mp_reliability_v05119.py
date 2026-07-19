"""v0.5.119: bidirectional emote memory · @emote / @emotedby aliases."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.message_handler import _social_alias


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


def test_emote_alias_tokens_unit():
    assert _social_alias("@emote") == "emote"
    assert _social_alias("@lastemote") == "emote"
    assert _social_alias("@emotedby") == "emote_from"
    assert _social_alias("@wavedby") == "emote_from"
    assert _social_alias("@waved") == "emote_from"
    assert _social_alias("emote") is None  # bare name ok


def test_directed_emote_from_and_lastemote_unit():
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

        # A lastemote: to B
        _c, _u, out_a, _ = await handle_message(1, 10, {"type": "lastemote"})
        le_a = next(m for m in out_a if m.get("type") == "lastemote")
        assert le_a.get("has_to") is True
        assert (le_a.get("to") or {}).get("name") == "B"
        assert "to B" in str(le_a.get("message") or "")

        # B lastemote: from A
        _c, _u, out_b, _ = await handle_message(2, 20, {"type": "lastemote"})
        le_b = next(m for m in out_b if m.get("type") == "lastemote")
        assert le_b.get("has_from") is True
        assert (le_b.get("from") or {}).get("name") == "A"
        assert "from A" in str(le_b.get("message") or "")

        # B can whisper @emotedby → A
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out_w, _ = await handle_message(
            2, 20, {"type": "whisper", "to": "@emotedby", "text": "hi"}
        )
        assert any(m.get("channel") == "whisper" for m in out_w), out_w
        assert any(m.get("channel") == "whisper" for m in a.sent)

        # A can re-wave @emote → B
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out_e, _ = await handle_message(
            1, 10, {"type": "wave", "to": "@emote"}
        )
        assert any(m.get("type") == "emote" for m in out_e), out_e

    asyncio.run(scenario())


def test_emote_from_soft_grace_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        # far wave uses private delivery
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        await wm.manager.disconnect(2, b)
        b2 = FakeWS()
        await wm.manager.connect(2, b2, name="B", x=5, y=5, map_id=0)
        lid, lname = wm.manager.last_emote_from(2)
        assert lid == 1 and lname == "A", (lid, lname)

    asyncio.run(scenario())


def test_social_emote_from_unit():
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
        _c, _u, out, _ = await handle_message(2, 20, {"type": "social"})
        soc = next(m for m in out if m.get("type") == "social")
        ef = soc.get("emote_from") or {}
        assert ef.get("name") == "A", soc
        assert "emote from" in str(soc.get("message") or "").lower()

    asyncio.run(scenario())


def test_empty_emotedby_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "thank", "to": "@emotedby"}
        )
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no one emoted at you", out

    asyncio.run(scenario())


def test_share_alias_regression_unit():
    from network.message_handler import _social_alias

    assert _social_alias("@share") == "share"
    assert _social_alias("@from") == "share_from"


def test_sync_includes_emote_peers_unit():
    """sync world_state exposes last_emote_to / last_emote_from after wave."""
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
        _c, _u, out, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out if m.get("type") == "world_state")
        assert (ws.get("last_emote_to") or {}).get("name") == "B", ws
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "sync"})
        ws2 = next(m for m in out2 if m.get("type") == "world_state")
        assert (ws2.get("last_emote_from") or {}).get("name") == "A", ws2

    asyncio.run(scenario())


def test_far_emote_fail_no_from_note_unit():
    """Failed far directed emote must not stamp recipient emote_from memory."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), DeadWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 2 not in wm.manager.ids_nearby(1)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        # recipient may be gone after dead send; if still present, no from note
        lid, _ = wm.manager.last_emote_from(2)
        assert lid is None
        to_id, _ = wm.manager.last_emote_to(1)
        assert to_id is None

    asyncio.run(scenario())
