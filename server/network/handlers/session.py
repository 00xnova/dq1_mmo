"""Session multiplayer peeks: ping / sync (extracted from message_handler)."""

from __future__ import annotations

import time
from typing import Any

from game.world_manager import map_payload, zone_at
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

PING_TYPES = frozenset({ClientMessageType.PING, "ping"})
SYNC_TYPES = frozenset({ClientMessageType.SYNC, "sync"})


async def handle_ping(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    if character_id is not None:
        manager.touch(character_id)
    from config import PROCESS_STARTED_AT, VERSION as _VER

    client_t = data.get("t")
    pong_body: dict[str, Any] = {
        "t": client_t,
        "server_t": time.time(),
        "online": len(manager.online_ids()),
        "afk_count": manager.afk_count(),
        "combat_count": manager.combat_count(),
        "zones": manager.zone_counts(),
        "version": _VER,
        "uptime": max(0, int(time.time() - PROCESS_STARTED_AT)),
    }
    if character_id is not None:
        pong_body["nearby_count"] = len(manager.ids_nearby(character_id))
        pong_body["nearby_afk"] = manager.nearby_afk_count(character_id)
        pong_body["nearby_combat"] = manager.nearby_combat_count(character_id)
        pong_body["session_id"] = manager.session_id(character_id)
    outbound.append(msg(ServerMessageType.PONG, **pong_body))
    if data.get("sync") or data.get("presence"):
        if character_id is not None:
            nearby = manager.nearby_players(character_id)
            outbound.append(
                msg(
                    ServerMessageType.WORLD_STATE,
                    players=nearby,
                    enemies=[],
                    map=map_payload(),
                    online=len(manager.online_ids()),
                )
            )
    return character_id, user_id, outbound, None


async def handle_sync(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)
    # Repair AOI drift so peers re-appear after desync / reconnect storms
    aoi_msgs = await manager.rebuild_aoi(character_id)
    outbound.extend(aoi_msgs)
    meta = manager.get_meta(character_id)
    nearby = manager.nearby_players(character_id)
    sync_zone = None
    if meta is not None:
        try:
            sync_zone = zone_at(int(meta["x"]), int(meta["y"]))
        except Exception:
            sync_zone = None
    ignores_snap = manager.ignore_list(character_id)
    lw_id, lw_name = manager.last_whisper_from(character_id)
    last_whisper = None
    if lw_id is not None or lw_name:
        last_whisper = {"id": lw_id, "name": lw_name}
    from network.handlers._common import social_peer_card
    from network.websocket_manager import _is_idle as _idle_chk

    st_id, st_name = manager.last_share_to(character_id)
    sf_id, sf_name = manager.last_share_from(character_id)
    last_share_to = social_peer_card(
        manager, st_id, st_name, viewer_id=character_id
    )
    last_share_from = social_peer_card(
        manager, sf_id, sf_name, viewer_id=character_id
    )
    et_id, et_name = manager.last_emote_to(character_id)
    ef_id, ef_name = manager.last_emote_from(character_id)
    last_emote_to = social_peer_card(
        manager, et_id, et_name, viewer_id=character_id
    )
    last_emote_from = social_peer_card(
        manager, ef_id, ef_name, viewer_id=character_id
    )
    you_blob = None
    if meta is not None:
        you_blob = {
            "x": meta["x"],
            "y": meta["y"],
            "zone": sync_zone,
            "session_id": manager.session_id(character_id),
            "afk": bool(meta.get("afk")),
            "idle": _idle_chk(meta),
            "in_combat": bool(meta.get("in_combat")),
        }
        if you_blob["afk"]:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you_blob["afk_message"] = am.strip()[:48]
    outbound.append(
        msg(
            ServerMessageType.WORLD_STATE,
            players=nearby,
            enemies=[],
            map=map_payload(),
            online=len(manager.online_ids()),
            afk_count=manager.afk_count(),
            nearby_count=len(nearby),
            nearby_afk=manager.nearby_afk_count(character_id),
            nearby_combat=manager.nearby_combat_count(character_id),
            zones=manager.zone_counts(),
            roster=manager.online_roster(),
            you=you_blob,
            repel=manager.repel_remaining(character_id),
            radiant=manager.radiant_remaining(character_id),
            zone=sync_zone,
            session_id=manager.session_id(character_id),
            ignores=ignores_snap,
            last_whisper=last_whisper,
            last_share_to=last_share_to,
            last_share_from=last_share_from,
            last_emote_to=last_emote_to,
            last_emote_from=last_emote_from,
        )
    )
    return character_id, user_id, outbound, None
