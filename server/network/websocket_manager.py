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
CHAT_MIN_INTERVAL = 0.75  # max ~1.3 messages/sec per player
CHAT_MAX_LEN = 200
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
        "in_combat": bool(meta.get("in_combat")),
    }


def _online_card(meta: dict[str, Any]) -> dict[str, Any]:
    """Public roster entry (no position — avoid map radar abuse)."""
    return {
        "id": meta["id"],
        "name": meta["name"],
        "level": meta["level"],
        "in_combat": bool(meta.get("in_combat")),
    }


# Soft reconnect grace for in-memory multiplayer state (repel, move seq).
# Survives brief disconnects without a DB column; expires like combat grace.
RECONNECT_SOFT_GRACE = 60.0


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._meta: dict[int, dict[str, Any]] = {}
        # cid -> {repel_steps, last_move_seq, expires}
        self._soft_grace: dict[int, dict[str, Any]] = {}
        # Per-loop locks: a module-level asyncio.Lock binds to the first loop and
        # breaks when tests / restarts use a new event loop.
        self._locks: dict[int, asyncio.Lock] = {}
        self._session_seq = 0

    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _take_soft_grace(self, character_id: int) -> dict[str, Any]:
        """Pop soft-state grace if still valid (repel/radiant — move seq resets client-side)."""
        bag = self._soft_grace.pop(character_id, None)
        if not bag:
            return {}
        if time.monotonic() > float(bag.get("expires") or 0.0):
            return {}
        return bag

    def _stash_soft_grace(self, character_id: int, meta: dict[str, Any]) -> None:
        # Clients reset move seq on auth; restore buffs only.
        repel = max(0, int(meta.get("repel_steps") or 0))
        radiant = max(0, int(meta.get("radiant_steps") or 0))
        if repel <= 0 and radiant <= 0:
            self._soft_grace.pop(character_id, None)
            return
        self._soft_grace[character_id] = {
            "repel_steps": repel,
            "radiant_steps": radiant,
            "expires": time.monotonic() + RECONNECT_SOFT_GRACE,
        }

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
        in_combat: bool = False,
    ) -> list[dict[str, Any]]:
        """Register connection. Returns list of peer public metas now visible."""
        async with self._lock():
            old = self._connections.get(character_id)
            old_meta = self._meta.get(character_id)
            # Prefer live meta (socket replace), else short disconnect grace.
            if old_meta:
                grace_repel = max(0, int(old_meta.get("repel_steps") or 0))
                grace_radiant = max(0, int(old_meta.get("radiant_steps") or 0))
            else:
                bag = self._take_soft_grace(character_id)
                grace_repel = max(0, int(bag.get("repel_steps") or 0))
                grace_radiant = max(0, int(bag.get("radiant_steps") or 0))

            if old is not None and old is not websocket:
                try:
                    await old.close(code=4000, reason="Replaced by new connection")
                except Exception:
                    pass
                # drop old visibility links
                if old_meta:
                    for oid in list(old_meta.get("visible") or set()):
                        om = self._meta.get(oid)
                        if om and "visible" in om:
                            om["visible"].discard(character_id)

            now = time.monotonic()
            self._session_seq += 1
            session_id = self._session_seq
            self._connections[character_id] = websocket
            self._meta[character_id] = {
                "id": character_id,
                "name": name,
                "x": float(x),
                "y": float(y),
                "map_id": map_id,
                "level": level,
                "in_combat": bool(in_combat),
                "last_seen": now,
                "last_move_at": 0.0,
                # Always reset move seq on (re)connect — clients start at 0 on auth.
                "last_move_seq": 0,
                "last_chat_at": 0.0,
                "msg_window_start": now,
                "msg_count": 0,
                "dirty": False,
                "repel_steps": grace_repel,
                "radiant_steps": grace_radiant,
                "session_id": session_id,
                "visible": set(),  # peer ids currently in AOI
            }
            # Live again — drop any leftover grace bag
            self._soft_grace.pop(character_id, None)

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
        async with self._lock():
            current = self._connections.get(character_id)
            if websocket is not None and current is not None and current is not websocket:
                return None
            self._connections.pop(character_id, None)
            left_meta = self._meta.pop(character_id, None)
            if left_meta:
                self._stash_soft_grace(character_id, left_meta)
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
                "reason": "disconnect",
            }
            for oid in notify_ids:
                await self.send(oid, leave_msg)
        if left_meta is not None:
            await self.broadcast_online()
        return left_meta

    def is_online(self, character_id: int) -> bool:
        return character_id in self._connections

    def owns(self, character_id: int, websocket: WebSocket) -> bool:
        return self._connections.get(character_id) is websocket

    def online_ids(self) -> list[int]:
        return list(self._connections.keys())

    def online_roster(self) -> list[dict[str, Any]]:
        """All online players as public cards (id/name/level/in_combat)."""
        out: list[dict[str, Any]] = []
        for cid in self._connections:
            meta = self._meta.get(cid)
            if meta:
                out.append(_online_card(meta))
        out.sort(key=lambda p: str(p.get("name") or "").lower())
        return out

    # Coalesce rapid join/leave pulses (reconnect storms), but flush soon.
    ONLINE_PULSE_MIN_INTERVAL = 0.15

    async def broadcast_online(self) -> None:
        """Pulse global online count to every connected client (debounced)."""
        now = time.monotonic()
        last = float(getattr(self, "_last_online_pulse", 0.0) or 0.0)
        if now - last < self.ONLINE_PULSE_MIN_INTERVAL:
            self._online_pulse_pending = True
            if not getattr(self, "_online_flush_scheduled", False):
                self._online_flush_scheduled = True
                try:
                    asyncio.get_running_loop().create_task(
                        self._delayed_online_flush(), name="dq1-online-pulse"
                    )
                except RuntimeError:
                    # No running loop — flush immediately
                    self._online_flush_scheduled = False
                    await self.flush_online_pulse()
            return
        self._last_online_pulse = now
        self._online_pulse_pending = False
        await self.broadcast(
            {"type": "online", "online": len(self._connections), "roster": self.online_roster()}
        )

    async def _delayed_online_flush(self) -> None:
        try:
            await asyncio.sleep(self.ONLINE_PULSE_MIN_INTERVAL)
            await self.flush_online_pulse()
        finally:
            self._online_flush_scheduled = False

    async def flush_online_pulse(self) -> None:
        """Send a pending debounced online pulse if any."""
        if not getattr(self, "_online_pulse_pending", False):
            return
        self._online_pulse_pending = False
        self._last_online_pulse = time.monotonic()
        await self.broadcast(
            {"type": "online", "online": len(self._connections), "roster": self.online_roster()}
        )

    def purge_expired_soft_grace(self) -> int:
        """Drop expired reconnect soft-state bags. Returns number removed."""
        now = time.monotonic()
        dead = [
            cid
            for cid, bag in self._soft_grace.items()
            if now > float(bag.get("expires") or 0.0)
        ]
        for cid in dead:
            self._soft_grace.pop(cid, None)
        return len(dead)

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

    def set_in_combat(self, character_id: int, in_combat: bool) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["in_combat"] = bool(in_combat)

    def set_repel(self, character_id: int, steps: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["repel_steps"] = max(0, int(steps))
        # Keep grace bag in sync so a mid-session crash path still restores
        if steps > 0 and character_id not in self._connections:
            bag = dict(self._soft_grace.get(character_id) or {})
            bag["repel_steps"] = max(0, int(steps))
            bag["radiant_steps"] = int(bag.get("radiant_steps") or 0)
            bag["expires"] = time.monotonic() + RECONNECT_SOFT_GRACE
            self._soft_grace[character_id] = bag

    def repel_remaining(self, character_id: int) -> int:
        meta = self._meta.get(character_id)
        if meta is None:
            return 0
        return max(0, int(meta.get("repel_steps") or 0))

    def consume_repel_step(self, character_id: int) -> bool:
        """Tick one repel step on move. Returns True if encounters should be blocked."""
        meta = self._meta.get(character_id)
        if meta is None:
            return False
        left = int(meta.get("repel_steps") or 0)
        if left <= 0:
            return False
        meta["repel_steps"] = left - 1
        return True

    # RADIANT: soft light — reduced dungeon encounter chance for N steps
    RADIANT_STEPS = 64

    def set_radiant(self, character_id: int, steps: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["radiant_steps"] = max(0, int(steps))
        if steps > 0 and character_id not in self._connections:
            bag = dict(self._soft_grace.get(character_id) or {})
            bag["radiant_steps"] = max(0, int(steps))
            bag["repel_steps"] = int(bag.get("repel_steps") or 0)
            bag["expires"] = time.monotonic() + RECONNECT_SOFT_GRACE
            self._soft_grace[character_id] = bag

    def radiant_remaining(self, character_id: int) -> int:
        meta = self._meta.get(character_id)
        if meta is None:
            return 0
        return max(0, int(meta.get("radiant_steps") or 0))

    def consume_radiant_step(self, character_id: int) -> bool:
        """Tick one radiant step. Returns True if light was active for this step."""
        meta = self._meta.get(character_id)
        if meta is None:
            return False
        left = int(meta.get("radiant_steps") or 0)
        if left <= 0:
            return False
        meta["radiant_steps"] = left - 1
        return True

    def last_move_seq(self, character_id: int) -> int:
        meta = self._meta.get(character_id)
        if meta is None:
            return 0
        return int(meta.get("last_move_seq") or 0)

    def find_id_by_name(self, name: str) -> int | None:
        """Case-insensitive exact match against online character names."""
        if not name or not isinstance(name, str):
            return None
        key = name.strip().lower()
        if not key:
            return None
        for cid, meta in self._meta.items():
            if str(meta.get("name") or "").strip().lower() == key:
                return cid
        return None

    def allow_chat(self, character_id: int) -> tuple[bool, float]:
        """Rate-limit chat. Returns (allowed, retry_after_seconds)."""
        meta = self._meta.get(character_id)
        if meta is None:
            return False, 0.0
        now = time.monotonic()
        elapsed = now - float(meta.get("last_chat_at") or 0.0)
        if elapsed < CHAT_MIN_INTERVAL:
            return False, CHAT_MIN_INTERVAL - elapsed
        meta["last_chat_at"] = now
        return True, 0.0

    async def publish_status(self, character_id: int, *, pulse_online: bool = False) -> None:
        """Broadcast current public status (level, combat) to AOI peers.

        When pulse_online is True (combat enter/leave), also refresh global roster cards.
        """
        me = self._meta.get(character_id)
        if me is None:
            return
        payload = {
            "type": "player_update",
            "player_id": character_id,
            "name": me["name"],
            "level": me["level"],
            "x": me["x"],
            "y": me["y"],
            "in_combat": bool(me.get("in_combat")),
        }
        for oid in list(me.get("visible") or set()):
            await self.send(oid, payload)
        if pulse_online:
            await self.broadcast_online()

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
                    "in_combat": me_pub["in_combat"],
                },
            )
            # tell us they appeared
            other_pub = _public_meta(other)
            to_self.append(
                {
                    "type": "player_joined",
                    "player_id": other_pub["id"],
                    "name": other_pub["name"],
                    "x": other_pub["x"],
                    "y": other_pub["y"],
                    "level": other_pub["level"],
                    "in_combat": other_pub["in_combat"],
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
            "in_combat": me_pub["in_combat"],
        }
        for oid in stayed:
            await self.send(oid, move_msg)

        return to_self

    async def publish_level(self, character_id: int, level: int) -> None:
        me = self._meta.get(character_id)
        if me is None:
            return
        me["level"] = int(level)
        # Pulse roster so other clients see the new level without a who refresh
        await self.publish_status(character_id, pulse_online=True)

    def session_id(self, character_id: int) -> int | None:
        meta = self._meta.get(character_id)
        if meta is None:
            return None
        sid = meta.get("session_id")
        return int(sid) if sid is not None else None

    async def broadcast_online_force(self) -> None:
        """Unconditional online pulse (periodic refresh; bypasses debounce)."""
        self._online_pulse_pending = False
        self._last_online_pulse = time.monotonic()
        await self.broadcast(
            {"type": "online", "online": len(self._connections), "roster": self.online_roster()}
        )

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
        """Send to geometric AOI peers (union with cached visible for safety).

        Prefer live geometry over the cached visible set so stale/partial AOI
        never drops nearby chat, emotes, or social traffic.
        """
        me = self._meta.get(source_id)
        if me is None:
            return
        targets = set(self.ids_nearby(source_id))
        # Union cached visible in case geometry and cache briefly disagree mid-move
        targets |= set(me.get("visible") or set())
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

    def ids_in_zone(self, character_id: int) -> list[int]:
        """Players on the same map whose tile zone matches the source (town/field/dungeon)."""
        from game.world_manager import zone_at

        me = self._meta.get(character_id)
        if me is None:
            return []
        try:
            my_zone = zone_at(int(me["x"]), int(me["y"]))
        except Exception:
            return []
        if my_zone in ("blocked",):
            return []
        out: list[int] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            if meta.get("map_id") != me.get("map_id"):
                continue
            try:
                z = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                continue
            if z == my_zone:
                out.append(cid)
        return out

    async def broadcast_zone(
        self,
        source_id: int,
        message: dict[str, Any],
        *,
        include_self: bool = True,
    ) -> None:
        """Send to all online players in the same zone (town / field / dungeon)."""
        me = self._meta.get(source_id)
        if me is None:
            return
        targets = set(self.ids_in_zone(source_id))
        if include_self:
            targets.add(source_id)
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid in targets:
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)

    async def rebuild_aoi(self, character_id: int) -> list[dict[str, Any]]:
        """Reconcile cached AOI with geometry; notify joins/leaves. Returns msgs for mover."""
        me = self._meta.get(character_id)
        if me is None:
            return []
        return await self.publish_move(
            character_id,
            float(me["x"]),
            float(me["y"]),
            seq=int(me.get("last_move_seq") or 0) or None,
        )

    def find_id_by_player_id(self, player_id: Any) -> int | None:
        """Resolve online character id from int/str player_id."""
        if player_id is None:
            return None
        try:
            pid = int(player_id)
        except (TypeError, ValueError):
            return None
        if pid in self._meta and pid in self._connections:
            return pid
        return None


manager = ConnectionManager()


def reset_manager() -> None:
    """Clear in-place multiplayer state (lifespan start/stop). Keep same object refs."""
    manager._connections.clear()
    manager._meta.clear()
    manager._soft_grace.clear()
    manager._locks.clear()
    manager._last_online_pulse = 0.0
    manager._online_pulse_pending = False
    manager._online_flush_scheduled = False
    manager._session_seq = 0
