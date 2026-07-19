# Dragon Quest 1 MMO

Love2D client + FastAPI/WebSocket server. See [plan.md](plan.md) for full architecture.

## Quick start (server)

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Server: `http://127.0.0.1:8000`  
Docs: `http://127.0.0.1:8000/docs`  
WebSocket: `ws://127.0.0.1:8000/ws`

### Auth API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | `{email, password, username}` → JWT |
| POST | `/auth/login` | `{email, password}` → JWT |
| GET | `/auth/me` | Bearer token → user |
| GET | `/auth/characters` | list characters |
| POST | `/auth/characters` | `{name}` create character |
| GET | `/auth/google/login` | Google OAuth (if configured) |

### Example

```bash
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"hero@example.com","password":"password","username":"Hero"}'
```

## Client (Love2D)

```bash
# optional: link combat library
ln -sfn ../../dq1-combat client/libs/dq1-combat

# install love2d-lua-websocket into client/libs (for multiplayer)
love client
```

Without the websocket library, login/character select still work over HTTP; overworld runs in local preview mode.

## Layout

```
client/     Love2D game
server/     FastAPI + WebSocket
shared/     items/enemies/spells stubs
data/       SQLite database (gitignored)
plan.md     implementation roadmap
```

## Status

- [x] Phase 1 — project setup & auth
- [x] Phase 2 — client foundation / websocket client
- [x] Phase 3 — world map, collision, nearby multiplayer movement
- [x] Phase 4 — server DQ1 combat, encounters, combat UI
- [ ] Phase 5 — equipment & shop
- [ ] Phase 6 — MVP zones & polish

### Combat

- Server-authoritative battles (DQ1 formulas from `dq1-combat`)
- Random encounters on **field** tiles (not town)
- Client: `B` forces a slime fight (debug)
- Actions: `attack`, `flee`, `use_spell` over WebSocket

## Map tiles

| Code | Meaning |
|------|---------|
| 0 | grass / field |
| 1 | wall |
| 2 | town (safe) |
| 3 | water (blocked) |
