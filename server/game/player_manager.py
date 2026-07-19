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


async def apply_character_patch(character_id: int, patch: dict) -> dict | None:
    db = await get_db()
    fields = []
    values = []
    allowed = {
        "level",
        "experience",
        "strength",
        "agility",
        "max_hp",
        "max_mp",
        "current_hp",
        "current_mp",
        "gold",
        "total_kills",
        "world_x",
        "world_y",
        "map_id",
    }
    for k, v in patch.items():
        if k in allowed:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        return await get_character(character_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(character_id)
    await db.execute(
        f"UPDATE characters SET {', '.join(fields)} WHERE id = ?",
        tuple(values),
    )
    await db.commit()
    return await get_character(character_id)
