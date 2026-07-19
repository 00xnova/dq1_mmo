"""v0.5.98 multiplayer reliability: restore AFK after failed private delivery."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail
        self.closed = False

    async def send_text(self, t):
        if self.fail:
            raise RuntimeError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_refund_chat_restores_afk_unit():
    mgr = ConnectionManager()

    async def scenario():
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        assert mgr.set_afk(1, True, message="brb coffee")
        meta = mgr.get_meta(1)
        assert meta and meta.get("afk") is True
        assert meta.get("afk_message") == "brb coffee"
        assert mgr.afk_count() == 1

        ok, _ = mgr.allow_chat(1)
        assert ok
        meta2 = mgr.get_meta(1)
        assert meta2 and meta2.get("afk") is False
        assert mgr.afk_count() == 0

        mgr.refund_chat(1, restore_afk=True, afk_message="brb coffee")
        meta3 = mgr.get_meta(1)
        assert meta3 and meta3.get("afk") is True
        assert meta3.get("afk_message") == "brb coffee"
        assert meta3.get("afk_since") is not None
        assert mgr.afk_count() == 1

        # Rate also refunded
        ok2, _ = mgr.allow_chat(1)
        assert ok2

    asyncio.run(scenario())


def test_whisper_fail_restores_manual_afk_unit():
    """AFK + status message survive a dead-socket whisper race."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS(fail=True)
        await wm.manager.connect(1, a, name="AfkA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="DeadB", x=3, y=2, map_id=0)
        assert wm.manager.set_afk(1, True, message="afk test")
        assert wm.manager.afk_count() == 1

        _cid, _uid, outbound, _cm = await handle_message(
            1, 99, {"type": "whisper", "to": "DeadB", "text": "hello?"}
        )
        errs = [m for m in outbound if m.get("type") == "error"]
        assert errs, outbound
        assert errs[0].get("reason") == "player not online"

        meta = wm.manager.get_meta(1)
        assert meta is not None
        assert meta.get("afk") is True, "manual AFK must be restored after failed whisper"
        assert meta.get("afk_message") == "afk test"
        assert wm.manager.afk_count() == 1

        # Chat rate refunded too
        ok, retry = wm.manager.allow_chat(1)
        assert ok, f"expected refunded chat allowance, retry={retry}"

    asyncio.run(scenario())


def test_invite_fail_restores_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS(fail=True)
        await wm.manager.connect(1, a, name="InvA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="InvB", x=3, y=2, map_id=0)
        assert wm.manager.set_afk(1, True, message="afk invite")

        _cid, _uid, outbound, _cm = await handle_message(
            1, 99, {"type": "invite", "to": "InvB"}
        )
        errs = [m for m in outbound if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online"

        meta = wm.manager.get_meta(1)
        assert meta and meta.get("afk") is True
        assert meta.get("afk_message") == "afk invite"
        assert wm.manager.afk_count() == 1

    asyncio.run(scenario())


def test_share_poke_askwhere_fail_restore_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        for msg_type, target_key in (
            ("share", "ShareB"),
            ("poke", "PokeB"),
            ("askwhere", "AskB"),
        ):
            wm.reset_manager()
            a, b = FakeWS(), FakeWS(fail=True)
            await wm.manager.connect(1, a, name="Src", x=2, y=2, map_id=0)
            await wm.manager.connect(2, b, name=target_key, x=3, y=2, map_id=0)
            assert wm.manager.set_afk(1, True, message=f"afk {msg_type}")

            _cid, _uid, outbound, _cm = await handle_message(
                1, 99, {"type": msg_type, "to": target_key}
            )
            errs = [m for m in outbound if m.get("type") == "error"]
            assert errs, (msg_type, outbound)
            assert errs[0].get("reason") == "player not online", msg_type

            meta = wm.manager.get_meta(1)
            assert meta and meta.get("afk") is True, msg_type
            assert meta.get("afk_message") == f"afk {msg_type}", msg_type
            assert wm.manager.afk_count() == 1, msg_type

    asyncio.run(scenario())


def test_accept_fail_restores_afk_and_keeps_invite_unit():
    """Failed accept must restore AFK and leave invite pending for retry."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a_live, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a_live, name="AccA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="AccB", x=3, y=2, map_id=0)
        _c, _u, out_inv, _ = await handle_message(1, 10, {"type": "invite", "to": "AccB"})
        assert any(m.get("type") == "invite" for m in out_inv), out_inv
        lid, _lname = wm.manager.last_invite_from(2)
        assert lid == 1

        # Replace inviter socket with failing one so accept delivery fails
        await wm.manager.connect(1, FakeWS(fail=True), name="AccA", x=2, y=2, map_id=0)
        assert wm.manager.set_afk(2, True, message="afk accept")

        _c, _u, out_acc, _ = await handle_message(2, 20, {"type": "accept"})
        errs = [m for m in out_acc if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online", out_acc

        meta = wm.manager.get_meta(2)
        assert meta and meta.get("afk") is True
        assert meta.get("afk_message") == "afk accept"
        # Invite still pending so they can retry accept
        lid2, _ = wm.manager.last_invite_from(2)
        assert lid2 == 1

    asyncio.run(scenario())


def test_channel_whisper_fail_restores_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS(fail=True)
        await wm.manager.connect(1, a, name="ChA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="ChB", x=3, y=2, map_id=0)
        assert wm.manager.set_afk(1, True, message="chan afk")

        _cid, _uid, outbound, _cm = await handle_message(
            1,
            99,
            {"type": "chat", "channel": "whisper", "to": "ChB", "text": "psst"},
        )
        errs = [m for m in outbound if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online"

        meta = wm.manager.get_meta(1)
        assert meta and meta.get("afk") is True
        assert meta.get("afk_message") == "chan afk"

    asyncio.run(scenario())
