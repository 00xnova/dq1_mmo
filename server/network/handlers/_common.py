"""Shared helpers for WebSocket message handling.

Imported by ``network.message_handler`` and re-exported so existing
``from network.message_handler import …`` test imports keep working.
"""

from __future__ import annotations

import math
import re
from typing import Any

from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at
from game.item_manager import (
    character_public,
    equipment_bonuses,
    list_items,
    resolve_item_id,
)
from game.player_manager import apply_character_patch, get_character
from game.world_manager import SPAWN_X, SPAWN_Y
from network.protocol import ServerMessageType, msg
from network.websocket_manager import CHAT_MAX_LEN, manager

# Strip control chars except space/tab; collapse whitespace for storage display
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Social target aliases for multiplayer private commands
_LAST_TOKENS = frozenset({"@last", "last", "!"})
# Require @ prefix so a hero named "pending" / "meetup" stays addressable by name
_PENDING_TOKENS = frozenset({"@pending", "@invite", "@meetup"})


def _format_uptime(seconds: int) -> str:
    """Human-readable uptime for /time (e.g. 1h 02m 03s)."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _afk_snap(meta: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Capture manual AFK + status before allow_chat (which clears AFK).

    Used so failed private delivery can refund_chat(..., restore_afk=True)
    and keep census / badges honest after a multiplayer send race.
    """
    if not meta:
        return False, None
    was = bool(meta.get("afk"))
    msg_txt: str | None = None
    if was:
        am = meta.get("afk_message")
        if isinstance(am, str) and am.strip():
            msg_txt = am.strip()[:48]
    return was, msg_txt


def _social_alias(target_name: Any, data: dict[str, Any] | None = None) -> str | None:
    """Return 'last' | 'pending' | None from to/name token or flags.

    @last  — last whisper / emote / invite peer (command-specific chain)
    @pending / @invite — pending meetup peer (incoming then outgoing)
    """
    if data:
        if data.get("pending") or data.get("invite_peer"):
            return "pending"
        if data.get("reply"):
            return "last"
    if not isinstance(target_name, str):
        return None
    t = target_name.strip().lower()
    if t in _LAST_TOKENS:
        return "last"
    if t in _PENDING_TOKENS:
        return "pending"
    return None


def _resolve_social_peer(
    manager_obj: Any,
    character_id: int,
    mode: str,
    *,
    chain: tuple[str, ...] = ("whisper", "emote", "invite_from", "invite_to"),
) -> tuple[int | None, str | None, str | None]:
    """Resolve @last / @pending peer. Returns (id, name, empty_reason)."""
    if mode == "pending":
        lid, lname = manager_obj.last_invite_from(character_id)
        if lid is None:
            lid, lname = manager_obj.last_invite_to(character_id)
        if lid is None:
            return None, None, "no pending invite"
        return lid, lname, None
    # mode == last
    for step in chain:
        if step == "whisper":
            lid, lname = manager_obj.last_whisper_from(character_id)
        elif step == "emote":
            lid, lname = manager_obj.last_emote_to(character_id)
        elif step == "invite_from":
            lid, lname = manager_obj.last_invite_from(character_id)
        elif step == "invite_to":
            lid, lname = manager_obj.last_invite_to(character_id)
        else:
            continue
        if lid is not None:
            return lid, lname, None
    return None, None, "no one"


