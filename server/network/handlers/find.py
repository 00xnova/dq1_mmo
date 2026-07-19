"""Find online players (extracted). Name prefix + zone/afk/idle/combat filters.

No coordinates on roster hits. Social aliases (@pending, @last, …). Response
includes multiplayer census and plain message for clients under peek spam.
"""

from __future__ import annotations

import re
from typing import Any

from network.handlers._common import _resolve_social_peer, _social_alias
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import _online_card, manager

FIND_TYPES = frozenset({ClientMessageType.FIND, "find", "search"})
ALL_TYPES = FIND_TYPES


def _parse_yn_token(raw: Any) -> bool | None | str:
    """Return True/False, None if unset, or 'bad' if invalid string."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return bool(int(raw))
    if isinstance(raw, str) and raw.strip():
        s = raw.strip().lower()
        if s in ("yes", "1", "true", "afk", "away", "idle"):
            return True
        if s in ("no", "0", "false", "back", "active"):
            return False
        return "bad"
    return "bad"


def _find_message(
    hits: list[dict[str, Any]],
    *,
    query: str,
    online_n: int,
    filtered_out: bool,
    find_msg_extra: dict[str, Any],
) -> str:
    if filtered_out and find_msg_extra.get("message"):
        return str(find_msg_extra["message"])
    n = len(hits)
    qbit = f" for {query}" if query else ""
    if n == 0:
        return f"No heroes found{qbit}. · {online_n} online"
    if n == 1:
        name = hits[0].get("name") or "Hero"
        zone = hits[0].get("zone")
        zbit = f" · {zone}" if zone else ""
        return f"Found {name}{zbit}.{qbit} · {online_n} online"
    return f"Found {n} heroes{qbit}. · {online_n} online"


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch find/search. Returns None if not a find message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)
    q = data.get("q") or data.get("query") or data.get("name") or data.get("prefix") or ""
    zone_f = data.get("zone") or data.get("area")
    afk_f = data.get("afk")
    idle_f = data.get("idle")
    q_clean = q.strip() if isinstance(q, str) else ""

    combat_f = data.get("combat")
    if combat_f is None:
        combat_f = data.get("fighting")
    # Pull ALL zone:/in:, afk:, idle:, combat: tokens from free text.
    if isinstance(q_clean, str) and q_clean:
        for _ in range(12):
            progressed = False
            m_zone = re.search(
                r"(?:^|\s)(?:zone|in):(\w+)\b", q_clean, flags=re.I
            )
            if m_zone:
                zone_f = m_zone.group(1)
                q_clean = (
                    q_clean[: m_zone.start()] + q_clean[m_zone.end() :]
                ).strip()
                progressed = True
            m_afk = re.search(r"(?:^|\s)afk:(\w+)\b", q_clean, flags=re.I)
            if m_afk:
                tok = m_afk.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="invalid afk filter")
                    )
                    return character_id, user_id, outbound, None
                afk_f = tok in ("yes", "1", "true")
                q_clean = (
                    q_clean[: m_afk.start()] + q_clean[m_afk.end() :]
                ).strip()
                progressed = True
            m_idle = re.search(r"(?:^|\s)idle:(\w+)\b", q_clean, flags=re.I)
            if m_idle:
                tok = m_idle.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="invalid idle filter")
                    )
                    return character_id, user_id, outbound, None
                idle_f = tok in ("yes", "1", "true")
                q_clean = (
                    q_clean[: m_idle.start()] + q_clean[m_idle.end() :]
                ).strip()
                progressed = True
            m_combat = re.search(
                r"(?:^|\s)(?:combat|fighting):(\w+)\b", q_clean, flags=re.I
            )
            if m_combat:
                tok = m_combat.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(
                            ServerMessageType.ERROR,
                            reason="invalid combat filter",
                        )
                    )
                    return character_id, user_id, outbound, None
                combat_f = tok in ("yes", "1", "true")
                q_clean = (
                    q_clean[: m_combat.start()] + q_clean[m_combat.end() :]
                ).strip()
                progressed = True
            if not progressed:
                break
        q_clean = re.sub(r"\s+", " ", q_clean).strip()
        if q_clean.lower() in ("afk", "away"):
            afk_f = True
            q_clean = ""
        if q_clean.lower() in ("idle",):
            idle_f = True
            q_clean = ""
        if q_clean.lower() in ("combat", "fighting", "battles"):
            combat_f = True
            q_clean = ""
    if isinstance(zone_f, str) and zone_f.strip():
        znorm = zone_f.strip().lower()
        if znorm not in ("town", "field", "dungeon"):
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid zone"))
            return character_id, user_id, outbound, None
        zone_f = znorm
    else:
        zone_f = None
    afk_filter = _parse_yn_token(afk_f)
    if afk_filter == "bad":
        outbound.append(msg(ServerMessageType.ERROR, reason="invalid afk filter"))
        return character_id, user_id, outbound, None
    idle_filter = _parse_yn_token(idle_f)
    if idle_filter == "bad":
        outbound.append(msg(ServerMessageType.ERROR, reason="invalid idle filter"))
        return character_id, user_id, outbound, None
    combat_filter = _parse_yn_token(combat_f)
    if combat_filter == "bad":
        outbound.append(msg(ServerMessageType.ERROR, reason="invalid combat filter"))
        return character_id, user_id, outbound, None
    if (
        not q_clean
        and zone_f is None
        and afk_filter is None
        and idle_filter is None
        and combat_filter is None
    ):
        outbound.append(msg(ServerMessageType.ERROR, reason="find query required"))
        return character_id, user_id, outbound, None
    limit = data.get("limit") or 20
    try:
        limit_i = int(limit)
    except (TypeError, ValueError):
        limit_i = 20
    social_q = _social_alias(q_clean)
    if social_q:
        lid, lname, empty = _resolve_social_peer(manager, character_id, social_q)
        if lid is None:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason=empty
                    if social_q
                    in ("pending", "share", "share_from", "emote", "emote_from")
                    else "no one to find",
                )
            )
            return character_id, user_id, outbound, None
        if lid not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        pmeta = manager.get_meta(lid)
        if pmeta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        card = _online_card(pmeta)
        peer_name = str(card.get("name") or lname or "Hero")
        peer_zone = card.get("zone") if isinstance(card.get("zone"), str) else None
        filtered_out = False
        filter_why: str | None = None
        if zone_f and card.get("zone") != zone_f:
            hits: list[dict[str, Any]] = []
            filtered_out = True
            filter_why = f"zone:{zone_f}"
        elif afk_filter is not None and bool(card.get("afk")) is not bool(afk_filter):
            hits = []
            filtered_out = True
            filter_why = "afk:" + ("yes" if afk_filter else "no")
        elif idle_filter is not None and bool(card.get("idle")) is not bool(
            idle_filter
        ):
            hits = []
            filtered_out = True
            filter_why = "idle:" + ("yes" if idle_filter else "no")
        elif combat_filter is not None and bool(card.get("in_combat")) is not bool(
            combat_filter
        ):
            hits = []
            filtered_out = True
            filter_why = "combat:" + ("yes" if combat_filter else "no")
        else:
            hits = [card]
        q_clean = (
            "@pending"
            if social_q
            in ("pending", "share", "share_from", "emote", "emote_from")
            else ("@last" if social_q == "last" else f"@{social_q}")
        )
    else:
        hits = manager.find_by_prefix(
            q_clean,
            limit=limit_i,
            zone=zone_f,
            afk=afk_filter,
            idle=idle_filter,
            combat=combat_filter,
        )
        if character_id is not None and hits:
            for card in hits:
                try:
                    if int(card.get("id") or 0) == int(character_id):
                        card["you"] = True
                except (TypeError, ValueError):
                    continue
        filtered_out = False
        filter_why = None
        peer_name = None
        peer_zone = None
    bits: list[str] = []
    if q_clean:
        bits.append(q_clean[:24])
    if zone_f:
        bits.append(f"zone:{zone_f}")
    if afk_filter is True:
        bits.append("afk:yes")
    elif afk_filter is False:
        bits.append("afk:no")
    if idle_filter is True:
        bits.append("idle:yes")
    elif idle_filter is False:
        bits.append("idle:no")
    if combat_filter is True:
        bits.append("combat:yes")
    elif combat_filter is False:
        bits.append("combat:no")
    find_msg_extra: dict[str, Any] = {}
    if filtered_out and peer_name:
        find_msg_extra["filtered"] = True
        find_msg_extra["filtered_peer"] = peer_name
        if filter_why:
            find_msg_extra["filter"] = filter_why
        if peer_zone:
            find_msg_extra["peer_zone"] = peer_zone
        where = f" in {peer_zone}" if peer_zone else ""
        find_msg_extra["message"] = (
            f"{peer_name} online{where} but filtered out"
            f" ({filter_why or 'filter'})"
        )
    query_str = " ".join(bits)
    online_n = len(manager.online_ids())
    plain = _find_message(
        hits,
        query=query_str,
        online_n=online_n,
        filtered_out=filtered_out,
        find_msg_extra=find_msg_extra,
    )
    body: dict[str, Any] = {
        "type": ServerMessageType.FIND,
        "query": query_str,
        "zone": zone_f,
        "afk": afk_filter,
        "idle": idle_filter,
        "combat": combat_filter,
        "players": hits,
        "online": online_n,
        "afk_count": manager.afk_count(),
        "combat_count": manager.combat_count(),
        "count": len(hits),
        "zones": manager.zone_counts(),
        "nearby_count": len(manager.ids_nearby(character_id)),
        "message": find_msg_extra.get("message") or plain,
    }
    for k, v in find_msg_extra.items():
        if k != "message":
            body[k] = v
    outbound.append(body)
    return character_id, user_id, outbound, None
