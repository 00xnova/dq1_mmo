"""v0.5.131: hud_info extract · keys/help/motd multiplayer census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import hud_info
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_hud_info_module_extracted_unit():
    assert "keys" in hud_info.KEYS_TYPES
    assert "help" in hud_info.HELP_TYPES or "commands" in hud_info.HELP_TYPES
    assert "motd" in hud_info.MOTD_TYPES
    assert hud_info.KEYS_TYPES <= hud_info.ALL_TYPES
    assert len(hud_info._HELP_COMMANDS) > 20


def test_keys_census_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.hud_info as hi

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        hi.manager = mgr
        try:
            outbound: list[dict] = []
            res = await hi.handle(1, 1, {"type": "keys"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "controls"
            assert m.get("online") == 2
            assert "afk_count" in m
            assert "combat_count" in m
            assert "zones" in m
            assert isinstance(m.get("message"), str)
            assert "online" in m["message"]
            assert m.get("nearby_count") is not None
        finally:
            wm.manager = old
            hi.manager = old

    asyncio.run(scenario())


def test_help_census_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.hud_info as hi

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        hi.manager = mgr
        try:
            outbound: list[dict] = []
            res = await hi.handle(1, 1, {"type": "help"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "help"
            cmds = m.get("commands") or []
            assert any(c.get("cmd") == "ignore" for c in cmds)
            assert "combat_count" in m
            assert "afk_count" in m
            assert isinstance(m.get("message"), str)
            assert "Help" in m["message"] or "online" in m["message"]
            # mute list help mentions near/far/zone
            ignore_hint = next(
                (c.get("hint") or "" for c in cmds if c.get("cmd") == "ignore"),
                "",
            )
            assert "near" in ignore_hint or "ignores" in ignore_hint
        finally:
            wm.manager = old
            hi.manager = old

    asyncio.run(scenario())


def test_motd_census_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.hud_info as hi

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        hi.manager = mgr
        try:
            outbound: list[dict] = []
            res = await hi.handle(1, 1, {"type": "motd"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "motd"
            assert "text" in m
            assert "combat_count" in m
            assert "afk_count" in m
            assert "zones" in m
            assert isinstance(m.get("message"), str)
            assert "online" in m["message"].lower() or "MOTD" in m["message"]
        finally:
            wm.manager = old
            hi.manager = old

    asyncio.run(scenario())
