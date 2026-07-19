"""HUD / ops info peeks: keys · help · motd (extracted).

Rate-exempt multiplayer helpers. Share online census fields with meta peeks so
clients stay oriented under soft reconnect and peek spam.
"""

from __future__ import annotations

import time
from typing import Any

from config import MOTD, PROCESS_STARTED_AT, VERSION as _VER
from network.handlers._common import _format_uptime
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

KEYS_TYPES = frozenset({"keys", "controls", "keybinds", "keymap"})
HELP_TYPES = frozenset({ClientMessageType.HELP, "help", "commands"})
MOTD_TYPES = frozenset({"motd", "message_of_the_day", "rules"})

ALL_TYPES = KEYS_TYPES | HELP_TYPES | MOTD_TYPES

_HELP_COMMANDS: list[dict[str, str]] = [
    {"cmd": "move", "hint": "WASD / arrow keys"},
    {"cmd": "chat", "hint": "T global · Y nearby · /z zone"},
    {
        "cmd": "whisper",
        "hint": "/w Name · /w @last · /w @emote · /w @share · /w @from · /w @pending",
    },
    {"cmd": "say", "hint": "/say · /s message — nearby chat"},
    {
        "cmd": "find",
        "hint": "/find Name · zone:town · afk:yes · combat:yes · idle:yes",
    },
    {"cmd": "status", "hint": "F or /status · /me · /whoami · /stats"},
    {"cmd": "look", "hint": "L · /look · /look @pending · /whereis @last"},
    {"cmd": "who", "hint": "O · /who · /players — online + zone counts"},
    {"cmd": "near", "hint": "/near · /here — nearby heroes only"},
    {"cmd": "zone", "hint": "/zone · /where · /mapinfo · /coords"},
    {"cmd": "counts", "hint": "/counts · /census — online + you + zones"},
    {
        "cmd": "emote",
        "hint": "E · /wave · /wave @last · /wave @emote · /wave @emotedby",
    },
    {"cmd": "lastemote", "hint": "/lastemote — last emote to + from (near/far)"},
    {"cmd": "lastshare", "hint": "/lastshare — last share to + from (near/far)"},
    {"cmd": "busy", "hint": "/busy [reason] — AFK alias"},
    {
        "cmd": "invite",
        "hint": "/invite Name · /meet @last · /invite @share · /invite @pending",
    },
    {"cmd": "cancel", "hint": "/cancel · /uninvite — cancel your last invite"},
    {"cmd": "accept", "hint": "/accept · /coming — reply to last invite"},
    {"cmd": "decline", "hint": "/decline · /later — decline last invite"},
    {"cmd": "lastinvite", "hint": "/lastinvite — who invited you last"},
    {"cmd": "pending", "hint": "/pending · /invites — pending meetup in + out"},
    {
        "cmd": "share",
        "hint": "/share Name · /share @pending · /share @last — share zone + coords",
    },
    {"cmd": "poke", "hint": "/poke Name · /nudge @last · /poke @pending"},
    {"cmd": "askwhere", "hint": "/askwhere Name · /locate @pending"},
    {
        "cmd": "thank",
        "hint": "/thank Name · /ty @last · /ty @share · /ty @from · /ty @pending",
    },
    {"cmd": "fighting", "hint": "/fighting · /combats — nearby heroes in combat"},
    {"cmd": "yell", "hint": "/yell · /shout · /z — zone chat"},
    {"cmd": "stuck", "hint": "/stuck · /unstuck · /home — return to town"},
    {"cmd": "use", "hint": "/use herb — use consumable from bag"},
    {"cmd": "buy", "hint": "/buy copper sword [qty] — names or ids OK"},
    {"cmd": "sell", "hint": "/sell herb [qty] — names or ids OK"},
    {"cmd": "equip", "hint": "/equip copper sword — name/id, slot auto"},
    {"cmd": "rest", "hint": "R — inn quote, R again to stay (town)"},
    {"cmd": "inventory", "hint": "I · /bag · /inv — bag (12 stacks · max 8)"},
    {"cmd": "gold", "hint": "/gold · /money — wallet peek"},
    {"cmd": "hp", "hint": "/hp · /vitals — HP/MP peek"},
    {"cmd": "xp", "hint": "/xp · /level — level + XP to next"},
    {"cmd": "buffs", "hint": "/buffs · /effects — repel · radiant · AFK"},
    {"cmd": "played", "hint": "/played · /session — this connection length"},
    {"cmd": "keys", "hint": "/keys · /controls — keybind summary"},
    {"cmd": "spells", "hint": "/spells · /magic — known battle + field"},
    {"cmd": "unequip", "hint": "/unequip weapon|armor|shield|helmet"},
    {"cmd": "discard", "hint": "/discard herb [qty] · D in bag — free a slot"},
    {"cmd": "cast", "hint": "/cast heal · /repel · /return · H/M keys"},
    {"cmd": "combat", "hint": "1–9 menu · A attack · F flee · H herb"},
    {
        "cmd": "ignore",
        "hint": "/ignore · /ignores near/far/zone · /unignore @last",
    },
    {"cmd": "reply", "hint": "/r message — reply last whisper (server-tracked)"},
    {"cmd": "lastwhisper", "hint": "/last · /lastwhisper — who /r targets"},
    {"cmd": "social", "hint": "/social · /peers — whisper · invite · emote peers"},
    {
        "cmd": "find",
        "hint": "/find Name · /find @pending · /find @share · zone:town",
    },
    {"cmd": "roll", "hint": "/roll · /dice — 1d100 nearby"},
    {"cmd": "version", "hint": "/version · /server · /info — server version"},
    {"cmd": "time", "hint": "/time · /uptime — server clock + uptime"},
    {"cmd": "motd", "hint": "/motd — message of the day"},
    {"cmd": "afk", "hint": "/afk [reason] · /away · /back — AFK badge + status"},
    {"cmd": "block", "hint": "/block · /unblock — same as ignore"},
    {"cmd": "quit", "hint": "/quit · /logout — leave the world"},
]


