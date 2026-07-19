import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from config import DATABASE_URL

_db: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


@asynccontextmanager
async def db_write():
    """Serialize SQLite writers (WAL still benefits from single-writer discipline)."""
    async with _write_lock:
        db = await get_db()
        yield db


async def init_db() -> aiosqlite.Connection:
    global _db
    Path(DATABASE_URL).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(DATABASE_URL)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute("PRAGMA busy_timeout=5000")
    from database.migrations import run_migrations

    await run_migrations(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