def _parse_positive_qty(raw: Any) -> int | None:
    """Parse buy/sell/discard quantity. Returns int >= 1 or None if invalid.

    Rejects bools and non-integer floats (2.5 must not silently become 2).
    Digit strings like \"2\" are accepted.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, float):
        if not math.isfinite(raw) or not raw.is_integer():
            return None
        q = int(raw)
        return q if q >= 1 else None
    if isinstance(raw, str):
        s = raw.strip()
        if not s or not s.lstrip("-").isdigit():
            return None
        try:
            q = int(s)
        except ValueError:
            return None
        return q if q >= 1 else None
    return None


async def _inventory_msg(character_id: int) -> dict:
    from database.db import get_db
    from game.item_manager import MAX_BAG_SLOTS, MAX_STACK_QTY

    db = await get_db()
    char = await get_character(character_id)
    items = await list_items(db, character_id)
    if char:
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["field_spells"] = field_spells_at(int(char["level"]))
        char = character_public(char, items)
    # Bag caps for client UI (distinct stacks / per-stack max)
    bag = {
        "used": len(items),
        "max_slots": MAX_BAG_SLOTS,
        "max_stack": MAX_STACK_QTY,
    }
    return msg(
        ServerMessageType.INVENTORY_UPDATE,
        items=items,
        character=char,
        bag=bag,
    )


def sanitize_chat(raw: Any) -> str | None:
    """Validate and clean chat text. Returns None if empty/invalid after sanitize."""
    if not isinstance(raw, str):
        return None
    text = _CTRL_RE.sub("", raw)
    text = " ".join(text.split())
    text = text.strip()
    if not text:
        return None
    if len(text) > CHAT_MAX_LEN:
        text = text[:CHAT_MAX_LEN]
    return text


def _resolve_item_arg(raw: Any) -> tuple[str | None, str | None]:
    """Resolve slash/UI item text → canonical id (or error reason)."""
    return resolve_item_id(raw)


async def _announce_combat_outcome(character_id: int, outcome: str) -> None:
    """Nearby multiplayer system line for combat result (victory / fled / defeat)."""
    hero = (manager.get_meta(character_id) or {}).get("name") or "Hero"
    if outcome == "defeat":
        text = f"{hero} was defeated!"
        include_self = True
    elif outcome == "victory":
        text = f"{hero} was victorious!"
        include_self = False
    elif outcome == "fled":
        text = f"{hero} fled battle!"
        include_self = False
    else:
        return
    await manager.broadcast_nearby(
        character_id,
        msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name="System",
            text=text,
            channel="system",
            system=True,
        ),
        include_self=include_self,
        respect_ignore=False,
    )


def _combat_update(battle, events: list | None = None) -> dict:
    snap = battle.snapshot()
    return msg(
        ServerMessageType.COMBAT_UPDATE,
        player_hp=snap["hero"]["hp"],
        player_mp=snap["hero"]["mp"],
        player_max_hp=snap["hero"]["max_hp"],
        player_max_mp=snap["hero"]["max_mp"],
        hero=snap["hero"],  # includes status (sleep / stopspell)
        enemy=snap["enemy"],
        events=events or [],
        legal_actions=snap["legal_actions"],
        turn=snap["turn"],
        phase=snap["phase"],
        outcome=snap["outcome"],
    )


async def _persist_battle_end(character_id: int, battle) -> dict:
    patch = battle.character_patch()
    gold_lost = 0
    if battle.outcome == "defeat":
        # DQ1-ish: wake at town, keep XP, lose half gold
        gold = int(str(patch.get("gold", "0")))
        gold_lost = gold - (gold // 2)
        gold = gold // 2
        patch["gold"] = str(gold)
        patch["current_hp"] = max(1, int(patch.get("max_hp", 15)) // 2)
        patch["world_x"] = SPAWN_X
        patch["world_y"] = SPAWN_Y
        manager.set_position(character_id, SPAWN_X, SPAWN_Y)
    char = await apply_character_patch(character_id, patch)
    if not char:
        return {}
    char["known_spells"] = battle_spells_at(int(char["level"]))
    char["bonuses"] = equipment_bonuses(char)
    if gold_lost:
        char["gold_lost"] = gold_lost
    return char


async def private_social_delivery(
    character_id: int,
    target_id: int,
    payload: dict,
    *,
    was_afk: bool,
    afk_message: str | None,
    outbound: list[dict],
) -> bool:
    """Send a private social payload; on socket failure refund chat + AFK.

    Returns True if delivered. On False, appends ``player not online`` error
    to ``outbound`` and restores AFK when the caller snapped it pre-allow_chat.
    """
    delivered = await manager.send(target_id, payload)
    if not delivered:
        manager.refund_chat(
            character_id, restore_afk=was_afk, afk_message=afk_message
        )
        outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
        return False
    return True


def social_peer_card(
    manager_obj: Any,
    pid: int | None,
    pname: str | None,
    *,
    viewer_id: int | None = None,
) -> dict[str, Any] | None:
    """Public social peer card (no coords). Optional nearby vs viewer for meetup.

    Online cards may include zone / afk / in_combat / session_id / afk_message.
    When ``viewer_id`` is set and the peer is online, sets ``nearby`` (AOI) without
    leaking map coordinates — helps /pending · /lastinvite · /lastemote meetup.
    """
    if pid is None:
        return None
    from network.websocket_manager import _zone_of

    online = manager_obj.is_online(pid)
    pmeta = manager_obj.get_meta(pid) if online else None
    card: dict[str, Any] = {
        "id": pid,
        "name": pname or (pmeta or {}).get("name") or "Hero",
        "online": online,
        "afk": bool((pmeta or {}).get("afk")) if pmeta else False,
    }
    if pmeta is not None:
        psid = pmeta.get("session_id")
        if psid is not None:
            card["session_id"] = psid
        z = _zone_of(pmeta)
        if isinstance(z, str) and z:
            card["zone"] = z
        if pmeta.get("in_combat"):
            card["in_combat"] = True
        if card["afk"]:
            pam = pmeta.get("afk_message")
            if isinstance(pam, str) and pam.strip():
                card["afk_message"] = pam.strip()[:48]
        if viewer_id is not None and online:
            try:
                card["nearby"] = pid in manager_obj.ids_nearby(viewer_id)
            except Exception:
                card["nearby"] = False
    return card


def peer_status_suffix(card: dict[str, Any] | None) -> str:
    """Human badge suffix: offline, or [zone,afk,fight,near|far]."""
    if not card:
        return ""
    if not card.get("online"):
        return " (offline)"
    bits: list[str] = []
    if card.get("zone"):
        bits.append(str(card["zone"]))
    if card.get("afk"):
        bits.append("afk")
    if card.get("in_combat"):
        bits.append("fight")
    if "nearby" in card:
        bits.append("near" if card.get("nearby") else "far")
    return f" [{','.join(bits)}]" if bits else " (online)"
