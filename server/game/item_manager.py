"""Equipment / inventory / shop."""

from __future__ import annotations

from game.data_loader import load_data
from game.formulas import hero_attack_power, hero_defense_power

VALID_SLOTS = ("weapon", "armor", "shield", "helmet")
SLOT_COLUMNS = {
    "weapon": "equipment_weapon",
    "armor": "equipment_armor",
    "shield": "equipment_shield",
    "helmet": "equipment_helmet",
}


def get_equipment_def(item_id: str | None) -> dict | None:
    if not item_id:
        return None
    return load_data().get("equipment", {}).get(item_id)


def get_item_def(item_id: str) -> dict | None:
    data = load_data()
    return data.get("equipment", {}).get(item_id) or data.get("consumables", {}).get(item_id)


def shop_catalog() -> list[dict]:
    data = load_data()
    out = []
    for iid in data.get("shop", []):
        d = get_item_def(iid)
        if d and int(d.get("price", 0)) > 0:
            out.append(dict(d))
    return out


def equipment_bonuses(character: dict) -> dict:
    weapon = get_equipment_def(character.get("equipment_weapon"))
    armor = get_equipment_def(character.get("equipment_armor"))
    shield = get_equipment_def(character.get("equipment_shield"))
    helm = get_equipment_def(character.get("equipment_helmet"))
    weapon_power = int((weapon or {}).get("attack", 0))
    armor_power = int((armor or {}).get("defense", 0))
    shield_power = int((shield or {}).get("defense", 0))
    accessory_power = int((helm or {}).get("defense", 0))
    strength = int(character.get("strength", 4))
    agility = int(character.get("agility", 4))
    return {
        "weapon_power": weapon_power,
        "armor_power": armor_power,
        "shield_power": shield_power,
        "accessory_power": accessory_power,
        "attack_power": hero_attack_power(strength, weapon_power),
        "defense_power": hero_defense_power(agility, armor_power, shield_power, accessory_power),
        "equipment": {
            "weapon": character.get("equipment_weapon"),
            "armor": character.get("equipment_armor"),
            "shield": character.get("equipment_shield"),
            "helmet": character.get("equipment_helmet"),
        },
    }


async def list_items(db, character_id: int) -> list[dict]:
    async with db.execute(
        "SELECT id, item_id, quantity, is_equipped FROM item_instances WHERE character_id = ? AND is_equipped = 0",
        (character_id,),
    ) as c:
        rows = await c.fetchall()
    return [
        {
            "id": r["id"],
            "item_id": r["item_id"],
            "quantity": r["quantity"],
            "is_equipped": False,
            "def": get_item_def(r["item_id"]),
        }
        for r in rows
    ]


async def add_item(db, character_id: int, item_id: str, quantity: int = 1) -> None:
    async with db.execute(
        "SELECT id, quantity FROM item_instances WHERE character_id = ? AND item_id = ? AND is_equipped = 0",
        (character_id, item_id),
    ) as c:
        row = await c.fetchone()
    if row:
        await db.execute(
            "UPDATE item_instances SET quantity = ? WHERE id = ?",
            (int(row["quantity"]) + quantity, row["id"]),
        )
    else:
        await db.execute(
            "INSERT INTO item_instances (character_id, item_id, quantity, is_equipped) VALUES (?, ?, ?, 0)",
            (character_id, item_id, quantity),
        )


async def remove_item(db, character_id: int, item_id: str, quantity: int = 1) -> bool:
    async with db.execute(
        "SELECT id, quantity FROM item_instances WHERE character_id = ? AND item_id = ? AND is_equipped = 0 ORDER BY id LIMIT 1",
        (character_id, item_id),
    ) as c:
        row = await c.fetchone()
    if row is None or int(row["quantity"]) < quantity:
        return False
    left = int(row["quantity"]) - quantity
    if left <= 0:
        await db.execute("DELETE FROM item_instances WHERE id = ?", (row["id"],))
    else:
        await db.execute("UPDATE item_instances SET quantity = ? WHERE id = ?", (left, row["id"]))
    return True


async def equip_item(db, character: dict, slot: str, item_id: str) -> tuple[bool, str]:
    if slot not in VALID_SLOTS:
        return False, "invalid slot"
    defn = get_equipment_def(item_id)
    if not defn:
        return False, "unknown item"
    if defn.get("slot") != slot:
        return False, "wrong slot"
    if not await remove_item(db, character["id"], item_id, 1):
        return False, "not in inventory"

    col = SLOT_COLUMNS[slot]
    prev = character.get(col)
    if prev:
        await add_item(db, character["id"], prev, 1)

    await db.execute(
        f"UPDATE characters SET {col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (item_id, character["id"]),
    )
    await db.commit()
    character[col] = item_id
    return True, "ok"


async def unequip_item(db, character: dict, slot: str) -> tuple[bool, str]:
    if slot not in VALID_SLOTS:
        return False, "invalid slot"
    col = SLOT_COLUMNS[slot]
    prev = character.get(col)
    if not prev:
        return False, "nothing equipped"
    await db.execute(
        f"UPDATE characters SET {col} = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (character["id"],),
    )
    await add_item(db, character["id"], prev, 1)
    await db.commit()
    character[col] = None
    return True, "ok"


async def buy_item(db, character: dict, item_id: str) -> tuple[bool, str]:
    defn = get_item_def(item_id)
    if not defn:
        return False, "unknown item"
    price = int(defn.get("price", 0))
    if price <= 0:
        return False, "not for sale"
    shop_ids = set(load_data().get("shop") or [])
    if item_id not in shop_ids:
        return False, "not in shop"
    gold = int(str(character.get("gold", "0")))
    if gold < price:
        return False, "not enough gold"
    gold -= price
    await db.execute(
        "UPDATE characters SET gold = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (str(gold), character["id"]),
    )
    await add_item(db, character["id"], item_id, 1)
    await db.commit()
    character["gold"] = str(gold)
    return True, "ok"


async def sell_item(db, character: dict, item_id: str) -> tuple[bool, str]:
    defn = get_item_def(item_id)
    if not defn:
        return False, "unknown item"
    price = int(defn.get("price", 0)) // 2
    if not await remove_item(db, character["id"], item_id, 1):
        return False, "not in inventory"
    gold = int(str(character.get("gold", "0"))) + price
    await db.execute(
        "UPDATE characters SET gold = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (str(gold), character["id"]),
    )
    await db.commit()
    character["gold"] = str(gold)
    return True, "ok"


def character_public(character: dict, items: list[dict] | None = None) -> dict:
    bonuses = equipment_bonuses(character)
    out = dict(character)
    out["bonuses"] = bonuses
    out["known_spells"] = out.get("known_spells")
    if items is not None:
        out["inventory"] = items
    return out
