"""Background tasks: flush positions, drop idle sockets."""

from __future__ import annotations

import asyncio
import logging

from database.db import db_write
from network.websocket_manager import HEARTBEAT_CHECK_INTERVAL, manager

log = logging.getLogger("dq1.presence")

_task: asyncio.Task | None = None
_task_loop: asyncio.AbstractEventLoop | None = None
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
        try:
            if combat_engine.is_in_combat(cid):
                await handle_disconnect(cid)
            if meta:
                async with db_write() as db:
                    await db.execute(
                        "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (meta["x"], meta["y"], cid),
                    )
                    await db.commit()
            # disconnect() already notifies AOI peers with player_left — no global double-send
            left = await manager.disconnect(cid, reason="idle")
            if left is not None:
                n += 1
        except Exception as exc:
            log.warning("idle kick failed for %s: %s", cid, exc)
    return n


async def expire_combats() -> int:
    from game.combat_engine import combat_engine
    from network.message_handler import expire_combat_grace

    n = 0
    for cid in combat_engine.expired_grace():
        try:
            await expire_combat_grace(cid)
            n += 1
        except Exception as exc:
            log.warning("combat grace expire failed for %s: %s", cid, exc)
    return n


# Full AOI rebuild cadence (~30s at FLUSH_INTERVAL=3)
AOI_RECONCILE_EVERY_TICKS = 10


async def _loop() -> None:
    ticks = 0
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)
            ticks += 1
            flushed = await flush_dirty_positions()
            if flushed:
                log.debug("flushed %s positions", flushed)
            expired = await expire_combats()
            if expired:
                log.info("expired %s orphaned combats", expired)
            try:
                await manager.flush_online_pulse()
            except Exception:
                pass
            try:
                purged = manager.purge_expired_soft_grace()
                if purged:
                    log.debug("purged %s soft-grace bags", purged)
            except Exception:
                pass
            # Cheap AOI cache hygiene every tick
            try:
                pruned = manager.prune_stale_visible()
                if pruned:
                    log.debug("pruned %s stale AOI links", pruned)
            except Exception:
                pass
            if ticks % max(1, int(HEARTBEAT_CHECK_INTERVAL // FLUSH_INTERVAL)) == 0:
                kicked = await kick_idle()
                if kicked:
                    log.info("kicked %s idle connections", kicked)
                # Periodic roster refresh so late clients stay consistent
                try:
                    if manager.online_ids():
                        await manager.broadcast_online_force()
                except Exception:
                    log.debug("periodic online pulse failed", exc_info=True)
            # Deeper AOI rebuild (~30s) — re-link peers after desync storms
            if ticks % AOI_RECONCILE_EVERY_TICKS == 0 and manager.online_ids():
                try:
                    n = await manager.reconcile_all_aoi()
                    if n:
                        log.debug("reconciled AOI for %s players", n)
                except Exception:
                    log.debug("AOI reconcile failed", exc_info=True)
        except asyncio.CancelledError:
            try:
                await flush_dirty_positions()
            except Exception:
                pass
            raise
        except Exception as exc:
            log.exception("presence loop error: %s", exc)


def start_presence_tasks() -> None:
    """Start presence loop on the *current* event loop (safe across test restarts)."""
    global _task, _task_loop
    loop = asyncio.get_running_loop()
    # Abandon any task from a previous loop without awaiting it (wrong-loop crash).
    if _task is not None and _task_loop is not loop:
        try:
            if not _task.done():
                _task_loop.call_soon_threadsafe(_task.cancel) if _task_loop and _task_loop.is_running() else None
        except Exception:
            pass
        _task = None
        _task_loop = None
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="dq1-presence")
        _task_loop = loop


async def stop_presence_tasks() -> None:
    global _task, _task_loop
    task = _task
    task_loop = _task_loop
    _task = None
    _task_loop = None
    if task is not None:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if task_loop is not None and current is not None and task_loop is not current:
            # Task belongs to another (dead) loop — do not await.
            try:
                if not task.done() and task_loop.is_running():
                    task_loop.call_soon_threadsafe(task.cancel)
            except Exception:
                pass
        else:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
    try:
        await flush_dirty_positions()
    except Exception:
        pass
