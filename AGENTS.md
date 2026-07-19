# AGENTS.md — LLM / agent contract for `dq1_mmo`

> **Audience: coding agents and LLMs only.**  
> Humans use [README.md](README.md) and [docs/HUMAN.md](docs/HUMAN.md) — never send players here first.  
> Do **not** copy protocol tables, reliability rule lists, or test matrices into README / HUMAN.

You are editing this multiplayer game. Prefer this file over guessing.

## Scope

| In (current) | Out (do not invent as done) |
|:-------------|:----------------------------|
| Love2D client + FastAPI WS server | Parties / PvP / trade |
| Server-authoritative DQ1 1v1 combat | Idle offline progress |
| Grid overworld, AOI, chat (global/nearby/zone)/emotes/whisper/look, who + online roster + session_id | Multi-map worlds |
| Auth JWT, equip/shop/sell (incl. equipped), consumables, inn, field magic (radiant), XP, UI + PNGs | Final commercial art (placeholders OK to replace) |
| Char create/delete (max 3) · SQLite · free-port multiplayer tests · reconnect soft grace | Binary protocol |

**Version:** `0.5.19` (`server/config.py` → `VERSION`) · **103** tests in `server/tests/run_tests.py`

## Documentation map (do not mix)

| File | Audience | Use for |
|:-----|:---------|:--------|
| `README.md` | Humans on GitHub | Install, features, controls (no protocol dumps) |
| `docs/HUMAN.md` | Humans | Gameplay & ops detail |
| `docs/README.md` | Both | Index + audience rules |
| **`AGENTS.md`** | **You (agents)** | Protocol, paths, tests, reliability, constraints |
| `plan.md` | Historical | Original roadmap only — **not source of truth** |

**Never** put long protocol tables in `README.md` / `docs/HUMAN.md`.  
**Never** put “how to install Love2D for players” only in this file.

When you change behavior, update **README + HUMAN + this file** as needed (and bump `VERSION`).

## Install / run (agent checklist)

```bash
# Server
cd server && source .venv/bin/activate   # create venv + pip install -r requirements.txt if needed
./run.sh                                 # :8000

# Tests (required after game logic / network changes)
python tests/run_tests.py

# Client (host machine with Love2D)
love client

# Multiplayer bots
./tools/mp_sim.sh -n 3
```

Env: optional repo-root `.env` (see `.env.example`). Isolated tests set `DATABASE_URL` / `ALLOW_DEBUG` themselves.

## Architecture (authoritative model)

```
Love2D client  --JSON WebSocket-->  FastAPI
   states/*                         network/message_handler.py
   client/network.lua               network/websocket_manager.py  (AOI, rates)
                                    game/combat_engine.py         (DQ1 1v1)
                                    game/world_manager.py         (MVP_MAP)
                                    SQLite via database/*
```

- **Combat is server-side only.** Client sends actions; never trust client HP/damage.
- Client `libs/dq1-combat` is a **symlink for reference** — live multiplayer does **not** resolve battles in Lua.
- Canonical data: `shared/dq1_data.json` (loaded by Python `game/data_loader.py`). Tiny `shared/*.lua` stubs are not the authority.

## Hot paths (edit carefully)

| Path | Role |
|:-----|:-----|
| `server/main.py` | WS accept loop, connect meta, send |
| `server/network/message_handler.py` | All game messages + combat + chat |
| `server/network/websocket_manager.py` | Connections, AOI, move/chat rate limits |
| `server/network/protocol.py` | Message type enums |
| `server/network/presence.py` | Position flush, idle kick, combat grace expiry |
| `server/game/combat_engine.py` | Battle state machine |
| `server/game/formulas.py` | Damage / flee / magic math |
| `server/game/world_manager.py` | Map tiles & zones |
| `client/client/ui.lua` | Shared DQ-style UI toolkit (panels, bars, menus) |
| `client/client/assets.lua` | PNG loader (`client/assets/…`); missing → procedural fallback |
| `client/client/renderer.lua` | Overworld tiles + actors |
| `client/assets/` | `tiles/`, `sprites/heroes/`, `sprites/enemies/`, `svg/`, `ATTRIBUTION.md` |
| `client/client/network.lua` | WS client, reconnect, `Network.chat` |
| `client/client/world.lua` | Prediction queue, remote players |
| `client/states/login.lua` | Auth UI |
| `client/states/character.lua` | Hero select / create UI |
| `client/states/overworld.lua` | Move, chat UI (`/w`, `/z`), presence handlers |
| `client/states/combat.lua` | Combat UI only (no authority) |
| `client/states/inventory.lua` | Bag / equip / shop UI |
| `client/conf.lua` | Window title/size (default 1024×720) |

