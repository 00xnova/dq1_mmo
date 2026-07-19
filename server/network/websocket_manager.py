import asyncio
import json
import math
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
# Softer idle for roster badges (AFK) — still below kick timeout
IDLE_SOFT = 45.0
HEARTBEAT_CHECK_INTERVAL = 15.0
IGNORE_MAX = 32


def _zone_of(meta: dict[str, Any]) -> str | None:
    """Walkable zone name for presence payloads (town/field/dungeon) or None."""
    from game.world_manager import zone_at

    try:
        x, y = float(meta["x"]), float(meta["y"])
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        z = zone_at(int(x), int(y))
        if z in ("town", "field", "dungeon"):
            return z
    except Exception:
        return None
    return None


def sanitize_afk_message(raw: Any, *, max_len: int = 48) -> str | None:
    """Optional AFK status text for multiplayer peeks (look/who/whisper tip).

    Only real strings are accepted — never coerce bool/int/list to \"True\"/\"123\".
    """
    if raw is None or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    # Strip control chars; keep printable unicode
    text = "".join(ch for ch in text if ch.isprintable() and ch not in "\n\r\t")
    text = text.strip()
    if not text:
        return None
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text or None


def coerce_character_id(raw: Any) -> int | None:
    """Strict positive character id. Rejects bool and non-integer floats."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        if not math.isfinite(raw) or not raw.is_integer():
            return None
        pid = int(raw)
    elif isinstance(raw, int):
        pid = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s or not s.lstrip("-").isdigit():
            return None
        try:
            pid = int(s)
        except ValueError:
            return None
    else:
        return None
    if pid <= 0:
        return None
    return pid


def _attach_afk_message(card: dict[str, Any], meta: dict[str, Any]) -> None:
    """Add afk_message to a public card when the player is manually AFK."""
    if not card.get("afk"):
        return
    msg = meta.get("afk_message")
    if isinstance(msg, str) and msg.strip():
        card["afk_message"] = msg.strip()[:48]


def _public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    pub = {
        "id": meta["id"],
        "name": meta["name"],
        "world_x": meta["x"],
        "world_y": meta["y"],
        "x": meta["x"],
        "y": meta["y"],
        "map_id": meta["map_id"],
        "level": meta["level"],
        "in_combat": bool(meta.get("in_combat")),
        "idle": _is_idle(meta),
        # Manual /afk vs soft-idle — peers need the explicit flag for badges
        "afk": bool(meta.get("afk")),
    }
    z = _zone_of(meta)
    if z:
        pub["zone"] = z
    sid = meta.get("session_id")
    if sid is not None:
        pub["session_id"] = sid
    if pub["afk"]:
        try:
            since = float(meta.get("afk_since") or 0.0)
            if since > 0:
                pub["afk_for"] = max(0, int(time.monotonic() - since))
        except (TypeError, ValueError):
            pass
        _attach_afk_message(pub, meta)
    return pub


def _is_idle(meta: dict[str, Any], now: float | None = None) -> bool:
    """AFK badge: manual /afk flag or soft inactivity timeout."""
    if meta.get("afk"):
        return True
    now = now if now is not None else time.monotonic()
    last = float(meta.get("last_seen") or 0.0)
    return (now - last) >= IDLE_SOFT


def _online_card(meta: dict[str, Any]) -> dict[str, Any]:
    """Public roster entry (no position — avoid map radar abuse).

    Zone name is OK (town/field/dungeon) without x/y — helps social find/who.
    session_id helps clients reconcile reconnects without map coords.
    afk is manual /afk (idle may also be true from soft timeout).
    """
    card = {
        "id": meta["id"],
        "name": meta["name"],
        "level": meta["level"],
        "in_combat": bool(meta.get("in_combat")),
        "idle": _is_idle(meta),
        "afk": bool(meta.get("afk")),
    }
    zone = _zone_of(meta)
    if zone:
        card["zone"] = zone
    sid = meta.get("session_id")
    if sid is not None:
        card["session_id"] = sid
    if card["afk"]:
        try:
            since = float(meta.get("afk_since") or 0.0)
            if since > 0:
                card["afk_for"] = max(0, int(time.monotonic() - since))
        except (TypeError, ValueError):
            pass
        _attach_afk_message(card, meta)
    return card


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
        """Pop soft-state grace if still valid (repel/radiant/ignore — move seq resets)."""
        bag = self._soft_grace.pop(character_id, None)
        if not bag:
            return {}
        if time.monotonic() > float(bag.get("expires") or 0.0):
            return {}
        return bag

    def _stash_soft_grace(self, character_id: int, meta: dict[str, Any]) -> None:
        # Clients reset move seq on auth; restore buffs + ignore + last social peers.
        repel = max(0, int(meta.get("repel_steps") or 0))
        radiant = max(0, int(meta.get("radiant_steps") or 0))
        ignore = set(meta.get("ignore") or set())
        ignore_names = dict(meta.get("ignore_names") or {})
        last_from = meta.get("last_whisper_from_id")
        last_name = meta.get("last_whisper_from_name")
        last_emote_id = meta.get("last_emote_to_id")
        last_emote_name = meta.get("last_emote_to_name")
        last_emote_from_id = meta.get("last_emote_from_id")
        last_emote_from_name = meta.get("last_emote_from_name")
        last_share_id = meta.get("last_share_to_id")
        last_share_name = meta.get("last_share_to_name")
        last_share_from_id = meta.get("last_share_from_id")
        last_share_from_name = meta.get("last_share_from_name")
        last_invite_id = meta.get("last_invite_from_id")
        last_invite_name = meta.get("last_invite_from_name")
        last_invite_to_id = meta.get("last_invite_to_id")
        last_invite_to_name = meta.get("last_invite_to_name")
        try:
            session_started = float(meta.get("session_started") or 0.0)
        except (TypeError, ValueError):
            session_started = 0.0
        if session_started <= 0:
            session_started = 0.0
        if (
            repel <= 0
            and radiant <= 0
            and not ignore
            and not last_from
            and not last_emote_id
            and not last_emote_from_id
            and not last_share_id
            and not last_share_from_id
            and not last_invite_id
            and not last_invite_to_id
            and session_started <= 0
        ):
            self._soft_grace.pop(character_id, None)
            return
        self._soft_grace[character_id] = {
            "repel_steps": repel,
            "radiant_steps": radiant,
            "ignore": ignore,
            "ignore_names": ignore_names,
            "last_whisper_from_id": last_from,
            "last_whisper_from_name": last_name,
            "last_emote_to_id": last_emote_id,
            "last_emote_to_name": last_emote_name,
            "last_emote_from_id": last_emote_from_id,
            "last_emote_from_name": last_emote_from_name,
            "last_share_to_id": last_share_id,
            "last_share_to_name": last_share_name,
            "last_share_from_id": last_share_from_id,
            "last_share_from_name": last_share_from_name,
            "last_invite_from_id": last_invite_id,
            "last_invite_from_name": last_invite_name,
            "last_invite_to_id": last_invite_to_id,
            "last_invite_to_name": last_invite_to_name,
            # Brief reconnect keeps /played connection age (monotonic stamp)
            "session_started": session_started,
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
                grace_ignore = set(old_meta.get("ignore") or set())
                grace_ignore_names = dict(old_meta.get("ignore_names") or {})
                grace_whisper_id = old_meta.get("last_whisper_from_id")
                grace_whisper_name = old_meta.get("last_whisper_from_name")
                grace_emote_id = old_meta.get("last_emote_to_id")
                grace_emote_name = old_meta.get("last_emote_to_name")
                grace_emote_from_id = old_meta.get("last_emote_from_id")
                grace_emote_from_name = old_meta.get("last_emote_from_name")
                grace_share_id = old_meta.get("last_share_to_id")
                grace_share_name = old_meta.get("last_share_to_name")
                grace_share_from_id = old_meta.get("last_share_from_id")
                grace_share_from_name = old_meta.get("last_share_from_name")
                grace_invite_id = old_meta.get("last_invite_from_id")
                grace_invite_name = old_meta.get("last_invite_from_name")
                grace_invite_to_id = old_meta.get("last_invite_to_id")
                grace_invite_to_name = old_meta.get("last_invite_to_name")
                try:
                    grace_session_started = float(
                        old_meta.get("session_started") or 0.0
                    )
                except (TypeError, ValueError):
                    grace_session_started = 0.0
            else:
                bag = self._take_soft_grace(character_id)
                grace_repel = max(0, int(bag.get("repel_steps") or 0))
                grace_radiant = max(0, int(bag.get("radiant_steps") or 0))
                grace_ignore = set(bag.get("ignore") or set())
                grace_ignore_names = dict(bag.get("ignore_names") or {})
                grace_whisper_id = bag.get("last_whisper_from_id")
                grace_whisper_name = bag.get("last_whisper_from_name")
                grace_emote_id = bag.get("last_emote_to_id")
                grace_emote_name = bag.get("last_emote_to_name")
                grace_emote_from_id = bag.get("last_emote_from_id")
                grace_emote_from_name = bag.get("last_emote_from_name")
                grace_share_id = bag.get("last_share_to_id")
                grace_share_name = bag.get("last_share_to_name")
                grace_share_from_id = bag.get("last_share_from_id")
                grace_share_from_name = bag.get("last_share_from_name")
                grace_invite_id = bag.get("last_invite_from_id")
                grace_invite_name = bag.get("last_invite_from_name")
                grace_invite_to_id = bag.get("last_invite_to_id")
                grace_invite_to_name = bag.get("last_invite_to_name")
                try:
                    grace_session_started = float(bag.get("session_started") or 0.0)
                except (TypeError, ValueError):
                    grace_session_started = 0.0

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
            # Keep /played connection age on live replace OR brief soft-grace rejoin.
            # Fresh connect (no grace) starts a new age. Full leave after grace expires too.
            session_started = now
            if grace_session_started > 0:
                session_started = grace_session_started
            # Soft-grace rejoin (not live replace): flag for auth restored.played / welcome
            soft_restored_session = old_meta is None and grace_session_started > 0
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
                "session_started": session_started,  # monotonic — for /played session age
                "soft_restored_session": soft_restored_session,
                "visible": set(),  # peer ids currently in AOI
                "ignore": grace_ignore,  # cid set — do not receive chat/emotes from these
                "ignore_names": grace_ignore_names,  # tid -> name for offline display
                "last_whisper_from_id": grace_whisper_id,
                "last_whisper_from_name": grace_whisper_name,
                "last_emote_to_id": grace_emote_id,
                "last_emote_to_name": grace_emote_name,
                "last_emote_from_id": grace_emote_from_id,
                "last_emote_from_name": grace_emote_from_name,
                "last_share_to_id": grace_share_id,
                "last_share_to_name": grace_share_name,
                "last_share_from_id": grace_share_from_id,
                "last_share_from_name": grace_share_from_name,
                "last_invite_from_id": grace_invite_id,
                "last_invite_from_name": grace_invite_name,
                "last_invite_to_id": grace_invite_to_id,
                "last_invite_to_name": grace_invite_to_name,
                "afk": False,  # manual /afk — cleared on back / activity
                "afk_since": None,  # monotonic when /afk set (for afk_for peeks)
                "afk_message": None,  # optional status text while AFK
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
        *,
        reason: str = "disconnect",
    ) -> dict[str, Any] | None:
        notify_ids: list[int] = []
        left_meta: dict[str, Any] | None = None
        leave_reason = (reason or "disconnect").strip()[:32] or "disconnect"
        async with self._lock():
            current = self._connections.get(character_id)
            if websocket is not None and current is not None and current is not websocket:
                return None
            self._connections.pop(character_id, None)
            left_meta = self._meta.pop(character_id, None)
            if left_meta:
                self._stash_soft_grace(character_id, left_meta)
                # Union cached AOI with live geometry so a desynced/empty
                # visible set never leaves ghost avatars on nearby clients.
                notify: set[int] = set(left_meta.get("visible") or set())
                try:
                    lx = float(left_meta.get("x") or 0)
                    ly = float(left_meta.get("y") or 0)
                    lmap = left_meta.get("map_id")
                    for oid, om in self._meta.items():
                        if oid not in self._connections:
                            continue
                        if om.get("map_id") != lmap:
                            continue
                        if is_nearby(lx, ly, float(om["x"]), float(om["y"])):
                            notify.add(oid)
                except Exception:
                    pass
                notify_ids = list(notify)
                for oid in notify_ids:
                    om = self._meta.get(oid)
                    if om and "visible" in om:
                        om["visible"].discard(character_id)

        # Notify peers who could see us (or were geometrically nearby)
        if left_meta and notify_ids:
            leave_msg = {
                "type": "player_left",
                "player_id": character_id,
                "name": left_meta.get("name"),
                "reason": leave_reason,
            }
            z = _zone_of(left_meta)
            if z:
                leave_msg["zone"] = z
            # Session at disconnect helps clients drop the right avatar instance
            sid = left_meta.get("session_id")
            if sid is not None:
                leave_msg["session_id"] = sid
            for oid in notify_ids:
                await self.send(oid, leave_msg)
        if left_meta is not None:
            # Force roster pulse on leave — debounced pulse can hide departures
            # under reconnect storms (multiplayer reliability).
            await self.broadcast_online_force()
        return left_meta

    def is_online(self, character_id: int) -> bool:
        return character_id in self._connections

    def owns(self, character_id: int, websocket: WebSocket) -> bool:
        return self._connections.get(character_id) is websocket

    def online_ids(self) -> list[int]:
        return list(self._connections.keys())

    def afk_count(self) -> int:
        """How many live sockets currently have manual /afk set (multiplayer census)."""
        n = 0
        for cid in self._connections:
            meta = self._meta.get(cid)
            if meta and meta.get("afk"):
                n += 1
        return n

    def combat_count(self) -> int:
        """How many live sockets are currently in combat (multiplayer census)."""
        n = 0
        for cid in self._connections:
            meta = self._meta.get(cid)
            if meta and meta.get("in_combat"):
                n += 1
        return n

    def nearby_afk_count(self, character_id: int) -> int:
        """AFK peers currently in geometric AOI (excludes self)."""
        n = 0
        for oid in self.ids_nearby(character_id):
            meta = self._meta.get(oid)
            if meta and meta.get("afk") and oid in self._connections:
                n += 1
        return n

    def zone_afk_count(self, character_id: int, *, include_self: bool = True) -> int:
        """AFK players in the same zone type as character_id."""
        n = 0
        for card in self.zone_roster(character_id, include_self=include_self):
            if card.get("afk"):
                n += 1
        return n

    def nearby_combat_count(self, character_id: int) -> int:
        """Peers currently in combat within geometric AOI (excludes self)."""
        n = 0
        for oid in self.ids_nearby(character_id):
            meta = self._meta.get(oid)
            if meta and meta.get("in_combat") and oid in self._connections:
                n += 1
        return n

    def nearby_combat_roster(self, character_id: int) -> list[dict[str, Any]]:
        """Public cards for AOI peers currently in combat (excludes self)."""
        out: list[dict[str, Any]] = []
        for oid in self.ids_nearby(character_id):
            meta = self._meta.get(oid)
            if not meta or oid not in self._connections:
                continue
            if not meta.get("in_combat"):
                continue
            out.append(_online_card(meta))
        out.sort(
            key=lambda p: (
                str(p.get("name") or "").lower(),
                int(p.get("id") or 0),
            )
        )
        return out

    def zone_combat_count(self, character_id: int, *, include_self: bool = True) -> int:
        """In-combat players in the same zone type as character_id."""
        n = 0
        for card in self.zone_roster(character_id, include_self=include_self):
            if card.get("in_combat"):
                n += 1
        return n

    def online_roster(self) -> list[dict[str, Any]]:
        """All online players as public cards; sorted by name then id for stable UI."""
        out: list[dict[str, Any]] = []
        for cid in self._connections:
            meta = self._meta.get(cid)
            if meta:
                out.append(_online_card(meta))
        out.sort(
            key=lambda p: (
                str(p.get("name") or "").lower(),
                int(p.get("id") or 0),
            )
        )
        return out

    # Coalesce rapid join/leave pulses (reconnect storms), but flush soon.
    ONLINE_PULSE_MIN_INTERVAL = 0.15

    def _online_payload(self) -> dict[str, Any]:
        """Shared body for online pulses (count + roster + zone breakdown)."""
        return {
            "type": "online",
            "online": len(self._connections),
            "afk_count": self.afk_count(),
            "combat_count": self.combat_count(),
            "roster": self.online_roster(),
            "zones": self.zone_counts(),
        }

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
        await self.broadcast(self._online_payload())

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
        await self.broadcast(self._online_payload())

    def purge_expired_soft_grace(self) -> int:
        """Drop expired reconnect soft-state bags. Returns number removed.

        Also clears peer invite pointers that only lived in the expired bag so
        multiplayer meetup state cannot zombie after soft-grace timeout.
        """
        now = time.monotonic()
        dead = [
            cid
            for cid, bag in self._soft_grace.items()
            if now > float(bag.get("expires") or 0.0)
        ]
        for cid in dead:
            bag = self._soft_grace.pop(cid, None) or {}
            # Outgoing invite: guest must not keep last_invite_from this inviter
            try:
                to_id = bag.get("last_invite_to_id")
                if to_id is not None:
                    self.clear_invite_from_peer(int(to_id), cid)
            except (TypeError, ValueError):
                pass
            # Incoming invite: inviter must not keep last_invite_to this guest
            try:
                from_id = bag.get("last_invite_from_id")
                if from_id is not None:
                    self.clear_invite_to_peer(int(from_id), cid)
            except (TypeError, ValueError):
                pass
        return len(dead)

    def get_meta(self, character_id: int) -> dict[str, Any] | None:
        return self._meta.get(character_id)

    def touch(self, character_id: int) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["last_seen"] = time.monotonic()
            # Passive activity (move/ping/who) does not clear manual /afk —
            # only chat/emote/allow_chat or explicit /back.

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
        # Moving is activity — clear soft idle + manual AFK
        meta["last_seen"] = now
        meta["afk"] = False
        meta["afk_since"] = None
        meta["afk_message"] = None
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
        """Case-insensitive exact match against **live** online character names.

        Orphan meta (no socket) must never resolve — whisper/look/ignore would
        target ghosts and desync multiplayer social flows.
        """
        if not name or not isinstance(name, str):
            return None
        key = name.strip().lower()
        if not key:
            return None
        for cid, meta in self._meta.items():
            if cid not in self._connections:
                continue
            if str(meta.get("name") or "").strip().lower() == key:
                return cid
        return None

    def resolve_live_name(self, name: str) -> tuple[int | None, str | None]:
        """Resolve a live player by exact name, else unique prefix (min 2 chars).

        Returns (character_id, error_reason). error_reason is None on success.
        - exact match wins
        - if no exact: unique case-insensitive prefix among live sockets
        - multiple prefix hits → ("name ambiguous",)
        - none → player not online
        """
        if not name or not isinstance(name, str):
            return None, "player not online"
        key = name.strip().lower()
        if not key:
            return None, "player not online"
        exact = self.find_id_by_name(name)
        if exact is not None:
            return exact, None
        # Prefix fallback (require 2+ chars to avoid single-letter spam)
        if len(key) < 2:
            return None, "player not online"
        hits: list[int] = []
        for cid, meta in self._meta.items():
            if cid not in self._connections:
                continue
            n = str(meta.get("name") or "").strip().lower()
            if n.startswith(key):
                hits.append(cid)
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, "name ambiguous"
        return None, "player not online"

    def is_ignored_by(self, listener_id: int, speaker_id: int) -> bool:
        """True if listener has muted/ignored speaker (no chat/emote delivery)."""
        if listener_id == speaker_id:
            return False
        meta = self._meta.get(listener_id)
        if not meta:
            return False
        return int(speaker_id) in set(meta.get("ignore") or set())

    def ignore_player(self, character_id: int, target_id: int) -> tuple[bool, str]:
        meta = self._meta.get(character_id)
        if meta is None:
            return False, "not online"
        tid = int(target_id)
        if tid == character_id:
            return False, "cannot ignore yourself"
        if tid not in self._connections:
            return False, "player not online"
        ig = set(meta.get("ignore") or set())
        if tid in ig:
            return True, "already ignored"
        if len(ig) >= IGNORE_MAX:
            return False, "ignore list full"
        ig.add(tid)
        meta["ignore"] = ig
        # Cache display name so /ignores stays useful if they disconnect
        names = dict(meta.get("ignore_names") or {})
        tmeta = self._meta.get(tid)
        if tmeta and tmeta.get("name"):
            names[tid] = str(tmeta["name"])[:24]
        meta["ignore_names"] = names
        return True, "ignored"

    def unignore_player(self, character_id: int, target_id: int) -> tuple[bool, str]:
        meta = self._meta.get(character_id)
        if meta is None:
            return False, "not online"
        tid = int(target_id)
        ig = set(meta.get("ignore") or set())
        if tid not in ig:
            return True, "not ignored"
        ig.discard(tid)
        meta["ignore"] = ig
        names = dict(meta.get("ignore_names") or {})
        names.pop(tid, None)
        # keys may be str after JSON-ish copies — also drop str form
        names.pop(str(tid), None)
        meta["ignore_names"] = names
        return True, "unignored"

    def ignore_list(self, character_id: int) -> list[dict[str, Any]]:
        """Muted peers for /ignores · auth soft reconnect.

        Online entries match roster cards plus ``online`` / ``nearby`` (AOI vs
        viewer, no coords) so soft reconnect mute lists stay multiplayer-useful.
        Offline entries keep cached names from soft-grace.
        """
        meta = self._meta.get(character_id)
        if not meta:
            return []
        # Lazy import avoids circular handlers ↔ manager load order
        from network.handlers._common import social_peer_card

        names = meta.get("ignore_names") or {}
        out: list[dict[str, Any]] = []
        for tid in sorted(set(meta.get("ignore") or set())):
            tid_i = int(tid)
            om = self._meta.get(tid_i)
            cached = names.get(tid_i) or names.get(str(tid_i))
            if om and tid_i in self._connections:
                entry = _online_card(om)
                entry["online"] = True
                entry["offline"] = False
                peer = social_peer_card(
                    self, tid_i, om.get("name") or cached, viewer_id=character_id
                )
                if peer is not None and "nearby" in peer:
                    entry["nearby"] = bool(peer.get("nearby"))
                out.append(entry)
            else:
                out.append(
                    {
                        "id": tid_i,
                        "name": str(cached or "?")[:24],
                        "level": 0,
                        "in_combat": False,
                        "idle": False,
                        "afk": False,
                        "offline": True,
                        "online": False,
                        "nearby": False,
                    }
                )
        return out

    def note_whisper_from(self, listener_id: int, speaker_id: int, speaker_name: str | None = None) -> None:
        """Remember last whisper peer for server-side /r reply after reconnect."""
        meta = self._meta.get(listener_id)
        if meta is None:
            return
        meta["last_whisper_from_id"] = int(speaker_id)
        if speaker_name:
            meta["last_whisper_from_name"] = str(speaker_name)[:24]

    def last_whisper_from(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_whisper_from_id")
        name = meta.get("last_whisper_from_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def note_emote_to(
        self, speaker_id: int, target_id: int, target_name: str | None = None
    ) -> None:
        """Remember last directed-emote target for /wave @last after reconnect."""
        meta = self._meta.get(speaker_id)
        if meta is None:
            return
        meta["last_emote_to_id"] = int(target_id)
        if target_name:
            meta["last_emote_to_name"] = str(target_name)[:24]

    def last_emote_to(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_emote_to_id")
        name = meta.get("last_emote_to_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def note_emote_from(
        self, listener_id: int, speaker_id: int, speaker_name: str | None = None
    ) -> None:
        """Remember who last directed an emote at you (soft reconnect)."""
        meta = self._meta.get(listener_id)
        if meta is None:
            return
        meta["last_emote_from_id"] = int(speaker_id)
        if speaker_name:
            meta["last_emote_from_name"] = str(speaker_name)[:24]

    def last_emote_from(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_emote_from_id")
        name = meta.get("last_emote_from_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def note_share_to(
        self, speaker_id: int, target_id: int, target_name: str | None = None
    ) -> None:
        """Remember last location-share target for /lastshare after reconnect."""
        meta = self._meta.get(speaker_id)
        if meta is None:
            return
        meta["last_share_to_id"] = int(target_id)
        if target_name:
            meta["last_share_to_name"] = str(target_name)[:24]

    def last_share_to(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_share_to_id")
        name = meta.get("last_share_to_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def note_share_from(
        self, listener_id: int, sharer_id: int, sharer_name: str | None = None
    ) -> None:
        """Remember who last shared location with you (soft reconnect)."""
        meta = self._meta.get(listener_id)
        if meta is None:
            return
        meta["last_share_from_id"] = int(sharer_id)
        if sharer_name:
            meta["last_share_from_name"] = str(sharer_name)[:24]

    def last_share_from(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_share_from_id")
        name = meta.get("last_share_from_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def note_invite_from(
        self, listener_id: int, inviter_id: int, inviter_name: str | None = None
    ) -> int | None:
        """Remember last meetup inviter for /accept · /lastinvite after reconnect.

        If the guest already had a pending invite from someone else, clear that
        previous inviter's last_invite_to so they do not keep a zombie outgoing
        pointer after a newer invite overwrites theirs.

        Returns the previous inviter id when superseded (for multiplayer notify).
        """
        meta = self._meta.get(listener_id)
        if meta is None:
            return None
        try:
            new_id = int(inviter_id)
        except (TypeError, ValueError):
            return None
        old_from = meta.get("last_invite_from_id")
        try:
            old_i = int(old_from) if old_from is not None else None
        except (TypeError, ValueError):
            old_i = None
        superseded: int | None = None
        if old_i is not None and old_i != new_id:
            # Previous inviter no longer has a live pending invite to this guest
            self.clear_invite_to_peer(old_i, listener_id)
            superseded = old_i
        meta["last_invite_from_id"] = new_id
        if inviter_name:
            meta["last_invite_from_name"] = str(inviter_name)[:24]
        return superseded

    def last_invite_from(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_invite_from_id")
        name = meta.get("last_invite_from_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def clear_last_invite(self, character_id: int) -> None:
        """Drop pending meetup invite after accept/decline (prevents spam replies)."""
        meta = self._meta.get(character_id)
        if meta is None:
            return
        meta["last_invite_from_id"] = None
        meta["last_invite_from_name"] = None

    @staticmethod
    def _ids_equal(a: Any, b: Any) -> bool:
        try:
            return a is not None and b is not None and int(a) == int(b)
        except (TypeError, ValueError):
            return False

    def clear_invite_from_peer(self, guest_id: int, inviter_id: int) -> bool:
        """Clear guest's last_invite_from if it points at inviter (live + soft-grace).

        Needed when inviter /cancel's while guest is offline — otherwise soft-grace
        restores a zombie invite on guest reconnect.
        """
        cleared = False
        meta = self._meta.get(guest_id)
        if meta is not None and self._ids_equal(meta.get("last_invite_from_id"), inviter_id):
            meta["last_invite_from_id"] = None
            meta["last_invite_from_name"] = None
            cleared = True
        bag = self._soft_grace.get(guest_id)
        if bag is not None and self._ids_equal(bag.get("last_invite_from_id"), inviter_id):
            bag["last_invite_from_id"] = None
            bag["last_invite_from_name"] = None
            cleared = True
        return cleared

    def clear_invite_to_peer(self, inviter_id: int, guest_id: int) -> bool:
        """Clear inviter's last_invite_to if it points at guest (live + soft-grace).

        Needed when guest answers while inviter is offline — otherwise soft-grace
        restores a zombie outgoing invite on inviter reconnect.
        """
        cleared = False
        meta = self._meta.get(inviter_id)
        if meta is not None and self._ids_equal(meta.get("last_invite_to_id"), guest_id):
            meta["last_invite_to_id"] = None
            meta["last_invite_to_name"] = None
            cleared = True
        bag = self._soft_grace.get(inviter_id)
        if bag is not None and self._ids_equal(bag.get("last_invite_to_id"), guest_id):
            bag["last_invite_to_id"] = None
            bag["last_invite_to_name"] = None
            cleared = True
        return cleared

    def note_invite_to(
        self, inviter_id: int, target_id: int, target_name: str | None = None
    ) -> int | None:
        """Remember last invite target so inviter can /cancel.

        If the inviter already had a pending invite to someone else, clear that
        previous guest's last_invite_from when it still points at this inviter
        (re-invite without cancel must not leave a zombie on the old guest).

        Returns the previous target id when retargeted (for multiplayer notify).
        """
        meta = self._meta.get(inviter_id)
        if meta is None:
            return None
        try:
            new_tid = int(target_id)
        except (TypeError, ValueError):
            return None
        old_to = meta.get("last_invite_to_id")
        try:
            old_t = int(old_to) if old_to is not None else None
        except (TypeError, ValueError):
            old_t = None
        retargeted: int | None = None
        if old_t is not None and old_t != new_tid:
            self.clear_invite_from_peer(old_t, inviter_id)
            retargeted = old_t
        meta["last_invite_to_id"] = new_tid
        if target_name:
            meta["last_invite_to_name"] = str(target_name)[:24]
        return retargeted

    def last_invite_to(self, character_id: int) -> tuple[int | None, str | None]:
        meta = self._meta.get(character_id)
        if meta is None:
            return None, None
        lid = meta.get("last_invite_to_id")
        name = meta.get("last_invite_to_name")
        try:
            lid_i = int(lid) if lid is not None else None
        except (TypeError, ValueError):
            lid_i = None
        return lid_i, str(name) if name else None

    def clear_last_invite_to(self, character_id: int) -> None:
        meta = self._meta.get(character_id)
        if meta is None:
            return
        meta["last_invite_to_id"] = None
        meta["last_invite_to_name"] = None

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
        # Chatting is activity (same as move) for idle/AFK badges
        meta["last_seen"] = now
        meta["afk"] = False
        meta["afk_since"] = None
        meta["afk_message"] = None
        return True, 0.0

    def set_afk(
        self,
        character_id: int,
        afk: bool,
        message: str | None = None,
    ) -> bool:
        """Toggle manual AFK flag (+ optional status message). Returns False if not online.

        message is applied when afk=True (None → clear reason; string → set/sanitize).
        When afk=False, message is always cleared.
        """
        meta = self._meta.get(character_id)
        if meta is None:
            return False
        now = time.monotonic()
        was = bool(meta.get("afk"))
        meta["afk"] = bool(afk)
        if afk:
            # Keep original afk_since when only updating the status message
            if not was or meta.get("afk_since") is None:
                meta["afk_since"] = now
            if message is None:
                meta["afk_message"] = None
            else:
                meta["afk_message"] = sanitize_afk_message(message)
        else:
            meta["afk_since"] = None
            meta["afk_message"] = None
            meta["last_seen"] = now
        return True

    def mark_active(self, character_id: int) -> bool:
        """Clear AFK/idle stamps after real multiplayer activity (shop, use, equip).

        Returns True if the player *was* AFK (so callers can publish_status).
        Does not publish status — caller should publish when peers need a badge refresh.
        """
        meta = self._meta.get(character_id)
        if meta is None:
            return False
        now = time.monotonic()
        meta["last_seen"] = now
        was_afk = bool(meta.get("afk"))
        meta["afk"] = False
        meta["afk_since"] = None
        meta["afk_message"] = None
        return was_afk

    def refund_chat(
        self,
        character_id: int,
        *,
        restore_afk: bool = False,
        afk_message: str | None = None,
    ) -> None:
        """Undo the last allow_chat stamp (failed whisper delivery, etc.).

        Lets the next legitimate chat succeed without waiting out the interval
        after a multiplayer send race (target socket died mid-deliver).

        When allow_chat cleared manual AFK before a failed send, pass
        restore_afk=True so peers still see an honest AFK badge.
        """
        meta = self._meta.get(character_id)
        if meta is None:
            return
        meta["last_chat_at"] = 0.0
        if restore_afk:
            was = bool(meta.get("afk"))
            meta["afk"] = True
            if not was or meta.get("afk_since") is None:
                meta["afk_since"] = time.monotonic()
            if isinstance(afk_message, str) and afk_message.strip():
                meta["afk_message"] = sanitize_afk_message(afk_message)
            else:
                meta["afk_message"] = None

    async def publish_status(self, character_id: int, *, pulse_online: bool = False) -> None:
        """Broadcast current public status (level, combat) to AOI peers.

        Uses geometric AOI ∪ cached visible so combat/level flags still reach
        peers after brief AOI desync. When pulse_online is True (combat
        enter/leave), also refresh global roster cards.
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
            "idle": _is_idle(me),
            "afk": bool(me.get("afk")),
        }
        z = _zone_of(me)
        if z:
            payload["zone"] = z
        sid = me.get("session_id")
        if sid is not None:
            payload["session_id"] = sid
        if payload["afk"]:
            am = me.get("afk_message")
            if isinstance(am, str) and am.strip():
                payload["afk_message"] = am.strip()[:48]
            try:
                since = float(me.get("afk_since") or 0.0)
                if since > 0:
                    payload["afk_for"] = max(0, int(time.monotonic() - since))
            except (TypeError, ValueError):
                pass
        targets = set(self.ids_nearby(character_id)) | set(me.get("visible") or set())
        # Only live sockets (cached visible can hold ghosts briefly)
        targets = {oid for oid in targets if oid in self._connections}
        for oid in targets:
            if oid == character_id:
                continue
            await self.send(oid, payload)
        if pulse_online:
            await self.broadcast_online()

    def _finite_xy(self, meta: dict[str, Any]) -> tuple[float, float] | None:
        """Return finite (x,y) or None; repair meta to spawn if corrupted."""
        from game.world_manager import SPAWN_X, SPAWN_Y

        try:
            x, y = float(meta["x"]), float(meta["y"])
            if math.isfinite(x) and math.isfinite(y):
                return x, y
        except (TypeError, ValueError, KeyError):
            pass
        meta["x"] = float(SPAWN_X)
        meta["y"] = float(SPAWN_Y)
        meta["dirty"] = True
        return float(SPAWN_X), float(SPAWN_Y)

    def ids_nearby(self, character_id: int) -> list[int]:
        me = self._meta.get(character_id)
        if me is None:
            return []
        me_xy = self._finite_xy(me)
        if me_xy is None:
            return []
        mx, my = me_xy
        out: list[int] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            # Only live sockets — never treat orphan meta as nearby
            if cid not in self._connections:
                continue
            if meta["map_id"] != me["map_id"]:
                continue
            other_xy = self._finite_xy(meta)
            if other_xy is None:
                continue
            ox, oy = other_xy
            if is_nearby(mx, my, ox, oy):
                out.append(cid)
        return out

    def zone_counts(self) -> dict[str, int]:
        """How many online players are in each walkable zone (social overview)."""
        from game.world_manager import zone_at

        counts = {"town": 0, "field": 0, "dungeon": 0}
        for cid in self._connections:
            meta = self._meta.get(cid)
            if not meta:
                continue
            xy = self._finite_xy(meta)
            if xy is None:
                continue
            try:
                z = zone_at(int(xy[0]), int(xy[1]))
            except Exception:
                continue
            if z in counts:
                counts[z] += 1
        return counts

    def nearby_players(self, character_id: int) -> list[dict[str, Any]]:
        out = []
        for cid in self.ids_nearby(character_id):
            meta = self._meta.get(cid)
            if meta:
                out.append(_public_meta(meta))
        return out

    def set_position(self, character_id: int, x: float, y: float, *, seq: int | None = None) -> None:
        meta = self._meta.get(character_id)
        if meta is None:
            return
        try:
            fx, fy = float(x), float(y)
            if not math.isfinite(fx) or not math.isfinite(fy):
                return
        except (TypeError, ValueError):
            return
        meta["x"] = fx
        meta["y"] = fy
        meta["dirty"] = True
        if seq is not None:
            try:
                meta["last_move_seq"] = int(seq)
            except (TypeError, ValueError, OverflowError):
                pass

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

        Meta mutation runs under the per-loop lock so concurrent movers
        cannot corrupt visible sets; network sends happen after release
        (send→disconnect also needs the lock).
        """
        join_peer: list[tuple[int, dict[str, Any]]] = []
        leave_peer: list[tuple[int, str | None]] = []
        stay_ids: list[int] = []
        me_pub: dict[str, Any] | None = None
        to_self: list[dict[str, Any]] = []

        async with self._lock():
            me = self._meta.get(character_id)
            if me is None:
                return []

            try:
                nx, ny = float(x), float(y)
                if not math.isfinite(nx) or not math.isfinite(ny):
                    return []
            except (TypeError, ValueError):
                return []

            old_visible: set[int] = set(me.get("visible") or set())
            me["x"] = nx
            me["y"] = ny
            me["dirty"] = True
            if seq is not None:
                try:
                    me["last_move_seq"] = int(seq)
                except (TypeError, ValueError, OverflowError):
                    pass

            new_visible = set(self.ids_nearby(character_id))
            entered = new_visible - old_visible
            left = old_visible - new_visible
            stayed = old_visible & new_visible
            me["visible"] = new_visible
            me_pub = _public_meta(me)

            for oid in entered:
                other = self._meta.get(oid)
                if not other:
                    continue
                other.setdefault("visible", set()).add(character_id)
                other_pub = _public_meta(other)
                join_peer.append((oid, other_pub))
                join_self = {
                    "type": "player_joined",
                    "player_id": other_pub["id"],
                    "name": other_pub["name"],
                    "x": other_pub["x"],
                    "y": other_pub["y"],
                    "level": other_pub["level"],
                    "in_combat": other_pub["in_combat"],
                    "idle": bool(other_pub.get("idle")),
                    "afk": bool(other_pub.get("afk")),
                }
                if other_pub.get("zone"):
                    join_self["zone"] = other_pub["zone"]
                # Peer's live session so client can reconcile reconnects
                osid = other.get("session_id")
                if osid is not None:
                    join_self["session_id"] = osid
                to_self.append(join_self)

            for oid in left:
                other = self._meta.get(oid)
                name = (other or {}).get("name")
                if other is not None:
                    other.setdefault("visible", set()).discard(character_id)
                leave_peer.append((oid, name if isinstance(name, str) else None))
                leave_self = {
                    "type": "player_left",
                    "player_id": oid,
                    "name": name,
                    "reason": "out_of_range",
                }
                if other is not None:
                    oz = _zone_of(other)
                    if oz:
                        leave_self["zone"] = oz
                    osid = other.get("session_id")
                    if osid is not None:
                        leave_self["session_id"] = osid
                to_self.append(leave_self)

            stay_ids = list(stayed)

        assert me_pub is not None
        me_sid = None
        me_live = self._meta.get(character_id)
        if me_live is not None:
            me_sid = me_live.get("session_id")
        join_them = {
            "type": "player_joined",
            "player_id": character_id,
            "name": me_pub["name"],
            "x": me_pub["x"],
            "y": me_pub["y"],
            "level": me_pub["level"],
            "in_combat": me_pub["in_combat"],
            "idle": bool(me_pub.get("idle")),
            "afk": bool(me_pub.get("afk")),
        }
        if me_pub.get("zone"):
            join_them["zone"] = me_pub["zone"]
        if me_sid is not None:
            join_them["session_id"] = me_sid
        for oid, _other_pub in join_peer:
            await self.send(oid, join_them)

        leave_them = {
            "type": "player_left",
            "player_id": character_id,
            "name": me_pub["name"],
            "reason": "out_of_range",
        }
        if me_pub.get("zone"):
            leave_them["zone"] = me_pub["zone"]
        if me_sid is not None:
            leave_them["session_id"] = me_sid
        for oid, name in leave_peer:
            await self.send(oid, leave_them)

        move_msg = {
            "type": "player_moved",
            "player_id": character_id,
            "x": me_pub["x"],
            "y": me_pub["y"],
            "seq": seq,
            "name": me_pub["name"],
            "level": me_pub["level"],
            "in_combat": me_pub["in_combat"],
            "idle": bool(me_pub.get("idle")),
            "afk": bool(me_pub.get("afk")),
        }
        if me_pub.get("zone"):
            move_msg["zone"] = me_pub["zone"]
        if me_sid is not None:
            move_msg["session_id"] = me_sid
        for oid in stay_ids:
            await self.send(oid, move_msg)

        return to_self

    def find_by_prefix(
        self,
        prefix: str,
        *,
        limit: int = 20,
        zone: str | None = None,
        afk: bool | None = None,
        idle: bool | None = None,
        combat: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Case-insensitive name prefix search over online roster (no coordinates).

        Optional zone filter: town | field | dungeon (never returns x/y).
        Optional afk filter: True = only AFK, False = only not-AFK, None = all.
        Optional idle filter: True = only idle (soft or AFK), False = active only.
        Optional combat filter: True = only in combat, False = not fighting.
        Empty prefix + zone/afk/idle/combat lists matching online heroes.
        """
        key = ""
        if isinstance(prefix, str):
            key = prefix.strip().lower()
        if len(key) > 24:
            return []
        zone_key = None
        if isinstance(zone, str) and zone.strip():
            z = zone.strip().lower()
            if z in ("town", "field", "dungeon"):
                zone_key = z
            else:
                # Invalid zone → no hits (caller may surface error)
                return []
        # Need a name prefix and/or a valid zone/afk/idle/combat filter
        if (
            not key
            and zone_key is None
            and afk is None
            and idle is None
            and combat is None
        ):
            return []
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 20
        # 0 must not fall through as "default 20" (bool(0) is False)
        if lim < 1:
            lim = 1
        if lim > 50:
            lim = 50
        hits: list[dict[str, Any]] = []
        for cid, meta in self._meta.items():
            if cid not in self._connections:
                continue
            name = str(meta.get("name") or "")
            if key and not name.lower().startswith(key):
                continue
            card = _online_card(meta)
            if zone_key and card.get("zone") != zone_key:
                continue
            if afk is not None and bool(card.get("afk")) is not bool(afk):
                continue
            if idle is not None and bool(card.get("idle")) is not bool(idle):
                continue
            if combat is not None and bool(card.get("in_combat")) is not bool(combat):
                continue
            hits.append(card)
        hits.sort(
            key=lambda p: (
                str(p.get("name") or "").lower(),
                int(p.get("id") or 0),
            )
        )
        return hits[:lim]

    async def publish_level(self, character_id: int, level: int) -> None:
        me = self._meta.get(character_id)
        if me is None:
            return
        me["level"] = int(level)
        name = str(me.get("name") or "Hero")
        # Pulse roster so other clients see the new level without a who refresh
        await self.publish_status(character_id, pulse_online=True)
        # Nearby system chat — multiplayer celebration without global spam
        await self.broadcast_nearby(
            character_id,
            {
                "type": "chat",
                "player_id": character_id,
                "name": "System",
                "text": f"{name} reached level {int(level)}!",
                "channel": "system",
                "system": True,
            },
            include_self=True,
        )

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
        await self.broadcast(self._online_payload())

    def prune_stale_visible(self) -> int:
        """Drop offline / out-of-range peer ids from every visible set.

        Silent repair for AOI cache drift (no network). Returns entries removed.
        """
        removed = 0
        for cid, meta in list(self._meta.items()):
            if cid not in self._connections:
                continue
            vis = set(meta.get("visible") or set())
            if not vis:
                continue
            clean: set[int] = set()
            try:
                mx = float(meta["x"])
                my = float(meta["y"])
                mmap = meta.get("map_id")
            except Exception:
                meta["visible"] = set()
                removed += len(vis)
                continue
            for oid in vis:
                om = self._meta.get(oid)
                if om is None or oid not in self._connections:
                    removed += 1
                    continue
                if om.get("map_id") != mmap:
                    removed += 1
                    continue
                try:
                    if not is_nearby(mx, my, float(om["x"]), float(om["y"])):
                        removed += 1
                        continue
                except Exception:
                    removed += 1
                    continue
                clean.add(oid)
            if clean != vis:
                meta["visible"] = clean
        return removed

    async def reconcile_all_aoi(self) -> int:
        """Rebuild AOI for every online player (joins/leaves as needed).

        Used periodically so desynced clients re-link without a manual sync.
        Returns number of players reconciled.
        """
        n = 0
        for cid in list(self._connections.keys()):
            try:
                await self.rebuild_aoi(cid)
                n += 1
            except Exception:
                continue
        return n

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

    async def broadcast(
        self,
        message: dict[str, Any],
        exclude: int | None = None,
        *,
        from_id: int | None = None,
        respect_ignore: bool = False,
    ) -> None:
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid, ws in list(self._connections.items()):
            if exclude is not None and cid == exclude:
                continue
            if (
                respect_ignore
                and from_id is not None
                and self.is_ignored_by(cid, from_id)
            ):
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
        respect_ignore: bool = True,
    ) -> None:
        """Send to geometric AOI peers (union with cached visible for safety).

        Prefer live geometry over the cached visible set so stale/partial AOI
        never drops nearby chat, emotes, or social traffic.
        When respect_ignore is True, skip listeners who ignored source_id.
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
            if respect_ignore and cid != source_id and self.is_ignored_by(cid, source_id):
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
        """Live sockets on the same map whose tile zone matches the source."""
        from game.world_manager import zone_at

        me = self._meta.get(character_id)
        if me is None:
            return []
        me_xy = self._finite_xy(me)
        if me_xy is None:
            return []
        try:
            my_zone = zone_at(int(me_xy[0]), int(me_xy[1]))
        except Exception:
            return []
        if my_zone not in ("town", "field", "dungeon"):
            return []
        out: list[int] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            # Only live sockets — orphan meta must never get zone chat
            if cid not in self._connections:
                continue
            if meta.get("map_id") != me.get("map_id"):
                continue
            other_xy = self._finite_xy(meta)
            if other_xy is None:
                continue
            try:
                z = zone_at(int(other_xy[0]), int(other_xy[1]))
            except Exception:
                continue
            if z == my_zone:
                out.append(cid)
        return out

    def zone_roster(
        self, character_id: int, *, include_self: bool = True
    ) -> list[dict[str, Any]]:
        """Public cards for live players in the same zone (no x/y)."""
        me = self._meta.get(character_id)
        if me is None:
            return []
        ids = list(self.ids_in_zone(character_id))
        if include_self and character_id in self._connections:
            ids.append(character_id)
        cards: list[dict[str, Any]] = []
        for cid in ids:
            meta = self._meta.get(cid)
            if meta and cid in self._connections:
                cards.append(_online_card(meta))
        cards.sort(
            key=lambda p: (
                str(p.get("name") or "").lower(),
                int(p.get("id") or 0),
            )
        )
        return cards

    async def broadcast_zone(
        self,
        source_id: int,
        message: dict[str, Any],
        *,
        include_self: bool = True,
        respect_ignore: bool = True,
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
            if respect_ignore and cid != source_id and self.is_ignored_by(cid, source_id):
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
        """Resolve online character id from int/str player_id.

        Rejects bool (True→1 trap) and non-integer floats (1.7→1 trap).
        Accepts ints, integer floats (1.0), and digit strings.
        """
        pid = coerce_character_id(player_id)
        if pid is None:
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
