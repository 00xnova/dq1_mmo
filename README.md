# Dragon Quest 1 MMO

Love2D client + FastAPI/WebSocket server. Server-authoritative DQ1 combat.

**Version:** 0.3.0

## Quick start

```bash
# Server
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh
# API: http://127.0.0.1:8000/docs

# Client (needs Love2D 11.x)
love client
```

Default login fields work after you register once (`hero@example.com` / `password`).

## Controls

| Key | Action |
|-----|--------|
| WASD / arrows | Move |
| I | Inventory / shop (Tab in inventory) |
| B | Debug slime fight (`ALLOW_DEBUG=1`) |
| Combat: A / F / Enter | Attack / Flee / confirm |
| Esc | Back / quit |

## Features

- Email/password auth + JWT (Google OAuth optional via env)
- Grid overworld (town / field / water / walls)
- Multiplayer presence (nearby players)
- Random field encounters, DQ1 combat formulas
- XP, level-ups, spells by level
- Equipment, inventory, town shop
- Defeat → town respawn, half gold
- Client reconnect + HP/MP bars

## Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
```

## Layout

```
client/     Love2D game
server/     FastAPI + WebSocket + combat engine
shared/     dq1_data.json (enemies, spells, gear)
data/       SQLite DB (gitignored)
plan.md     original roadmap
```

## Env

See `.env.example`. Production tips:

- Set a strong `SECRET_KEY`
- `ALLOW_DEBUG=0` to disable forced encounters
- Point `DATABASE_URL` at a durable path

## Networking reliability

- **Server-authoritative moves** with `seq` + `move_ok` ack/reject
- Client **prediction + reconciliation** (pending queue, snap on reject)
- **Move rate limit** (~10 steps/sec) and global msg rate limit
- **Deferred position DB writes** (flush every ~3s / combat / disconnect)
- **Heartbeats** (`ping`/`pong` + RTT) and stale-connection reconnect with backoff
- **Idle kick** (~90s), presence `sync`, remote player lerp
- Reconnect-safe socket ownership (stale `finally` cannot wipe new session)

## Protocol (WebSocket JSON)

**Client → server:** `auth`, `move`(+`seq`), `attack`, `flee`, `use_spell`, `equip`, `unequip`, `buy`, `sell`, `shop`, `inventory`, `ping`, `sync`

**Server → client:** `auth_ok`, `world_state`, `move_ok`, `player_moved`, `player_joined`, `player_left`, `combat_start`, `combat_update`, `combat_end`, `level_up`, `inventory_update`, `shop_list`, `error`, `pong`
