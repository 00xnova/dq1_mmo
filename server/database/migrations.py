import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    google_id TEXT UNIQUE,
    username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    experience INTEGER DEFAULT 0,

    strength INTEGER DEFAULT 4,
    agility INTEGER DEFAULT 4,
    max_hp INTEGER DEFAULT 15,
    max_mp INTEGER DEFAULT 0,
    current_hp INTEGER DEFAULT 15,
    current_mp INTEGER DEFAULT 0,

    gold TEXT DEFAULT '0',
    total_damage_dealt TEXT DEFAULT '0',
    total_kills INTEGER DEFAULT 0,

    world_x REAL DEFAULT 4,
    world_y REAL DEFAULT 4,
    map_id INTEGER DEFAULT 1,

    equipment_weapon TEXT,
    equipment_armor TEXT,
    equipment_shield TEXT,
    equipment_helmet TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS item_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER DEFAULT 1,
    is_equipped INTEGER DEFAULT 0,

    FOREIGN KEY (character_id) REFERENCES characters(id)
);

CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_item_instances_character_id ON item_instances(character_id);
"""


async def run_migrations(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA)
    await db.commit()
