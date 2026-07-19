import asyncio
import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, character_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            old = self._connections.get(character_id)
            if old is not None:
                try:
                    await old.close(code=4000, reason="Replaced by new connection")
                except Exception:
                    pass
            self._connections[character_id] = websocket

    async def disconnect(self, character_id: int) -> None:
        async with self._lock:
            self._connections.pop(character_id, None)

    def is_online(self, character_id: int) -> bool:
        return character_id in self._connections

    def online_ids(self) -> list[int]:
        return list(self._connections.keys())

    async def send(self, character_id: int, message: dict[str, Any]) -> bool:
        ws = self._connections.get(character_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message))
            return True
        except Exception:
            await self.disconnect(character_id)
            return False

    async def broadcast(self, message: dict[str, Any], exclude: int | None = None) -> None:
        dead: list[int] = []
        for cid, ws in list(self._connections.items()):
            if exclude is not None and cid == exclude:
                continue
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(cid)
        for cid in dead:
            await self.disconnect(cid)


manager = ConnectionManager()