UI presentation changes stay in `client/client/ui.lua` + states; do not fork styling per-screen unless necessary.

## WebSocket protocol

All messages are JSON objects with a `type` string.

### Client → server

| type | Fields (main) | Notes |
|:-----|:--------------|:------|
| `auth` | `token`, `character_id` | First message after connect |
| `move` | `x`, `y`, `seq` | Adjacent step only; rate-limited |
| `attack` / `flee` | — | Combat only, hero turn |
| `use_spell` | `spell` / `id` | **Combat** battle spells, or **field** magic if not in combat (`field: true` spells). Field: heal/healmore (refuse at full HP), return, repel, radiant (light buff), outside (dungeon only) |
| `equip` / `unequip` | `slot`, `item` | Not in combat |
| `buy` / `sell` / `shop` / `inventory` | `item` | Shop only in **town** |
| `use_item` | `item` / `item_id` | Herb (heal), Wings (town), Fairy Water (repel 64 steps). Herb OK in combat (uses turn). |
| `rest` / `inn` | optional `preview` | Town inn: full HP/MP for gold (`level*4`, min 4). Not in combat. |
| `chat` | `text`, optional `channel` | Default **global**; `nearby` AOI; `zone` same tile-zone; `whisper` + `to`/`to_id` |
| `say` | `text` | **Nearby** (AOI) chat |
| `whisper` / `tell` | `to` (name) and/or `to_id`/`player_id`, `text` | Private to one **online** player (echo to self) |
| `emote` | `emote` | Nearby social: wave, bow, cheer, dance, cry, laugh, point, sit, think |
| `who` | — | Nearby players + `online` count (lightweight; no full map) |
| `look` / `examine` | `name` or `player_id` | Public card; coords only if nearby. Rate-exempt. |
| `ping` | `t`, optional `sync` | Heartbeat / presence refresh |
| `sync` | — | Full nearby snapshot; **rebuilds AOI** server-side |
| `debug_encounter` | `enemy`, optional `seed` | Only if `ALLOW_DEBUG` |

### Server → client

| type | Purpose |
|:-----|:--------|
| `auth_ok` / `auth_fail` | Session (`session_id`, `online` on success) |
| `world_state` | `players`, `map`, optional `you`, `online`, `repel`, `radiant`, `zone` |
| `move_ok` | Ack: `ok`, `x`, `y`, `seq`, optional `duplicate`/`reason` |
| `player_joined` / `player_left` / `player_moved` | Presence (`player_left.reason`: `disconnect` \| `out_of_range`) |
| `player_update` | `level`, `in_combat`, position |
| `chat` | `player_id`, `name`, `text`, `channel` (`global` \| `nearby` \| `zone` \| `whisper`); zone may include `zone`; whisper has `to` / `to_id` |
| `combat_start` / `combat_resume` / `combat_update` / `combat_end` | Battles |
| `level_up` | After victory |
| `inventory_update` / `shop_list` | Economy |
| `item_used` | Consumable result (`healed`, `teleported`, `repel_steps`, `message`) |
| `rest_ok` | Inn result or preview (`cost`, `character`, `message`) |
| `spell_cast` | Field magic result (`healed`, `teleported`, `repel_steps`, `radiant_steps`, `character`) |
| `emote` | Nearby emote broadcast |
| `who` | `players`, `online`, `roster`, `you` (incl. `repel`, `radiant`, `zone`) |
| `look` | `player` card (`id`, `name`, `level`, `in_combat`, `nearby`, optional `x`/`y`) |
| `online` | Global pulse: `online` count + `roster` (no positions); debounced ~150ms with delayed flush |
| `error` | `reason` (+ sometimes `x`/`y`/`seq`/`retry_after`) |
| `pong` | Echo `t` for RTT |

Public player objects include: `id`, `name`, `x`/`y` (and `world_x`/`world_y`), `level`, `in_combat`, `map_id`.

### Reliability rules (do not break)

