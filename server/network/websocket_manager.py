import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket

from game.world_manager import is_nearby

# Tunables
MOVE_MIN_INTERVAL = 0.10
MSG_RATE_WINDOW = 1.0
MSG_RATE_MAX = 40
IDLE_TIMEOUT = 90.0
HEARTBEAT_CHECK_INTERVAL = 15.0


def _public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": meta["id"],
        "name": meta["name"],
        "world_x": meta["x"],
        "world_y": meta["y"],
        "x": meta["x"],
        "y": meta["y"],
        "map_id": meta["map_id"],
        "level": meta["level"],
    }


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._meta: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        character_id: int,
        websocket: WebSocket,
        *,
        name: str,
        x: float,
        y: float,
        map_id: int,
        level: int = 1,
    ) -> list[dict[str, Any]]:
        """Register connection. Returns list of peer public metas now visible."""
        async with self._lock:
            old = self._connections.get(character_id)
            if old is not None and old is not websocket:
                try:
                    await old.close(code=4000, reason="Replaced by new connection")
                except Exception:
                    pass
                # drop old visibility links
                old_meta = self._meta.get(character_id)
                if old_meta:
                    for oid in list(old_meta.get("visible") or set()):
                        om = self._meta.get(oid)
                        if om and "visible" in om:
                            om["visible"].discard(character_id)

            now = time.monotonic()
            self._connections[character_id] = websocket
            self._meta[character_id] = {
                "id": character_id,
                "name": name,
                "x": float(x),
                "y": float(y),
                "map_id": map_id,
                "level": level,
                "last_seen": now,
                "last_move_at": 0.0,
                "last_move_seq": 0,
                "msg_window_start": now,
                "msg_count": 0,
                "dirty": False,
                "visible": set(),  # peer ids currently in AOI
            }

        # Build AOI outside lock for sends (re-enter carefully)
        peers = self.ids_nearby(character_id)
        me = self._meta.get(character_id)
        if me is None:
            return []
        me["visible"] = set(peers)
        peer_publics: list[dict[str, Any]] = []
        for oid in peers:
            other = self._meta.get(oid)
            if not other:
                continue
            other.setdefault("visible", set()).add(character_id)
            peer_publics.append(_public_meta(other))
        return peer_publics

    async def disconnect(
        self,
        character_id: int,
        websocket: WebSocket | None = None,
    ) -> dict[str, Any] | None:
        notify_ids: list[int] = []
        left_meta: dict[str, Any] | None = None
        async with self._lock:
            current = self._connections.get(character_id)
            if websocket is not None and current is not None and current is not websocket:
                return None
            self._connections.pop(character_id, None)
            left_meta = self._meta.pop(character_id, None)
            if left_meta:
                notify_ids = list(left_meta.get("visible") or set())
                for oid in notify_ids:
                    om = self._meta.get(oid)
                    if om and "visible" in om:
                        om["visible"].discard(character_id)

        # Notify peers who could see us
        if left_meta and notify_ids:
            leave_msg = {
                "type": "player_left",
                "player_id": character_id,
                "name": left_meta.get("name"),
            }
            for oid in notify_ids:
                await self.send(oid, leave_msg)
        return left_meta

    def is_online(self, character_id: int) -> bool:
        return character_id in self._connections

    def owns(self, character_id: int, websocket: WebSocket) -> bool:
        return self._connections.get(character_id) is websocket

    def online_ids(self) -> list[int]:
        return list(self._connections.keys())

    def get_meta(self, character_id: int) -> dict[str, Any] | None:
        return self._meta.get(character_id)

    def touch(self, character_id: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["last_seen"] = time.monotonic()

    def allow_message(self, character_id: int) -> bool:
        meta = self._meta.get(character_id)
        if meta is None:
            return False
        now = time.monotonic()
        meta["last_seen"] = now
        if now - meta["msg_window_start"] >= MSG_RATE_WINDOW:
            meta["msg_window_start"] = now
            meta["msg_count"] = 0
        meta["msg_count"] += 1
        return meta["msg_count"] <= MSG_RATE_MAX

    def allow_move(self, character_id: int) -> tuple[bool, float]:
        meta = self._meta.get(character_id)
        if meta is None:
            return False, 0.0
        now = time.monotonic()
        elapsed = now - float(meta.get("last_move_at") or 0.0)
        if elapsed < MOVE_MIN_INTERVAL:
            return False, MOVE_MIN_INTERVAL - elapsed
        meta["last_move_at"] = now
        return True, 0.0

    def set_level(self, character_id: int, level: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["level"] = int(level)

    def ids_nearby(self, character_id: int) -> list[int]:
        me = self._meta.get(character_id)
        if me is None:
            return []
        out: list[int] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            if meta["map_id"] != me["map_id"]:
                continue
            if is_nearby(me["x"], me["y"], meta["x"], meta["y"]):
                out.append(cid)
        return out

    def nearby_players(self, character_id: int) -> list[dict[str, Any]]:
        out = []
        for cid in self.ids_nearby(character_id):
            meta = self._meta.get(cid)
            if meta:
                out.append(_public_meta(meta))
        return out

    def set_position(self, character_id: int, x: float, y: float, *, seq: int | None = None) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["x"] = float(x)
            meta["y"] = float(y)
            meta["dirty"] = True
            if seq is not None:
                meta["last_move_seq"] = int(seq)

    async def publish_move(
        self,
        character_id: int,
        x: float,
        y: float,
        *,
        seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Update position and resolve AOI.
        Returns messages that should be delivered to the moving player
        (joins/leaves for peers entering/leaving their view).
        Peers are notified directly.
        """
        me = self._meta.get(character_id)
        if me is None:
            return []

        old_visible: set[int] = set(me.get("visible") or set())
        me["x"] = float(x)
        me["y"] = float(y)
        me["dirty"] = True
        if seq is not None:
            me["last_move_seq"] = int(seq)

        new_visible = set(self.ids_nearby(character_id))
        entered = new_visible - old_visible
        left = old_visible - new_visible
        stayed = old_visible & new_visible
        me["visible"] = new_visible

        me_pub = _public_meta(me)
        to_self: list[dict[str, Any]] = []

        # Peers who newly see us / we newly see
        for oid in entered:
            other = self._meta.get(oid)
            if not other:
                continue
            other.setdefault("visible", set()).add(character_id)
            # tell them we appeared
            await self.send(
                oid,
                {
                    "type": "player_joined",
                    "player_id": character_id,
                    "name": me_pub["name"],
                    "x": me_pub["x"],
                    "y": me_pub["y"],
                    "level": me_pub["level"],
                },
            )
            # tell us they appeared
            to_self.append(
                {
                    "type": "player_joined",
                    "player_id": other["id"],
                    "name": other["name"],
                    "x": other["x"],
                    "y": other["y"],
                    "level": other["level"],
                }
            )

        # Peers who lost sight
        for oid in left:
            other = self._meta.get(oid)
            if other is not None:
                other.setdefault("visible", set()).discard(character_id)
                await self.send(
                    oid,
                    {
                        "type": "player_left",
                        "player_id": character_id,
                        "name": me_pub["name"],
                        "reason": "out_of_range",
                    },
                )
            to_self.append(
                {
                    "type": "player_left",
                    "player_id": oid,
                    "name": (other or {}).get("name"),
                    "reason": "out_of_range",
                }
            )

        # Still visible — movement update
        move_msg = {
            "type": "player_moved",
            "player_id": character_id,
            "x": me_pub["x"],
            "y": me_pub["y"],
            "seq": seq,
            "name": me_pub["name"],
            "level": me_pub["level"],
        }
        for oid in stayed:
            await self.send(oid, move_msg)

        return to_self

    async def publish_level(self, character_id: int, level: int) -> None:
        me = self._meta.get(character_id)
        if me is None:
            return
        me["level"] = int(level)
        payload = {
            "type": "player_update",
            "player_id": character_id,
            "name": me["name"],
            "level": me["level"],
            "x": me["x"],
            "y": me["y"],
        }
        for oid in list(me.get("visible") or set()):
            await self.send(oid, payload)

    def mark_clean(self, character_id: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["dirty"] = False

    def dirty_positions(self) -> list[tuple[int, float, float]]:
        return [
            (cid, meta["x"], meta["y"])
            for cid, meta in self._meta.items()
            if meta.get("dirty")
        ]

    def stale_ids(self, now: float | None = None) -> list[int]:
        now = now if now is not None else time.monotonic()
        return [
            cid
            for cid, meta in self._meta.items()
            if now - float(meta.get("last_seen") or 0.0) > IDLE_TIMEOUT
        ]

    async def send(self, character_id: int, message: dict[str, Any]) -> bool:
        ws = self._connections.get(character_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message, default=str))
            return True
        except Exception:
            await self.disconnect(character_id, ws)
            return False

    async def broadcast(self, message: dict[str, Any], exclude: int | None = None) -> None:
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid, ws in list(self._connections.items()):
            if exclude is not None and cid == exclude:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)

    async def broadcast_nearby(
        self,
        source_id: int,
        message: dict[str, Any],
        *,
        include_self: bool = False,
    ) -> None:
        """Send to peers currently in source's AOI set (or geometric nearby if empty)."""
        me = self._meta.get(source_id)
        if me is None:
            return
        targets = set(me.get("visible") or set())
        if not targets:
            targets = set(self.ids_nearby(source_id))
        if include_self:
            targets.add(source_id)
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid in targets:
            if cid == source_id and not include_self:
                continue
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)


manager = ConnectionManager()
