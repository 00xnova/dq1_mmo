import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket

from game.world_manager import is_nearby

# Tunables
MOVE_MIN_INTERVAL = 0.10  # seconds between accepted steps
MSG_RATE_WINDOW = 1.0
MSG_RATE_MAX = 40  # messages per window after auth
IDLE_TIMEOUT = 90.0  # seconds without any message
HEARTBEAT_CHECK_INTERVAL = 15.0


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._meta: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._seq = 0  # global outbound id (optional)

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
    ) -> None:
        async with self._lock:
            old = self._connections.get(character_id)
            if old is not None and old is not websocket:
                try:
                    await old.close(code=4000, reason="Replaced by new connection")
                except Exception:
                    pass
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
                "dirty": False,  # position needs DB flush
            }

    async def disconnect(
        self,
        character_id: int,
        websocket: WebSocket | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            current = self._connections.get(character_id)
            if websocket is not None and current is not None and current is not websocket:
                return None
            self._connections.pop(character_id, None)
            return self._meta.pop(character_id, None)

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
        """Simple token-bucket-ish rate limit. Returns False if over limit."""
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
        """Return (allowed, retry_after_seconds)."""
        meta = self._meta.get(character_id)
        if meta is None:
            return False, 0.0
        now = time.monotonic()
        elapsed = now - float(meta.get("last_move_at") or 0.0)
        if elapsed < MOVE_MIN_INTERVAL:
            return False, MOVE_MIN_INTERVAL - elapsed
        meta["last_move_at"] = now
        return True, 0.0

    def set_position(self, character_id: int, x: float, y: float, *, seq: int | None = None) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["x"] = float(x)
            meta["y"] = float(y)
            meta["dirty"] = True
            if seq is not None:
                meta["last_move_seq"] = int(seq)

    def mark_clean(self, character_id: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["dirty"] = False

    def dirty_positions(self) -> list[tuple[int, float, float]]:
        out = []
        for cid, meta in self._meta.items():
            if meta.get("dirty"):
                out.append((cid, meta["x"], meta["y"]))
        return out

    def stale_ids(self, now: float | None = None) -> list[int]:
        now = now if now is not None else time.monotonic()
        return [
            cid
            for cid, meta in self._meta.items()
            if now - float(meta.get("last_seen") or 0.0) > IDLE_TIMEOUT
        ]

    def nearby_players(self, character_id: int) -> list[dict[str, Any]]:
        me = self._meta.get(character_id)
        if me is None:
            return []
        out: list[dict[str, Any]] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            if meta["map_id"] != me["map_id"]:
                continue
            if is_nearby(me["x"], me["y"], meta["x"], meta["y"]):
                out.append(
                    {
                        "id": meta["id"],
                        "name": meta["name"],
                        "world_x": meta["x"],
                        "world_y": meta["y"],
                        "map_id": meta["map_id"],
                        "level": meta["level"],
                    }
                )
        return out

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
        me = self._meta.get(source_id)
        if me is None:
            return
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid, ws in list(self._connections.items()):
            if cid == source_id and not include_self:
                continue
            other = self._meta.get(cid)
            if other is None:
                continue
            if other["map_id"] != me["map_id"]:
                continue
            if not is_nearby(me["x"], me["y"], other["x"], other["y"]):
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)


manager = ConnectionManager()