def _census() -> dict[str, Any]:
    return {
        "online": len(manager.online_ids()),
        "afk_count": manager.afk_count(),
        "combat_count": manager.combat_count(),
        "zones": manager.zone_counts(),
        "version": _VER,
        "uptime": max(0, int(time.time() - PROCESS_STARTED_AT)),
    }


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch keys/help/motd. Returns None if not a hud info peek."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is not None:
        manager.touch(character_id)

    census = _census()
    online_n = census["online"]
    up_hms = _format_uptime(int(census["uptime"]))

    if msg_type in KEYS_TYPES:
        body: dict[str, Any] = {
            "type": "controls",
            "overworld": [
                "WASD move",
                "T global chat · Y nearby",
                "E emote · F status · L look · O who",
                "I bag · R inn · H/M field magic · K spells",
                "Esc disconnect",
            ],
            "combat": ["↑↓ menu · Enter", "1–9 jump", "A attack · F flee · H herb"],
            "inventory": [
                "Enter use/equip",
                "S sell · D discard · U unequip · Tab shop",
            ],
            "slash": [
                "/w /r /last · /say /g /z /yell · /find · /who /near /zone",
                "/hp /xp /gold /spells /bag /buffs /played · /stuck /afk /quit",
                "/ignore /ignores · /version /time /motd",
            ],
            "online": online_n,
            "afk_count": census["afk_count"],
            "combat_count": census["combat_count"],
            "zones": census["zones"],
            "version": _VER,
            "message": (
                f"WASD · T/Y chat · E emote · F status · L look · "
                f"R inn · I bag · H/M magic · O who · /stuck · Esc"
                f" · {online_n} online"
            ),
        }
        if character_id is not None:
            body["nearby_count"] = len(manager.ids_nearby(character_id))
            body["session_id"] = manager.session_id(character_id)
        outbound.append(body)
        return character_id, user_id, outbound, None

    if msg_type in HELP_TYPES:
        body = {
            "type": ServerMessageType.HELP,
            "commands": list(_HELP_COMMANDS),
            "channels": ["global", "nearby", "zone", "whisper"],
            "version": _VER,
            "online": online_n,
            "afk_count": census["afk_count"],
            "combat_count": census["combat_count"],
            "zones": census["zones"],
            "uptime": census["uptime"],
            "message": (
                f"Help · {_VER} · {online_n} online · "
                f"{census['afk_count']} AFK · up {up_hms}"
            ),
        }
        if character_id is not None:
            body["nearby_count"] = len(manager.ids_nearby(character_id))
            body["session_id"] = manager.session_id(character_id)
        outbound.append(body)
        return character_id, user_id, outbound, None

    if msg_type in MOTD_TYPES:
        text = str(MOTD)[:500]
        body = {
            "type": "motd",
            "text": text,
            "version": _VER,
            "online": online_n,
            "afk_count": census["afk_count"],
            "combat_count": census["combat_count"],
            "zones": census["zones"],
            "uptime": census["uptime"],
            "message": f"MOTD · {online_n} online · up {up_hms}",
        }
        if character_id is not None:
            body["nearby_count"] = len(manager.ids_nearby(character_id))
            body["session_id"] = manager.session_id(character_id)
        outbound.append(body)
        return character_id, user_id, outbound, None

    return None
