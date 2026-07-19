from typing import Any

from auth.jwt_handler import decode_access_token
from database.db import get_db
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager


async def handle_message(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
) -> tuple[int | None, int | None, list[dict]]:
    """Process one client message. Returns (character_id, user_id, outbound messages)."""
    msg_type = data.get("type")
    outbound: list[dict] = []

    if msg_type == ClientMessageType.PING:
        outbound.append(msg(ServerMessageType.PONG))
        return character_id, user_id, outbound

    if msg_type == ClientMessageType.AUTH:
        token = data.get("token")
        char_id = data.get("character_id")
        if not token or not char_id:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="token and character_id required"))
            return character_id, user_id, outbound

        payload = decode_access_token(token)
        if payload is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="invalid token"))
            return character_id, user_id, outbound

        db = await get_db()
        async with db.execute(
            "SELECT * FROM characters WHERE id = ? AND user_id = ?",
            (int(char_id), payload["user_id"]),
        ) as c:
            row = await c.fetchone()
        if row is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="character not found"))
            return character_id, user_id, outbound

        character = {k: row[k] for k in row.keys()}
        outbound.append(
            msg(
                ServerMessageType.AUTH_OK,
                player_id=character["id"],
                character=character,
            )
        )
        # Nearby players snapshot (Phase 3 will refine visibility)
        players = []
        for oid in manager.online_ids():
            if oid == character["id"]:
                continue
            async with db.execute("SELECT id, name, world_x, world_y, map_id, level FROM characters WHERE id = ?", (oid,)) as c:
                other = await c.fetchone()
            if other and other["map_id"] == character["map_id"]:
                players.append(dict(other))
        outbound.append(msg(ServerMessageType.WORLD_STATE, players=players, enemies=[]))
        return character["id"], payload["user_id"], outbound

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound

    if msg_type == ClientMessageType.MOVE:
        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid move"))
            return character_id, user_id, outbound

        # Basic bounds for MVP 8x8 map; refined in Phase 3
        x = max(0, min(7, int(x)))
        y = max(0, min(7, int(y)))
        db = await get_db()
        await db.execute(
            "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (x, y, character_id),
        )
        await db.commit()
        await manager.broadcast(
            msg(ServerMessageType.PLAYER_MOVED, player_id=character_id, x=x, y=y),
            exclude=character_id,
        )
        outbound.append(msg(ServerMessageType.PLAYER_MOVED, player_id=character_id, x=x, y=y))
        return character_id, user_id, outbound

    outbound.append(msg(ServerMessageType.ERROR, reason=f"unknown or unsupported type: {msg_type}"))
    return character_id, user_id, outbound
