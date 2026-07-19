# Dragon Quest 1 MMO - Implementation Plan

> **Historical document.** This was the original multi-phase roadmap used to build the MVP.  
> It is **not** the live source of truth. Prefer:
>
> - [README.md](README.md) — human overview & run instructions  
> - [docs/HUMAN.md](docs/HUMAN.md) — player/operator guide  
> - [AGENTS.md](AGENTS.md) — agent/LLM contract, protocol, tests  
>
> Shipped baseline as of docs refresh: **v0.5.19** (MVP + session_id, look, radiant, whisper, zone chat `/z`, AOI rebuild, **103** tests).  
> **Docs:** humans → README + docs/HUMAN.md · agents → AGENTS.md only.  
> **Not the live source of truth** — use README + docs/HUMAN.md + AGENTS.md.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      LOVE2D CLIENT                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Overworld   │  │   Combat    │  │   UI / Menus        │ │
│  │  Renderer    │  │   System    │  │   (Stats, Inventory)│ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         └────────────────┼─────────────────────┘            │
│                          │                                  │
│              ┌───────────▼───────────┐                      │
│              │   Network Layer       │                      │
│              │   (WebSocket Client)  │                      │
│              └───────────┬───────────┘                      │
└──────────────────────────┼──────────────────────────────────┘
                           │
                    WebSocket (JSON)
                           │
┌──────────────────────────┼──────────────────────────────────┐
│              FASTAPI GAME SERVER                            │
│              ┌───────────▼───────────┐                      │
│              │   Connection Manager  │                      │
│              └───────────┬───────────┘                      │
│                          │                                  │
│  ┌───────────────────────┼───────────────────────┐          │
│  │                       │                       │          │
│  ▼                       ▼                       ▼          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Auth API   │  │  Game World │  │   Combat Engine     │ │
│  │  (REST)     │  │  Manager    │  │   (DQ1 Mechanics)   │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         └────────────────┼─────────────────────┘            │
│                          │                                  │
│              ┌───────────▼───────────┐                      │
│              │      SQLite DB        │                      │
│              │   (Players, Items)    │                      │
│              └───────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
dq1-mmo/
├── client/                          # Love2D Client
│   ├── conf.lua
│   ├── main.lua
│   ├── libs/
│   │   ├── dq1-combat/              # Your combat library
│   │   ├── save-system/             # Your save library
│   │   └── lua-bignumber/           # BigNumber library
│   ├── client/
│   │   ├── network.lua              # WebSocket client
│   │   ├── auth.lua                 # Login/register UI
│   │   ├── world.lua                # Overworld state
│   │   ├── combat.lua               # Combat integration
│   │   ├── inventory.lua            # Equipment/items
│   │   └── renderer.lua             # Rendering engine
│   ├── assets/
│   │   ├── sprites/
│   │   ├── tiles/
│   │   └── ui/
│   └── states/
│       ├── login.lua
│       ├── overworld.lua
│       ├── combat.lua
│       └── inventory.lua
│
├── server/                          # Python FastAPI Server
│   ├── main.py                      # Entry point
│   ├── requirements.txt
│   ├── config.py
│   ├── auth/
│   │   ├── routes.py                # REST endpoints
│   │   ├── google_sso.py            # Google OAuth
│   │   ├── local_auth.py            # Email/password
│   │   └── jwt_handler.py           # JWT tokens
│   ├── game/
│   │   ├── world_manager.py         # World state
│   │   ├── player_manager.py        # Player operations
│   │   ├── combat_engine.py         # Server-side DQ1 combat
│   │   ├── enemy_spawner.py         # Enemy management
│   │   └── item_manager.py          # Equipment/items
│   ├── network/
│   │   ├── websocket_manager.py     # Connection handling
│   │   ├── message_handler.py       # Message routing
│   │   └── protocol.py              # Message types
│   ├── models/
│   │   ├── player.py
│   │   ├── item.py
│   │   └── enemy.py
│   └── database/
│       ├── db.py                    # SQLite connection
│       └── migrations.py            # Schema setup
│
├── shared/                          # Shared constants
│   ├── items.lua
│   ├── enemies.lua
│   ├── spells.lua
│   └── items.json
│
└── README.md
```

## Database Schema

```sql
-- Users table (authentication)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,              -- NULL for Google SSO users
    google_id TEXT UNIQUE,           -- NULL for email/password users
    username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Characters table (game state)
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    experience BIGINT DEFAULT 0,     -- Using BIGINT for incremental gains
    
    -- DQ1 Stats
    strength INTEGER DEFAULT 3,
    agility INTEGER DEFAULT 2,
    max_hp INTEGER DEFAULT 20,
    max_mp INTEGER DEFAULT 0,
    current_hp INTEGER DEFAULT 20,
    current_mp INTEGER DEFAULT 0,
    
    -- BigNumber stats (stored as string for huge numbers)
    gold TEXT DEFAULT '0',           -- BigNumber string
    total_damage_dealt TEXT DEFAULT '0',
    total_kills INTEGER DEFAULT 0,
    
    -- Position
    world_x REAL DEFAULT 0,
    world_y REAL DEFAULT 0,
    map_id INTEGER DEFAULT 1,
    
    -- Inventory
    equipment_weapon TEXT,
    equipment_armor TEXT,
    equipment_shield TEXT,
    equipment_helmet TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Items table (item instances)
CREATE TABLE item_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,           -- Reference to items.json
    quantity INTEGER DEFAULT 1,
    is_equipped BOOLEAN DEFAULT 0,
    
    FOREIGN KEY (character_id) REFERENCES characters(id)
);
```

## Network Protocol (WebSocket Messages)

All messages are JSON with a `type` field:

```json
// Client -> Server
{"type": "auth", "token": "jwt_token"}
{"type": "move", "x": 10, "y": 20}
{"type": "attack"}
{"type": "flee"}
{"type": "use_spell", "spell": "heal"}
{"type": "equip", "slot": "weapon", "item": "copper_sword"}
{"type": "unequip", "slot": "weapon"}