1. Moves are **server-authoritative**; client predicts with `seq` and reconciles on `move_ok`.
2. Duplicate `seq` → idempotent `move_ok` with `duplicate: true`.
3. Reconnect: only the **current** WebSocket may `disconnect` that character (`manager.owns`).
4. Combat disconnect → grace (`COMBAT_GRACE_SECONDS`); resume via `combat_resume`.
5. Idle kick: `disconnect()` already notifies AOI — **do not** global double-broadcast `player_left`.
6. Chat: sanitize (strip control chars, collapse whitespace); empty → error; rate-limit → `chat_rate_limit`.
7. **Ping / sync / who / look must not be rate-limited** (main.py exempts them so RTT and presence stay healthy under move spam).
8. Outbound WS batches: best-effort send; one failure must not crash the connection loop.
9. Integration tests must use **ephemeral ports** via `tests.ws_helpers` (never hard-code 8765–8767).
10. If a WS **send fails**, stop the receive loop and disconnect cleanly (do not call `receive_*` on a dead socket).
11. On connect, deliver **`auth_ok` (+ world_state) before** `broadcast_online()` so the joiner never sees `online` first.
12. DB / presence / manager locks must be **loop-safe** (per-loop locks + generation-stamped `close_db`) — sequential uvicorn tests use new event loops.
13. Lifespan **must** `reset_manager()` + `reset_combat_engine()` so multiplayer state never leaks across restarts/tests.
14. `init_db` must read `config.DATABASE_URL` live (never freeze via `from config import DATABASE_URL`).
15. Brief disconnects preserve **repel** and **radiant** via soft grace (~60s); move `seq` always resets on auth (client starts at 0).
16. REST: `DELETE /auth/characters/{id}` (owner only, 204). Character payloads may include `xp_progress`.
17. **Nearby chat/emotes** use geometric AOI **union** cached `visible` — never only a stale non-empty visible set.
18. **`sync` rebuilds AOI** (`rebuild_aoi`) so desync/reconnect storms re-link peers; `world_state` may include `zone`.

## Tests (mandatory for your changes)

```bash
cd server && source .venv/bin/activate && python tests/run_tests.py
```

| Module | What it proves |
|:-------|:---------------|
| `tests.test_formulas` | Damage / flee / hurt bands |
| `tests.test_combat` | Battle flow, gear ATK, level-up |
| `tests.test_presence` | AOI, reconnect ownership, rates, combat meta |
| `tests.test_api` | Register → WS move → buy → equip → fight |
| `tests.test_multiplayer` | Two clients, chat, combat flag, leave |
| `tests.test_adversarial` | Edge cases: world, combat, gold, chat |
| `tests.test_items` | Herb / wings / fairy water / repel |
| `tests.test_mp_reliability` | Nearby chat, emotes, 3 players, ping under load |
| `tests.test_inn` | Town inn cost, rest, not enough gold |
| `tests.test_who` | Free-port who/online multiplayer query |
| `tests.test_field_magic` | Field spell lists + heal formula |
| `tests.test_mp_teleport` | RETURN spell AOI + who under move spam |
| `tests.test_online_roster` | Online pulse on join/leave + roster (no coords) |
| `tests.test_mp_expand` | Whisper, repel soft-reconnect, socket replace, combat roster pulse |
| `tests.test_adversarial_hunt` | Neg seq, delete kicks session, sell equipped, herb full HP, combat guards |
| `tests.test_features_v0513` | Radiant light, char delete, XP progress |
| `tests.test_mp_look` | Look/examine, online debounce, 4-player stress, field spell in combat |
| `tests.test_mp_session` | session_id, level roster pulse, reconnect presence |
| `tests.test_mp_zone` | Zone chat, whisper-by-id, AOI rebuild, geometry-safe nearby |
| `tests.ws_helpers` | Free-port uvicorn helpers (not a test module) |

- Prefer **adding tests** for new multiplayer/network behavior.
- Integration WS tests should use `tests.ws_helpers.start_server()` (ephemeral port), not hard-coded 8765–8767.
- Use isolated `DATABASE_URL` (runner already temp-isolates).
- Do not depend on the developer's live `data/dq1_mmo.db`.

## Coding conventions

- Python: async FastAPI; game logic in `server/game/*`; no combat authority in the client.
- Lua: Love2D 11; states under `client/states/`; network thin; UI via `UI.*` helpers.
- Bump `VERSION` in `server/config.py` when shipping user-visible behavior; mirror in README + HUMAN.
- Gold may be string-stored (big-number ready); HP/damage still normal ints for MVP.
- Client art: drop PNGs under `client/assets/` (see `ATTRIBUTION.md`). Missing files use procedural fallback.
- Do not commit secrets; never force-push `main` unless user asks.

## Common agent mistakes

| Mistake | Correct approach |
|:--------|:-----------------|
| Run combat in Lua client for multiplayer | Call server actions only |
| Trust client position | Validate adjacency + walkable tiles |
| Update only README | Keep `AGENTS.md` / `docs/HUMAN.md` in sync |
| Treat `plan.md` as backlog truth | Re-read code + this file |
| Skip multiplayer tests after net changes | Run full `run_tests.py` |

## Related libraries

- Combat reference (Lua): sibling repo / `client/libs/dq1-combat` → see that repo's `AGENTS.md` and `docs/HUMAN.md`.
- Live MMO combat code lives in **Python** under `server/game/`.
