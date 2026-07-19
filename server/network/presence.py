"""Background tasks: flush positions, drop idle sockets."""

from __future__ import annotations

import asyncio
import logging

from database.db import db_write
from network.protocol import ServerMessageType, msg
from network.websocket_manager import HEARTBEAT_CHECK_INTERVAL, manager

log = logging.getLogger("dq1.presence")

_task: asyncio.Task | None = None
FLUSH_INTERVAL = 3.0


async def flush_dirty_positions() -> int:
    dirty = manager.dirty_positions()
    if not dirty:
        return 0
    async with db_write() as db:
        for cid, x, y in dirty:
            await db.execute(
                "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (x, y, cid),
            )
            manager.mark_clean(cid)
        await db.commit()
    return len(dirty)


async def kick_idle() -> int:
    from game.combat_engine import combat_engine
    from network.message_handler import handle_disconnect

    n = 0
    for cid in manager.stale_ids():
        meta = manager.get_meta(cid)
        ws = None
        # close socket if present
        try:
            # disconnect handles meta removal
            if combat_engine.is_in_combat(cid):
                await handle_disconnect(cid)
            # flush position first
            if meta:
                async with db_write() as db:
                    await db.execute(
                        "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (meta["x"], meta["y"], cid),
                    )
                    await db.commit()
            left = await manager.disconnect(cid)
            if left is not None:
                await manager.broadcast(msg(ServerMessageType.PLAYER_LEFT, player_id=cid))
                n += 1
        except Exception as exc:
            log.warning("idle kick failed for %s: %s", cid, exc)
    return n


async def _loop() -> None:
    ticks = 0
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)
            ticks += 1
            flushed = await flush_dirty_positions()
            if flushed:
                log.debug("flushed %s positions", flushed)
            # idle check less often
            if ticks % max(1, int(HEARTBEAT_CHECK_INTERVAL // FLUSH_INTERVAL)) == 0:
                kicked = await kick_idle()
                if kicked:
                    log.info("kicked %s idle connections", kicked)
        except asyncio.CancelledError:
            # final flush
            try:
                await flush_dirty_positions()
            except Exception:
                pass
            raise
        except Exception as exc:
            log.exception("presence loop error: %s", exc)


def start_presence_tasks() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="dq1-presence")


async def stop_presence_tasks() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    await flush_dirty_positions()
