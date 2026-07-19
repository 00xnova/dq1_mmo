"""Equipment / inventory — Phase 5."""

from database.db import get_db

VALID_SLOTS = ("weapon", "armor", "shield", "helmet")


async def list_items(character_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, item_id, quantity, is_equipped FROM item_instances WHERE character_id = ?",
        (character_id,),
    ) as c:
        rows = await c.fetchall()
    return [
        {
            "id": r["id"],
            "item_id": r["item_id"],
            "quantity": r["quantity"],
            "is_equipped": bool(r["is_equipped"]),
        }
        for r in rows
    ]
