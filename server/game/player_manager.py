from database.db import get_db


async def get_character(character_id: int) -> dict | None:
    db = await get_db()
    async with db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)) as c:
        row = await c.fetchone()
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


async def save_position(character_id: int, x: float, y: float) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (x, y, character_id),
    )
    await db.commit()
