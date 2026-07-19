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
- [ ] Phase 2 — client foundation / websocket polish
- [ ] Phase 3 — world & multiplayer movement
- [ ] Phase 4 — combat (dq1-combat)
- [ ] Phase 5 — equipment & shop
- [ ] Phase 6 — MVP zones & polish