// Server -> Client
{"type": "auth_ok", "player_id": 1, "character": {...}}
{"type": "world_state", "players": [...], "enemies": [...]}
{"type": "player_moved", "player_id": 2, "x": 15, "y": 25}
{"type": "combat_start", "enemy": {...}}
{"type": "combat_update", "player_hp": 20, "enemy_hp": 15, "events": [...]}
{"type": "combat_end", "result": "victory", "xp": 10, "gold": 5}
{"type": "level_up", "new_level": 5, "new_stats": {...}}
{"type": "inventory_update", "items": [...]}
```

## Implementation Phases

### Phase 1: Project Setup & Auth (Day 1-2)

**Tasks:**
1. Initialize project structure
2. Set up Python virtual environment with dependencies:
   ```
   fastapi uvicorn websockets python-jose[cryptography] 
   passlib[bcrypt] httpx aiosqlite
   ```
3. Create SQLite database schema
4. Implement email/password registration and login
5. Implement Google OAuth with `authlib` (simpler than Passport equivalent)
6. Create JWT token generation/validation
7. Create Love2D project structure

**Deliverable:** User can register, login, and get JWT token

### Phase 2: Client Foundation (Day 3-4)

**Tasks:**
1. Create Love2D main game loop
2. Implement WebSocket client using `love2d-lua-websocket`
3. Create login screen UI (text fields, buttons)
4. Implement JWT authentication flow
5. Create basic renderer for tile-based overworld
6. Integrate `lua-bignumber` for stat displays

**Deliverable:** Client connects to server, authenticates, shows empty world

### Phase 3: Game World & Movement (Day 5-7)

**Tasks:**
1. Create tile-based overworld map (8x8 grid for MVP testing area)
2. Implement player movement (grid-based, 4-directional)
3. Server-side position tracking and validation
4. Broadcast player positions to nearby players
5. Implement other player visibility (show nearby players)
6. Add collision detection for walls/obstacles

**Deliverable:** Multiple players can move around and see each other

### Phase 4: Combat System (Day 8-10)

**Tasks:**
1. Port `dq1-combat` library to server
2. Implement enemy spawning system (random encounters)
3. Create combat state management (server tracks all active battles)
4. Implement combat message flow:
   - Client sends action (attack/spell/flee)
   - Server processes using dq1-combat
   - Server sends combat update back
5. Add BigNumber support for damage/HP at high levels
6. Create combat UI on client side

**Deliverable:** Players can fight enemies, gain XP, level up

### Phase 5: Equipment & Stats (Day 11-13)

**Tasks:**
1. Create items.json with DQ1 equipment (weapons, armor, shields)
2. Implement inventory system (client + server)
3. Equipment slots (weapon, armor, shield, helmet)
4. Stats calculation (base + equipment bonuses)
5. Inventory UI with equip/unequip
6. Gold system for purchasing (basic shop)

**Deliverable:** Players can equip items and see stat changes

### Phase 6: Testing Area & Polish (Day 14-16)

**Tasks:**
1. Create MVP testing area:
   - Town (safe zone, shop)
   - Field (random encounters)
   - Dungeon (harder enemies)
2. Add enemy variety (slime, skeleton, etc. from dq1-combat)
3. Implement level progression (stats, spells)
4. Add basic UI polish (HP/MP bars, minimap)
5. Error handling and reconnection logic
6. Basic anti-cheat (server-side validation)

**Deliverable:** Complete playable MVP

## Key Technical Decisions

### 1. Server Authority
- **All combat runs server-side** using `dq1-combat` library
- Client only sends actions, never game state
- Prevents cheating

### 2. BigNumber Integration
- Use `lua-bignumber` for display only
- Server stores big numbers as strings in SQLite
- For MVP, keep stats in regular integers (BigNumber ready)

### 3. WebSocket Message Format
- JSON for readability (MVP)
- Can optimize to binary later if needed

### 4. Enemy Spawning
- Server-side random encounter system
- Each map zone has enemy tables (from dq1-combat data)
- Encounter rate based on steps/movement

### 5. Player Visibility
- Only broadcast nearby players (within 10 tiles)
- Reduces bandwidth for larger maps

## MVP Scope (What's IN)

- Email/password + Google SSO authentication
- Grid-based overworld movement
- See other players in overworld
- Random encounter combat (DQ1 mechanics)
- Equipment system (4 slots)
- Stats system (STR, AGI, HP, MP)
- XP and leveling (levels 1-30)
- Gold and basic shop
- 10+ enemy types from dq1-combat
- Spells system (Heal, Hurt, etc.)
- BigNumber ready for future scaling

## MVP Scope (What's OUT - Future)

- Guilds/parties
- PvP combat
- Trading system
- Quest system
- Multiple maps
- Crafting
- Offline progress

## Dependencies

### Server (Python)
```
fastapi==0.109.0
uvicorn[standard]==0.27.0
websockets==12.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
authlib==1.3.0
aiosqlite==0.19.0
httpx==0.26.0
```

### Client (Love2D)
- `love2d-lua-websocket` (WebSocket client)
- `lua-bignumber` (your library)
- `dq1-combat` (your library)
- `save-system` (your library)

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| WebSocket latency | Grid-based movement is forgiving; turn-based combat doesn't need real-time |
| SQLite concurrency | Use WAL mode, serialize writes with asyncio lock |
| Server load | Limit players per server instance, start with single server |
| Cheating | Server-authoritative combat, validate all inputs |
| Data loss | Regular auto-saves, use your save-system library for client cache |
