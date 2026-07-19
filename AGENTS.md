# AGENTS.md — LLM / agent contract for `dq1_mmo`

> **Audience: coding agents and LLMs only.**  
> Humans use [README.md](README.md) and [docs/HUMAN.md](docs/HUMAN.md) — never send players here first.  
> Do **not** copy protocol tables, reliability rule lists, or test matrices into README / HUMAN.

| Humans (do not use this file first) | Agents (you) |
|:------------------------------------|:-------------|
| [README.md](README.md) · [docs/HUMAN.md](docs/HUMAN.md) · [docs/README.md](docs/README.md) · [ATTRIBUTION](client/assets/ATTRIBUTION.md) | **This file only** for protocol · hot paths · tests · reliability |

You are editing this multiplayer game. Prefer this file over guessing.

## Scope

| In (current) | Out (do not invent as done) |
|:-------------|:----------------------------|
| Love2D client + FastAPI WS server | Parties / PvP / trade |
| Server-authoritative DQ1 1v1 combat | Idle offline progress |
| Grid overworld, AOI, chat (global/nearby/zone/system)/emotes/whisper/reply/lastwhisper/look/find/status/ignore/roll/counts, who/players/near/zone + idle/AFK roster + session_id | Multi-map worlds |
| Auth JWT + password change, equip/shop/sell/discard, consumables, inn, field magic · slash buy/sell/use/equip/cast/discard · stuck/home · yell · emotes · busy AFK · meetup invite/accept/decline/cancel · share · askwhere/locate · thank/ty · poke/nudge · offline invite clear · soft-grace invite peer clear · fighting peek · combat_count census · find combat filter · AFK notices · afk_count on peeks/health · refund_chat restore_afk on failed private delivery · social_peer_card near/far on pending/lastinvite/lastemote/social · whisper via private_social_delivery | Final commercial art (placeholders OK to replace) |
| Char create/delete (max 3) · SQLite · free-port multiplayer tests · soft grace · AOI self-heal · `/cast` · `/buy` · `/stuck` · `/played` · `/counts` · auth welcome | Binary protocol |

**Version:** `0.5.128` (`server/config.py` → `VERSION`) · **662** tests in `server/tests/run_tests.py`  
**Docs:** humans → `README.md` + `docs/HUMAN.md` · agents → **this file only** (protocol / tests / reliability).  
When docs fire: sync version badges + test count; **never** copy protocol tables into human docs.  
Human entry points only: `README.md`, `docs/HUMAN.md`, `docs/README.md`, `client/assets/ATTRIBUTION.md`.  
Human “What’s new” should use plain language (no `session_id` / message-type catalogs / AOI jargon).  
GitHub README may use badges and callouts; still **no** protocol dumps.  
Keep trees separate on every docs pass: polish README for GitHub humans; put protocol / reliability / test matrix **only here**.  
Keep badges at **0.5.128** / **662** until the suite or `VERSION` changes.  
Last **pushed** ship: `5135109` / `158abc0` (v0.5.127). Shipping **0.5.128** (code local; docs this pass).
**Docs map:** [docs/README.md](docs/README.md) — audience rules for both trees.  
Docs pass (**this run**): badges **0.5.128 / 662** · self_peeks extract · protocol only here.

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
| `server/network/message_handler.py` | All game messages + combat + chat (dispatcher; helpers in `handlers/_common.py`) |
| `server/network/handlers/_common.py` | Shared message helpers (social aliases, qty parse, private delivery, combat UI msgs) |
| `server/network/handlers/session.py` | Ping + sync session peeks (extracted) |
| `server/network/handlers/social_peeks.py` | lastwhisper/social/lastemote/lastshare/lastinvite/pending |
| `server/network/handlers/look.py` | look/examine/profile/whereis (coords only if AOI-near) |
| `server/network/handlers/status.py` | status/me/whoami/stats sheet + MP census |
| `server/network/handlers/self_peeks.py` | gold/vitals/xp/spells/buffs (zone · combat · nearby) |
| `server/network/handlers/presence_peeks.py` | who/near/counts/zone/fighting |
| `server/network/websocket_manager.py` | Connections, AOI, move/chat rate limits |
| `server/network/protocol.py` | Message type enums |
| `server/network/presence.py` | Position flush, idle kick, combat grace expiry |
| `server/game/combat_engine.py` | Battle state machine |
| `server/game/formulas.py` | Damage / flee / magic math |
| `server/game/world_manager.py` | Map tiles & zones |
| `client/client/ui.lua` | Shared DQ-style UI toolkit (panels, bars, menus) |
| `client/client/assets.lua` | PNG loader (`client/assets/…`); missing → procedural fallback |
| `client/client/renderer.lua` | Overworld tiles + actors |
| `client/assets/` | `tiles/`, `sprites/heroes/`, `sprites/enemies/`, `src/kenney/`, `src/tiny-creatures/`, `svg/`, `ATTRIBUTION.md` |
| `tools/import_open_assets.py` | Kenney + Tiny Creatures CC0 import; punches TC black mats; SVG companions always written |
| `tools/gen_placeholder_assets.sh` | Thin wrapper around import / scale path |
| `client/client/network.lua` | WS client, reconnect · `request_status()` (sheet) ≠ `link_status()` (HUD) |
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
| `chat` / `g` | `text`, optional `channel` | Default **global**; `nearby` AOI; `zone` same tile-zone; `whisper` + `to`/`to_id`. Type `g` forces global. |
| `say` / `s` / `nearby_chat` | `text` | **Nearby** (AOI) chat |
| `whisper` / `tell` | `to` (name) and/or `to_id`/`player_id`, `text` | Private to one **online** player (echo to self) |
| `reply` / `r` | `text` (or whisper with `reply:true` / `to:@last`) | Reply to last whisper peer (server-tracked, soft-grace). Raw type `r` is reply-only, not a separate channel. |
| `emote` | `emote` | Nearby social: wave, bow, cheer, dance, cry, laugh, point, sit, think |
| `wave` / `bow` / `cheer` / `dance` / `cry` / `laugh` / `point` / `sit` / `think` | optional `to`/`to_id` | Emote shortcuts (same as `emote` + that name); directed + `@last` / `reply` |
| `lastemote` / `last_emote` / `who_emote` / `emote_last` | — | Last emote **to** + **from** (soft-grace, near/far). Rate-exempt. |
| social `to` | `@emote` / `@lastemote` · `@emotedby` / `@wavedby` | Emote to (then from) · emote-from only |
| `lastshare` / `last_share` / `who_share` / `share_last` | — | Last share **to** + **from** (soft-grace, near/far). Rate-exempt. |
| social `to` tokens | `@share` / `@lastshare` · `@from` / `@sharefrom` | Share to (then from) · share-from only |
| `busy` | optional reason | AFK alias (same as `afk`/`away`). |
| `invite` / `meet` / `beckon` / `come` | `to`/`to_id` or `@last` | Private meetup invite (zone; coords only if nearby). Not a party. Chat-rate. |
| `cancel` / `uninvite` / `invite_cancel` | — | Cancel your last outgoing invite. Chat-rate. |
| `share` / `sharepos` | `to`/`to_id` or `@last` | Private share of your zone + coords. Chat-rate. |
| `askwhere` / `ask_where` / `askpos` / `locate` / `whereru` | `to`/`to_id` or `@last` | Private “where are you?” request (target may `/share @last`). Chat-rate. |
| `thank` / `thanks` / `ty` / `thx` | `to`/`to_id` or `@last` | Private thanks. Chat-rate. |
| `poke` / `nudge` / `hey` / `attention` / `tap` | `to`/`to_id` or `@last` | Private attention ping. Chat-rate. |
| `lastinvite` / `last_invite` | — | Last invite **from** + **to** (soft-grace, near/far). Rate-exempt. |
| `pending` / `invites` / `meetup` | — | Incoming + outgoing meetup pointers. Rate-exempt. |
| `accept` / `coming` / `invite_accept` | — | Private reply to last inviter “is coming”. Chat-rate. |
| `decline` / `later` / `invite_decline` | — | Private decline of last invite. Chat-rate. |
| `fighting` / `combats` / `battles` | — | Nearby combat roster + count. Rate-exempt. |
| `who` / `players` / `online_list` | — | Nearby players + `online` + `afk_count` + `nearby_combat` + `zones`; lightweight |
| `look` / `examine` / `inspect` / `profile` / `card` / `player_info` | `name` or `player_id` | Public card; coords only if nearby. Bare → self. Rate-exempt. |
| `zone` / `where` / `mapinfo` / `whereami` / `coords` | — | Self zone + x/y + same-zone roster + zone counts. Rate-exempt. |
| `version` / `ver` / `about` / `server` / `info` | — | `{version, online, zones, uptime, service}`. Rate-exempt. |
| `played` / `session` / `session_time` / `online_time` | — | Connection age + multiplayer snapshot (`seconds`, `name`, `zone`, `online`, `nearby_count`, `afk`, `idle`, `message`). Rate-exempt. |
| `whereis` / `where_is` | `name` or `player_id` | Look alias. Rate-exempt. |
| `stuck` / `unstuck` / `home` / `recall_home` | — | Free teleport to town spawn; blocked in combat; chat-rate limited. |
| `yell` / `shout` | `text` | Zone chat (same as channel zone). |
| `afk` / `away` / `back` | optional `text`/`message`/`reason` | Manual AFK + optional status (max 48). `back` / text `back` clears. |
| `emotes` or `emote`+`list` | — | Emote catalog `{emotes[], message}`. Rate-exempt. |
| `buy` / `purchase` | `item`, optional `quantity` | Town shop buy. |
| `sell` / `vendor_sell` | `item`, optional `quantity` | Town shop sell. |
| `shop` / `store` / `vendor` | — | Shop catalog list. Rate-exempt. |
| `use` / `use_item` / `consume` | `item` | Consumable from bag. |
| `equip` / `wear` / `wield` | `item`, optional `slot` | Equip; slot auto from equipment def if omitted. |
| `cast` / `cast_spell` / `use_spell` | `spell` | Field magic when not in combat. |
| `heal` / `repel` / `return` / `outside` / `radiant` | — | Field-spell shortcuts (same as cast). |
| `status` / `me` | — | Self sheet: stats, xp_progress, zone, repel/radiant. Rate-exempt. |
| `find` / `search` | `q`/`query`/`name`, optional `limit`, optional `zone` | Online roster prefix search (no coords); zone filter town/field/dungeon. Rate-exempt. |
| `help` / `commands` | — | Command list + version. Rate-exempt. |
| `ignore` / `unignore` / `ignores` | `name` or `player_id` | Mute chat/emotes from a player (session soft-grace). |
| `ping` | `t`, optional `sync` | Heartbeat; pong echoes `t` + `server_t` + `online` |
| `sync` | — | Full nearby snapshot; **rebuilds AOI** server-side |
| `debug_encounter` | `enemy`, optional `seed` | Only if `ALLOW_DEBUG` |

### Server → client

| type | Purpose |
|:-----|:--------|
| `auth_ok` / `auth_fail` | Session (`session_id`, `online`, `welcome`, `ignores`, `last_whisper`, `repel`/`radiant` on success) |
| `world_state` | `players`, `map`, optional `you` (`x`/`y`/`zone`), `online`, `repel`, `radiant`, `zone` (on auth + sync) |
| `move_ok` | Ack: `ok`, `x`, `y`, `seq`, optional `zone`, `duplicate`/`reason` |
| `player_joined` / `player_left` / `player_moved` | Presence (`player_left.reason`: `disconnect` \| `out_of_range`) |
| `player_update` | `level`, `in_combat`, position |
| `chat` | `player_id`, `name`, `text`, `channel` (`global` \| `nearby` \| `zone` \| `whisper` \| `system`); system level-up nearby; whisper has `to` / `to_id` |
| `find` | `query`, `players` (roster cards with optional `zone`, no coords), `count`, `online` |
| `help` | `commands[]`, `channels`, `version`, `online` |
| `combat_end` | `result`, `xp`, `gold`; on defeat also `gold_lost`, `respawn` |
| `pong` | `t` (echo), `server_t`, `online` |
| `combat_start` / `combat_resume` / `combat_update` / `combat_end` | Battles |
| `level_up` | After victory |
| `inventory_update` / `shop_list` | Economy |
| `item_used` | Consumable result (`healed`, `teleported`, `repel_steps`, `message`) |
| `rest_ok` | Inn result or preview (`cost`, `character`, `message`) |
| `spell_cast` | Field magic result (`healed`, `teleported`, `repel_steps`, `radiant_steps`, `character`) |
| `emote` | Nearby emote broadcast |
| `who` | `players`, `nearby_count`, `online`, `roster`, `zones`, `you` (`id`, `name`, `level`, `x`/`y`, `idle`, `in_combat`, `repel`, `radiant`, `zone`) |
| `look` | `player` card (`id`, `name`, `level`, `in_combat`, `nearby`, optional `x`/`y`) |
| `played` | `seconds`, `session_id`, `name`, `zone`, `online`, `nearby_count`, `afk`, `idle`, `message` |
| `zone` | `zone`, `x`/`y`, `zones`, `players` (same-zone cards), `population`, `online`, `session_id` |
| `status` | `character` (stats/spells/xp_progress), `you` (x/y/zone/repel/radiant/in_combat), `online` |
| `combat_update` | Includes `hero` public (status) + `legal_actions` with spell `name`/`mp_cost` |
| `online` | Global pulse: `online` count + `roster` (no positions) + `zones` counts; debounced ~150ms with delayed flush |
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
19. **`combat_engine.start` refuses to clobber** an ongoing battle (raises unless `replace=True`); encounter paths check `is_in_combat` first.
20. Move `seq`: bool rejected; digit **strings** coerced (`"2"` → 2); optional seq still allowed.
21. **`publish_move` mutates AOI under the per-loop lock**; network sends after unlock (avoid deadlock with `send`→`disconnect`).
22. Level-up → nearby **system** chat + roster pulse; `find` never returns coordinates.
23. **Disconnect leave** notifies geometric AOI **∪** cached `visible` (empty/corrupt visible must not leave ghost avatars).
24. **`publish_status`** (combat/level) uses geometric AOI **∪** cached `visible` (same as nearby chat).
25. `ids_nearby` only counts **live sockets** (orphan meta never appears nearby/find/roster).
26. Move **rate limit applies only after** adjacent+walkable validation (invalid steps do not burn budget).
27. Reserved chat channels rejected **before** chat rate limit (clear `reserved channel` reason).
28. Presence loop: **prune_stale_visible** every tick; full **reconcile_all_aoi** ~30s; online pulse includes **zones**.
29. `GET /health` includes `zones` counts (ops visibility).
30. Move coords must be **finite** (reject NaN/Inf/bool); `publish_move`/`set_position` refuse non-finite; corrupted meta pos recovers to spawn.
31. Inventory bag items include **`sell_price`** (half buy); shop catalog already does.
32. Moving updates **`last_seen`** (idle badge honest under walk-only play).
33. Online/find cards may include **`zone`** (town/field/dungeon) never x/y.
34. **`reply`** / last-whisper peer stored in meta + soft grace for reconnect.
35. Successful **sell** includes `sold` + `message` on `inventory_update` (`gold_gained`).
36. Chat and move both refresh **`last_seen`** (idle badges).
37. **`player_moved` includes `idle`**; find accepts **`zone`** filter / `zone:field` query suffix.
38. Find: empty name + zone lists zone roster; invalid zone → `invalid zone` error (not silent ignore).
39. Successful **buy** includes `bought` + `message` (`gold_spent`); not-enough-gold may include `cost`.
40. **Auth / sync `world_state`** always includes top-level `zone` and `you.zone` when position is known.
41. Successful **`move_ok` includes `zone`** (current tile zone after the step).
42. Crossing zone types (town↔field↔dungeon) emits nearby **system** chat: `"{name} entered the {zone}."` (same-zone steps stay quiet).
43. **`who.you`** includes `name`, `level`, `idle` (not only coords/buffs).
44. Open art: Kenney + Tiny Creatures CC0 via `tools/import_open_assets.py`; TC black mats punched to alpha; SVG companions in `svg/enemies/` for every enemy id (PNG is what the client loads).
45. Shop includes **leather_helmet** / **iron_helmet** (helmet slot); buy shortfalls include `cost` (client inventory toast shows need N G).
46. Status sheet may show **own** map position (`you.x`/`you.y`) — never leak other players’ coords via find/online.
47. Find: invalid zone token (`zone:moon`, field `zone=space`) → **`invalid zone`** even when name is empty (never `find query required`).
48. Move coords must be **finite integer-valued** (reject `3.7`; allow `3` / `3.0`). Truncation would desync clients.
49. Presence events (`player_joined` / `player_moved` / `player_update` / public meta) include **zone** when known.
50. `ids_in_zone` / zone chat only **live sockets** (orphan meta never receives zone traffic).
51. Online roster + find results sorted by name then id (stable multiplayer UI).
52. `/players` and msg types `players` / `online_list` alias **who** (rate-exempt).
53. **Shop list** refused in combat (`in combat`); buy/sell already combat-gated.
54. Shop catalog includes mid-tier **broad_sword** and **half_plate**.
55. `find_id_by_name` only resolves **live sockets** (orphan meta never whisper/look targets).
56. `/near` · `/here` (msg `near`/`nearby_list`/`here`) → nearby-only roster; rate-exempt.
57. `auth_ok` includes **welcome** string + online count (not a chat message).
58. `who` includes **nearby_count** matching `players` length.
59. `/zone` · `/where` (msg `zone`/`where`/`area`) → own zone, coords, zone population; rate-exempt.
60. Teleport/respawn **`move_ok` includes `zone`** (wings + death).
61. Shop catalog includes **full_plate** and **silver_shield**.
62. Whisper target validation (offline / self / ignore) runs **before** `allow_chat` so failed whispers never burn chat rate; global chat also **outbound.append** for reliable self-echo.
63. Chat (global/nearby/zone) + emote: **peers via broadcast, self via outbound once** (no double-echo).
64. `/zone` includes same-zone **players** roster (public cards) + `zone_count`.
65. Ignore list caches **names** (soft-grace) so offline targets stay labeled.
66. `pong` includes `zones`, `nearby_count`, `session_id` when authed.
67. Bag caps: **12** stacks · **8** per stack (`inventory full` / `stack full` on buy/equip/unequip).
68. Defeat broadcasts nearby **system** chat `"{name} was defeated!"` (both combat end paths).
69. Reserved hero names include god/null/npc/staff/… (spoof system identity).
70. `inventory_update` includes `bag: {used, max_slots, max_stack}` for client UI.
71. Whisper: `send()` failure → `player not online` (no self-echo / no reply peer note) + **`refund_chat`** so rate is not burned; if manual AFK was set pre-`allow_chat`, pass **`restore_afk=True`** + prior `afk_message`.
72. `sync` / join `world_state`: `zones`, `roster`, `nearby_count`, `session_id` for multiplayer resync.
73. `/roll` · `/dice` (msg `roll`/`dice`/`d100`) → nearby system 1dN (default 100); chat-rate limited.
74. Combat start → nearby system `"{name} is fighting!"` (not to self).
75. `discard` / `drop` destroys bag items (not equipped; blocked in combat) so full bags can free slots.
76. `disconnect(reason=…)` — idle kicks use `reason=idle` on `player_left`.
77. Combat end nearby system: victory / fled / defeat via `_announce_combat_outcome`.
78. `/counts` · `/census` (msg `counts`/`census`/`population`) — online + zone totals, no full roster.
79. `find` results include `zones` for multiplayer overview.
80. Inn: `rest` with `preview`/`quote` returns cost without charging; client R quotes then confirms.
81. Buy `stack full` / `inventory full` errors may include `bag` snapshot for UI.
82. `resolve_live_name`: exact match, else unique 2+ char prefix; ambiguous → `name ambiguous` (whisper/look/ignore).
83. `player_left` includes `zone` when known; `auth_ok` adds `nearby_count` + `zones`.
84. `look` card always includes **zone** (coords only when nearby).
85. Presence payloads carry **`session_id`**: `player_joined`, `player_moved`, `player_left`, `player_update` (reconnect hygiene).
86. Join path: `auth_ok` + first `world_state` include **`ignores`**, **`last_whisper`**, `repel`/`radiant` (soft-grace restore to client).
87. `manager.refund_chat(cid, *, restore_afk=False, afk_message=None)` clears `last_chat_at` after failed multiplayer delivery; optional restore of manual AFK + status (census honesty).
88. Combat soft-reconnect: after `connect`, if `in_combat` → `publish_status(..., pulse_online=True)`.
89. `player_left` on disconnect includes `session_id` from leaving meta when present.
90. Bare `look` (no name/id) examines **self**; empty name string same.
91. `version`/`ver`/`about` → `{version, online, zones, uptime, service}`; `time`/`uptime` → clock + `uptime_hms`.
92. `whoami` is a status alias; `pong` and `/health` include `version` + `uptime` (`PROCESS_STARTED_AT`).
93. Roll `sides`: never use `or` default (0 is falsy); valid range **2..1000** or `invalid roll sides` + `refund_chat`.
94. Discard `quantity`: never use `or 1` (0 must error `bad quantity`, not destroy one unit).
95. Look named offline → `player not online` (not `player not found`); bare look still self.
96. `_online_card` / `_public_meta` include `session_id` when set (roster reconnect hygiene).
97. Social activity (chat/whisper/emote) that clears idle → `publish_status` so AOI peers drop AFK.
98. Zone chat only from town/field/dungeon; otherwise `not in a zone` (no rate burn).
99. Emote payloads include `zone` when known.
100. `motd` / `rules` → MOTD text + version/online/zones/uptime (`config.MOTD`).
101. `afk`/`away` sets `meta.afk`; `back` clears; `_is_idle` true when afk; chat/move clears afk.
102. `block`/`unblock` aliases for ignore/unignore; `quit`/`logout` ack then `disconnect(reason=quit)`.
103. `sell` quantity: never ignore client qty — `qty<1` → `bad quantity`; supports multi-stack sell (equipped still qty 1 only).
104. Successful move after manual AFK → `publish_status` so AOI peers drop idle badge.
105. `sync` world_state rehydrates `ignores`, `last_whisper`, and `you.{afk,idle,session_id,in_combat}`.
106. `buy` quantity: never ignore client qty — `qty<1` → `bad quantity`; multi-buy supported (stack cap).
107. Zone aliases: `whereami`/`coords`/`pos`/`position`; status aliases: `stats`/`sheet`.
108. Quantity parse (`_parse_positive_qty`): reject bool + non-integer floats (2.5); accept ints, `2.0`, digit strings.
109. `disconnect` uses `broadcast_online_force` so leave roster updates are not lost to debounce.
110. Chat / whisper / emote stamp speaker `session_id`; look card includes `session_id` + `afk`; who.you includes `afk` + `session_id`.
111. `status.you` includes `afk` + `idle` (was missing after /afk).
112. Inventory aliases: `bag`/`inv`/`items`; `gold`/`money`/`wallet`; `spells`/`magic`/`spell_list`.
113. `_online_card` / `_public_meta` / `player_update` / join / move include **`afk`** (manual flag, separate from soft `idle`).
114. Whisper echo may set **`target_afk`** when recipient is AFK (delivery copy does not need it).
115. `lastwhisper` / `last` / `reply_to` / `who_last` → last `/r` peer (online/afk/session when live); soft grace keeps peer.
116. `player_left` (out_of_range) carries `session_id` when known (both sides).
117. Lightweight peeks: `hp`/`mp`/`vitals`/`life` → `vitals`; `xp`/`exp`/`level`/`experience` → `xp` (uses combat HP when fighting).
118. Equip/unequip return `inventory_update` with `equipped`/`unequipped` + `message`; unequip aliases `takeoff`/`remove`; rest alias `sleep`.
119. Auth join uses `broadcast_online_force` so roster `session_id`/AFK cards refresh immediately (not debounced).
120. `find` supports `afk:yes|no` (and bare `afk`) plus zone combos; `find_by_prefix(..., afk=)`.
121. `counts` and `roll` stamp speaker `session_id`; join `player_joined` includes `afk:false`.
122. Chat `channel=shout` maps to **zone** (area shout, not global).
123. Buy/sell bare or empty `item` → `item required` (not `unknown item`).
124. Find `afk:` token only accepts yes/no/1/0/true/false; else `invalid afk filter`.
125. `buffs`/`effects`/`debuffs` → repel/radiant/combat/AFK peek; `keys`/`controls`/`keybinds` → control summary.
126. `inspect` aliases look; `blocklist`/`blocks` alias ignores list; discard bare → `item required`.
127. `counts` includes `you` card (zone/afk/idle/session/nearby); find supports `idle:yes|no` (invalid → error).
128. Connect meta stores **`session_started`** (monotonic) for `/played`. **Live replace** and **soft-grace rejoin** preserve `session_started`; grace expiry / cold join → new age.
129. Look aliases: `profile`/`card`/`player_info`/`whereis`/`where_is`; zone aliases add `mapinfo`; version aliases add `server`/`info`.
130. Chat type `s`/`nearby_chat` → nearby; type `g` → global (channel override still wins when valid).
131. `played`/`session`/`session_time`/`online_time` → multiplayer snapshot + pretty `message` (rate-exempt in `main.py`).
132. `counts.you.played` = session age seconds; zone responses include `session_id`.
133. Tests: `test_mp_reliability_v0573` + `test_features_v0573` lock played/chat aliases + soft reconnect + regressions.
134. `stuck`/`unstuck`/`home` → town spawn (`SPAWN_X/Y`); `teleported:false` if already home; combat → `in combat`; uses `allow_chat`.
135. `yell`/`shout` message types force zone channel; `emotes` / `emote list` returns catalog without performing.
136. `stuck` already-home checks **before** `allow_chat` (no rate burn). Teleport path: clear AFK, `publish_move`, nearby system “returned to town”, `publish_status`.
137. Manual AFK stores `afk_since` (monotonic); look/who/public cards + buffs may include `afk_for` seconds.
138. AFK state flip → nearby system chat “is now AFK” / “is back”; `manager.mark_active` clears AFK on successful buy/sell/equip/use and optional `publish_status`.
139. `counts.you` may include `afk_for`; shop/buy/sell/use/equip require auth (`authenticate first`).
140. Auth `world_state`/`auth_ok` include `restored.{ignores,last_whisper,repel,radiant}` after soft grace; welcome may note restores.
141. Move while in combat → `error` + `move_ok ok=false` reason `in combat` (client reconcile); first join `restored` all false (no false "Restored" welcome).
142. **AFK status message:** `/afk lunch` · msg `afk`/`away` with `text`/`message`/`reason` (max 48, printable). Stored as `afk_message`. Cleared on `/back`, `mark_active`, move, chat. Soft reconnect always starts not-AFK.
143. `afk_message` on look card, who.you, counts.you, status.you, buffs, roster/`_online_card`/`_public_meta`, `player_update` when AFK.
144. Whisper sender echo: `target_afk` + optional `target_afk_message` (both whisper paths).
145. **`afk_count`** on `who`, `counts`/`census`, `online` pulse, `status` (live sockets with manual AFK).
146. System notice may include reason: `"{name} is now AFK: {reason}."`; flip-only (no spam on reason-only update).
147. Tests: `test_mp_reliability_v0582` + `test_features_v0582` lock AFK message + afk_count + soft reconnect ignore + yell regression.
148. **Item name resolve:** `resolve_item_id` on buy/sell/use/equip/discard — display names (`Copper Sword`), aliases (`herbs`/`wings`/`dragon scale`), unique prefixes (`copper`); ambiguous → `name ambiguous`.
149. **Roll sides validate before `allow_chat`** — invalid sides never burn rate or clear AFK (same pattern as empty chat / reserved channel).
150. **AFK census peeks:** `near` → `nearby_afk` + `afk_count`; `zone` → `zone_afk` + `afk_count`; `played`/`pong`/`find`/`version` carry `afk_count` (and nearby_afk on played/pong).
151. **`stuck` clears `afk_message`** with AFK flags so peers never see a stale AFK tip after home recall.
152. Tests: `test_mp_reliability_v0585` + `test_features_v0585`.
153. `GET /health` includes **`afk_count`**; unauthed **pong** includes global `afk_count`.
154. Already-home **`stuck`** calls `mark_active` (clears AFK reason, may `publish_status`).
155. `sync` world_state: `afk_count`, `nearby_afk`, `you.afk_message` when AFK.
156. **Password change:** `POST /auth/password` `{current_password,new_password}` (local accounts only; 401 if wrong current).
157. Tests: `test_features_v0586`.
158. **Directed emotes:** optional `to`/`name`/`to_id` on `emote`; validate before `allow_chat`; self/offline/ambiguous errors; `message` + `to`/`to_id`; far targets get a direct `send` if outside AOI.
159. `auth_ok` includes `afk_count`; welcome may note AFK online; `who.nearby_afk`; `motd.afk_count`.
160. Tests: `test_mp_reliability_v0587` + `test_features_v0587`.
161. Directed emote: target ignore either way → `player unavailable` / `you ignore that player` before rate; far `send` never bypasses ignore.
162. Tests: `test_adversarial_v0588`.
163. Rate-exempt inventory/shop/field/stuck/emote types so domain errors never look like `rate_limit` under peek spam.
164. Emote perform blocked **in combat** (`in combat`); `emotes` catalog still allowed.
165. New heroes start with **clothes** equipped (`equipment_armor`) + 3 herbs.
166. Tests: `test_features_v0589`.
167. **Emote shortcuts:** msg types `wave`/`bow`/`cheer`/`dance`/`cry`/`laugh`/`point`/`sit`/`think` perform that emote (optional `to`/`to_id`). Rate-exempt at global layer (own chat-rate).
168. **Last directed emote:** successful directed emote → `note_emote_to`; `lastemote` peek; `to:@last` / `to:last` / `to:!` / `reply:true` re-targets; soft-grace restores `last_emote_to_*`.
169. Failed directed (`no one to emote` / offline / ignore) validates **before** `allow_chat` (no AFK clear, no rate burn).
170. **`busy`** alias for AFK (reason text same as `/afk`).
171. **`nearby_combat`** census on `near`/`who`/`counts`/`pong`/`sync` world_state (AOI peers with `in_combat`).
172. Emote perform requires auth (`authenticate first`); catalog still unauth-ok.
173. Tests: `test_mp_reliability_v0590` + `test_features_v0590` + `test_adversarial_v0590`.
174. **`coerce_character_id` / `find_id_by_player_id`:** reject bool (`True→1` trap) and non-integer floats (`1.7→1`); accept ints, `1.0`, digit strings; `pid<=0` never resolves.
175. **Look** with explicit invalid `id`/`player_id` → `player not found` (never bare-self). Online-only cards still `player not online`.
176. **Directed emote** with explicit `to_id`/`player_id` that fails resolve → error (never undirected fall-through).
177. **AFK reason** only from real strings (never `str(True)` / `str(99)`); `sanitize_afk_message` rejects non-str.
178. Tests: `test_adversarial_hunt_v0591` (id coercion, AFK bool, lastemote offline, peek storm, combat gates).
179. **Meetup invite:** `invite`/`meet`/`beckon`/`come` — validate self/offline/ignore/ambiguous **before** `allow_chat`; private `invite` payload; coords only if target in AOI; echo may set `target_afk`; notes whisper peer for `/invite @last`; send fail → `refund_chat`.
180. Client wires `/busy`, `/lastemote`, `/invite`, census toasts (`nearby_combat` / AFK counts).
181. Tests: `test_features_v0592`.
182. **Invite memory:** successful invite → `note_invite_from` on target; soft-grace restores `last_invite_from_*`.
183. **`accept`/`coming` · `decline`/`later`:** answer last invite privately (`invite_reply`); validate offline/ignore before rate; send fail → `refund_chat`; failed accept with no invite does not burn AFK.
184. **`fighting` peek:** nearby in-combat public cards + `nearby_combat`; **`zone_combat`** on `/zone`.
185. Tests: `test_mp_reliability_v0593` + `test_features_v0593`.
186. **Accept/decline consume invite** (`clear_last_invite`) after successful delivery — no double-accept spam.
187. **Accept** notes whisper peers both ways so `/r` works after meetup accept.
188. **Roll sides:** reject non-integer floats (`2.7`) and bools before `allow_chat` (no AFK clear).
189. Tests: `test_adversarial_hunt_v0594`.
190. **Invite cancel:** `cancel`/`uninvite` — inviter clears `last_invite_to`; notifies target; clears target’s pending invite if still from inviter.
191. **Location share:** `share`/`sharepos` — private zone+coords to a player (whisper privacy); `@last` uses whisper/emote/invite peers; notes `/r` both ways; send fail → `refund_chat`.
192. Accept/decline also clears inviter’s `last_invite_to` when it points at acceptor.
193. Tests: `test_features_v0595`.
194. **`combat_count`:** live sockets with `in_combat` on who/counts/pong/online/health (alongside engine `combats`).
195. **Find `combat:yes|no`** / bare `fighting` filter (no coords); invalid → `invalid combat filter`.
196. **Cancel after accept:** only notifies guest if their `last_invite_from` still points at inviter (no spam cancel).
197. Tests: `test_mp_reliability_v0596`.
198. **Poke/nudge:** `poke`/`nudge`/`hey`/`attention`/`tap` — private attention ping; whisper privacy + ignore; `@last`; notes `/r` peers; send fail → `refund_chat(..., restore_afk=…)`.
199. Fighting peek includes global **`combat_count`**; client who/near/zone toasts show fighting census + ⚔/💤 name tags.
200. Tests: `test_features_v0597`.
201. **`_afk_snap(meta)`** before every private social `allow_chat`; on `send()` failure call `refund_chat(..., restore_afk=was_afk, afk_message=…)`. Paths: whisper, channel whisper, invite, share, poke, askwhere, thank, accept/decline.
202. **Askwhere:** `askwhere`/`ask_where`/`askpos`/`locate`/`whereru`/`where_r_u`/`whereyou` — private location request; whisper privacy + ignore; `@last`; notes `/r` both ways; target may `/share @last`; send fail → refund + restore AFK.
203. Failed accept/decline does **not** clear invite memory (retry possible); successful delivery still consumes invite.
204. Tests: `test_features_v0598` + `test_mp_reliability_v0598`.
205. **Offline invite answer:** accept/decline when inviter offline → clear `last_invite` + `invite_cleared` (no stuck loop); does not burn AFK.
206. **Thank:** `thank`/`thanks`/`ty`/`thx` — private ack; whisper privacy; `@last`; notes `/r`; send fail → refund+restore AFK.
207. Tests: `test_features_v0599` + `test_mp_reliability_v0599`.
208. **`clear_invite_from_peer` / `clear_invite_to_peer`:** clear matching invite pointers on live meta **and** soft-grace bags.
209. **Cancel:** always `clear_invite_from_peer(target, self)` (zombie-safe when guest offline).
210. **Offline accept/decline:** `clear_last_invite` + `clear_invite_to_peer(inviter, self)`.
211. Tests: `test_adversarial_hunt_v05100`.
212. **`note_invite_from`:** if guest already had another inviter, `clear_invite_to_peer(old, guest)`.
213. **`note_invite_to`:** if inviter re-targets, `clear_invite_from_peer(old_guest, inviter)`.
214. **`pending`/`invites`/`meetup`:** rate-exempt peek of incoming+outgoing meetup pointers.
215. Tests: `test_features_v05101` + `test_mp_reliability_v05101`.
216. **Invite deliver:** note whisper peers **both** ways (guest `/r` before accept).
217. **`invite_superseded`:** when `note_invite_from` replaces inviter, notify previous inviter if online.
218. **Retarget invite:** `note_invite_to` previous guest gets `invite_cancel` reason=retarget if online.
219. **`purge_expired_soft_grace`:** clear peer invite pointers for expired bags (to/from).
220. Tests: `test_features_v05102` + `test_mp_reliability_v05102`.
221. **Cancel / retarget notify:** skip send when `is_ignored_by(target, self)`; still clear pointers.
222. **Supersede notify:** skip if previous inviter ignores current inviter.
223. Tests: `test_adversarial_hunt_v05103`.
224. **`_social_alias` / `_resolve_social_peer`:** `@last` vs `@pending`/`@invite` for private social.
225. Cancel echo: `muted=True` + clearer message when notify skipped for ignore.
226. Tests: `test_features_v05104` + `test_mp_reliability_v05104`.
227. Whisper + channel-whisper + directed emote resolve `@pending`/`@last` via `_social_alias`.
228. Pending tokens require `@` prefix (`@pending` not bare `pending`).
229. Tests: `test_adversarial_hunt_v05105`.
230. **Look / ignore / unignore** resolve `@pending`/`@last` via `_social_alias` (online peers only).
231. Tests: `test_features_v05106` + `test_mp_reliability_v05106`.
232. **`social`/`peers`:** rate-exempt summary of whisper, invite_from/to, last emote peers; online peers include **`zone`** / **`in_combat`** (no coords); message shows `[town,afk,fight]` badges.
233. **`find`:** query `@pending`/`@last`/`@invite` resolves social peer → single online card (or error).
234. **Social find + filters:** when `@pending`/`@last` peer is online but zone/afk/idle/combat filter excludes them, FIND returns `count=0` with `filtered=true`, `filtered_peer`, `filter`, optional `peer_zone`, and `message` (never a silent empty roster).
235. **`pending` / `lastinvite`:** online peers include **`zone`** / **`in_combat`** (no coords); offline omits zone; messages use `[town,afk,fight]` badges.
236. **`find` prefix hits:** cards for the requesting character get **`you: true`** (self still counted).
237. **`find` free-text filters:** strip **all** `zone:/afk:/idle:/combat:` tokens in a loop (last wins); never leave residual tokens as a name prefix.
238. **`invite_reply` (accept/decline):** includes accepter **zone** + **nearby** (coords only if AOI-near); message says `from the field`.
239. Whisper/reply also accepts type **`r`** as alias for **`reply`**.
240. **`lastemote`:** peer zone/afk/in_combat badges like pending/lastinvite.
241. Tests: `test_features_v05107`–`v05111` + `test_mp_reliability_v05107`–`v05111` + `test_adversarial_hunt_v05110`.
242. **`social_peer_card` / `peer_status_suffix`:** shared peer cards for pending/lastinvite/lastemote/social; optional **`nearby`** (AOI) vs viewer without coords; badges include `near`|`far`.
243. **Whisper** (dedicated + channel=whisper) uses **`private_social_delivery`** (refund_chat + restore_afk).
244. Tests: `test_features_v05112` + `test_mp_reliability_v05112`.
245. **Directed far emote** (`/wave` outside AOI): uses **`private_social_delivery`**; fail → refund_chat + restore_afk; does **not** `note_emote_to`.
246. Directed emote self-echo may set **`target_afk`** / **`target_afk_message`**.
247. **`lastwhisper`/`last`:** `social_peer_card` + near/far badges (no coords).
248. Tests: `test_features_v05113` + `test_mp_reliability_v05113`.
249. **`handlers/session.py`:** ping + sync extracted (behavior unchanged).
250. **Invite cancel:** `notified` is true only when `manager.send` succeeds; echo may include **`nearby`**.
251. **`lastshare` / `note_share_to`:** soft-grace restore; social peers include **share** card; rate-exempt peeks.
252. Tests: `test_features_v05114` + `test_mp_reliability_v05114`.
253. **`@share` / `@lastshare`:** `_social_alias` → mode share; `_resolve_social_peer` uses `last_share_to`; bare `share` not an alias.
254. **`best_effort_send`:** invite supersede / retarget / cancel notify (no chat refund).
255. Tests: `test_features_v05115` + `test_mp_reliability_v05115`.
256. **`note_share_from` / `last_share_from`:** recipient of `/share` remembers sharer; soft-grace restore.
257. **`lastshare`:** `to` + `from` cards (`has_to`/`has_from`); back-compat `peer` = to then from.
258. **`@share` resolve:** last_share_to first, else last_share_from (recipient thank/whisper).
259. Tests: `test_features_v05116` + `test_mp_reliability_v05116`.
260. **`handlers/social_peeks.py`:** lastwhisper/social/lastemote/lastshare/lastinvite/pending extracted.
261. **`@from` / `@sharefrom` / `@sharedby`:** mode `share_from` → `last_share_from` only (not bare `from`).
262. **`@share`:** still to-first then from; **`@from`:** from only.
263. Tests: `test_features_v05117` + `test_mp_reliability_v05117`; combat gate flee waits for `combat_end`.
264. **`handlers/presence_peeks.py`:** who/near/counts/zone/fighting extracted.
265. **Auth/sync soft reconnect:** `last_share_to` / `last_share_from` cards + `restored.last_share` + welcome “share peers”.
266. Tests: `test_features_v05118` + `test_mp_reliability_v05118`.
267. **`note_emote_from` / `last_emote_from`:** directed emote recipient memory + soft-grace bag.
268. **`lastemote`:** to + from cards (like lastshare); **`social`** includes `emote_from`.
269. **`@emote` / `@lastemote`:** mode emote (to then from); **`@emotedby` / `@wavedby` / `@waved`:** emote_from only.
270. **Sync:** `last_emote_to` / `last_emote_from` peer cards on `world_state` (parity with share).
271. Failed far directed emote (private_social_delivery fail) must **not** note to or from.
272. Tests: `test_features_v05119` + `test_mp_reliability_v05119` (sync peers · fail no-from).
273. **`soft_reconnect_social_snapshot`:** shared helper for share · emote · invite peer cards (auth + sync).
274. **Auth/sync:** `last_invite_to` / `last_invite_from` + `restored.last_emote` / `restored.last_invite`.
275. Welcome restored bits: “emote peers” · “meetup invites” (with share / mute / whisper / buffs).
276. First join: new restored flags stay **false** (no false “Restored” welcome).
277. Tests: `test_features_v05120` + `test_mp_reliability_v05120`.
278. **`lastinvite`:** to + from cards (`has_to`/`has_from`); peer prefers from then to.
279. Soft-grace lastinvite still shows outgoing `to` after inviter reconnect.
280. Tests: `test_features_v05121` + `test_mp_reliability_v05121`.
281. **`soft_reconnect_social_snapshot`:** includes `last_whisper` social_peer_card + `has_whisper`.
282. Auth/sync `last_whisper` uses full peer card (near/far/zone), not bare `{id,name}` only.
283. **`lastwhisper`:** `has_peer` + near/far message badges; name-only offline fallback card.
284. Tests: `test_features_v05122` + `test_mp_reliability_v05122`.
285. Soft-grace bag stashes **`session_started`**; always bag if session stamp present.
286. Soft reconnect restores `/played` age; expired grace does not.
287. Tests: `test_features_v05123` + `test_mp_reliability_v05123` (+ v0573 continue).
288. **`soft_restored_session`** meta flag on soft-grace rejoin only (not live replace / first join).
289. **`build_soft_reconnect_restored` / `format_restored_welcome_bits`:** shared auth restored flags + welcome bits.
290. **`restored.played`** + welcome **session timer**; first join stays all-false for played.
291. Tests: `test_features_v05124` + `test_mp_reliability_v05124`.
292. **`ignore_list`:** online cards include **`nearby`** (AOI) + `online`/`offline`; offline keep cached names.
293. **`ignores` list:** `count` / `online_count` / `offline_count` + plain `message` summary.
294. Tests: `test_features_v05125` + `test_mp_reliability_v05125`.
295. **`handlers/look.py`:** look/examine/whereis extracted from message_handler.
296. Look response includes plain **`message`** + top-level **`nearby`**; coords only when near/self.
297. Tests: `test_features_v05126` + `test_mp_reliability_v05126`.
298. **`handlers/status.py`:** status/me/whoami/stats extracted from message_handler.
299. Status includes nearby_count/afk/combat, zones, plain **message**, optional social summary.
300. Tests: `test_features_v05127` + `test_mp_reliability_v05127`.
301. **`handlers/self_peeks.py`:** gold/money/wallet · hp/mp/vitals/life · xp/exp/level · spells/magic · buffs/effects extracted from message_handler.
302. Self peeks include **zone**, **in_combat**, **online**, **nearby_count** where useful; plain **message** always.
303. Empty buffs keep **`No active buffs.`** (optional zone suffix); non-empty may append nearby + zone bits.
304. Tests: `test_features_v05128` + `test_mp_reliability_v05128`.

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
| `tests.test_adversarial_hunt` | Neg seq, delete kicks, sell equipped, combat start no-overwrite, string seq, field shop, defeat gold |
| `tests.test_features_v0513` | Radiant light, char delete, XP progress |
| `tests.test_mp_look` | Look/examine, online debounce, 4-player stress, field spell in combat |
| `tests.test_mp_session` | session_id, level roster pulse, reconnect presence |
| `tests.test_mp_zone` | Zone chat, whisper-by-id, AOI rebuild, geometry-safe nearby |
| `tests.test_features_v0521` | status/me, legal_actions mp_cost, combat hero status |
| `tests.test_mp_find` | find prefix, level-up system chat, locked publish_move AOI |
| `tests.test_features_v0524` | help, pong server_t, defeat gold_lost |
| `tests.test_mp_ignore` | ignore/mute, idle roster, soft-grace, dead socket cleanup |
| `tests.test_mp_aoi_fix` | disconnect geometric leave, status AOI, zone counts, global ignore, reconnect storm |
| `tests.test_features_v0528` | invalid step no rate burn, reserved channel first, who zones |
| `tests.test_mp_presence_heal` | AOI prune/reconcile, online zones, health zones, 4-player chat |
| `tests.test_adversarial_nan` | NaN/Inf move rejection, meta recovery, no position corruption |
| `tests.test_features_v0531` | inventory sell_price, zone_counts repairs NaN meta |
| `tests.test_mp_reply_zone` | server reply whisper, roster zone, move clears idle, soft reconnect reply |
| `tests.test_features_v0533` | sell gold_gained + sold payload on inventory_update |
| `tests.test_mp_find_zone` | find zone filter, chat clears idle, player_moved idle |
| `tests.test_features_v0536` | buy gold_spent + cost on not-enough-gold |
| `tests.test_features_v0538` | leather/iron helmet shop, world_state/who.you zone, move_ok.zone + zone-enter system chat |
| `tests.test_adversarial_v0539` | find zone:moon → invalid zone; non-integer move rejected; whisper self blocked |
| `tests.test_features_v0544` | whisper self/offline must not burn chat rate; global self-echo |
| `tests.test_mp_reliability_v0545` | zone roster; chat/emote single self-echo; ignore names offline; pong zones |
| `tests.test_features_v0546` | bag stack/slot caps; defeat system chat |
| `tests.test_features_v0547` | bag meta on inventory; reserved God/null/NPC; empty chat no rate burn |
| `tests.test_mp_expand_v0548` | whisper send fail-closed; sync zones/roster; /roll; combat engage chat |
| `tests.test_features_v0549` | discard bag items; free slot; combat block |
| `tests.test_mp_expand_v0550` | /counts census; combat victory/fled notices; idle leave reason; find zones |
| `tests.test_features_v0551` | inn rest preview; buy bag-full error bag snapshot |
| `tests.test_mp_expand_v0552` | unique name prefix whisper; ambiguous; leave zone; auth nearby/zones |
| `tests.test_adversarial_v0553` | look zone when far; look ambiguous prefix; empty chat then real chat |
| `tests.test_mp_reliability_v0554` | session_id on presence; chat refund; soft-grace ignores/last_whisper on auth |
| `tests.test_features_v0555` | bare look self; version/about; time/uptime; whoami; pong+health uptime |
| `tests.test_adversarial_v0556` | roll sides=0 not d100; invalid sides; discard qty=0 no burn |
| `tests.test_mp_reliability_v0557` | look offline reason; roster session_id; idle clear on chat; zone gate; emote zone |
| `tests.test_features_v0558` | motd; afk/back; block alias; quit leave; help cmds; chat clears afk |
| `tests.test_adversarial_v0559` | sell qty=0/− not sell; multi-sell; bool qty rejected |
| `tests.test_mp_reliability_v0560` | move clears AFK for peers; sync rehydrates ignores/last_whisper |
| `tests.test_features_v0561` | buy qty=0; multi-buy; whereami/coords; stats/sheet aliases |
| `tests.test_adversarial_v0562` | fractional qty rejected; int-float + digit-string qty ok |
| `tests.test_mp_reliability_v0563` | force online on leave; session_id on chat/emote; look/who afk |
| `tests.test_mp_reliability_v0565` | afk on presence/online; whisper target_afk; lastwhisper; soft-grace last peer |
| `tests.test_features_v0566` | vitals/xp peeks; equip message; takeoff/remove; sleep; help cmds |
| `tests.test_mp_reliability_v0567` | force join online; find afk; roll/counts session_id; zone ignore; replace count |
| `tests.test_adversarial_v0568` | bare buy/sell; shout=zone; invalid afk filter; sell equipped; ignore self |
| `tests.test_features_v0569` | buffs/repel; keys; inspect; blocklist; discard bare; help |
| `tests.test_mp_reliability_v0570` | counts.you; find idle; soft restored flags; shout ignore; replace |
| `tests.test_adversarial_v0571` | combat move gate; first-join restored; ignore whispers; concurrent peeks |
| `tests.test_mp_reliability_v0573` | played snapshot; s/g chat; live-replace timer; soft ignore; whisper/who regression |
| `tests.test_features_v0573` | played unauth; rate-exempt peeks; empty s chat; help whereis |
| `tests.test_adversarial_v0574` | combat gates; g/s channel override; qty/move edges; AFK whisper; auth fails |
| `tests.test_features_v0575` | stuck/home town return; yell/shout zone; emote list catalog; help |
| `tests.test_mp_reliability_v0576` | stuck no rate burn; peer system notice; afk_for; yell/played regression |
| `tests.test_adversarial_v0577` | stuck auth/combat/home; ambiguous Adv*; clean ignore whisper; channel overrides |
| `tests.test_features_v0578` | buy/sell/use aliases; equip auto-slot; shop town gate; help |
| `tests.test_mp_reliability_v0579` | AFK system notices; buy clears AFK; counts.afk_for; shop unauth |
| `tests.test_adversarial_v0580` | AFK/back notices; combat shop/stuck; unauth shop; whisper after AFK cycle |
| `tests.test_features_v0581` | cast/repel aliases; cast clears AFK; discard; unauth cast |
| `tests.test_mp_reliability_v0582` | AFK status message; afk_count; whisper tip; soft reconnect ignore; yell |
| `tests.test_features_v0582` | /afk reason clamp; field aliases; unauth AFK; help hint |
| `tests.test_features_v0583` | resolve_item_id names/aliases; buy copper sword; equip/sell/discard |
| `tests.test_adversarial_v0583` | item resolve edges; bare item; AFK+buy clear; ambiguous equip |
| `tests.test_adversarial_v0584` | invalid roll keeps AFK; failed social AFK matrix; shop/combat gates; soft reconnect |
| `tests.test_mp_reliability_v0585` | nearby/zone AFK census; stuck clears reason; whisper/yell/who regression |
| `tests.test_features_v0585` | near unauth; played afk_message; version afk_count |
| `tests.test_features_v0586` | health/pong afk_count; stuck-home clears AFK; password change; sync |
| `tests.test_features_v0564` | status.you afk; bag/inv aliases; gold; spells |
| `tests.test_mp_reliability_v0540` | zone on presence, live zone chat, roster sort, /players alias |
| `tests.test_features_v0541` | shop blocked in combat; broad_sword/half_plate shop |
| `tests.test_mp_expand_v0542` | live name resolve, /near, auth welcome, who.nearby_count |
| `tests.test_features_v0543` | /zone, fairy water repel, wings zone, full_plate/silver_shield shop |
| `tests.test_mp_reliability_v0590` | wave shortcut; lastemote/@last; nearby_combat; busy; soft last-emote; whisper/yell |
| `tests.test_features_v0590` | unauth wave; no one to emote keeps AFK; help; version/starter |
| `tests.test_adversarial_v0590` | wave self/offline/ignore no rate; combat gate; peeks then wave |
| `tests.test_adversarial_hunt_v0591` | bool/float id traps; AFK non-str; lastemote offline; peek storm; combat matrix |
| `tests.test_features_v0592` | meetup invite; ignore gate; @last; help; busy; bool to_id |
| `tests.test_mp_reliability_v0593` | fighting peek; zone_combat; accept/decline; soft lastinvite; whisper |
| `tests.test_features_v0593` | unauth peeks; failed accept keeps AFK; help |
| `tests.test_adversarial_hunt_v0594` | double accept blocked; accept→/r; float roll sides; fighting self; ignore accept |
| `tests.test_features_v0595` | cancel invite; share location; share ignore; help |
| `tests.test_mp_reliability_v0596` | combat_count census; find combat filter; cancel after accept; share/whisper |
| `tests.test_features_v0597` | poke/nudge; ignore; bool to_id; fighting combat_count; help |
| `tests.test_features_v0598` | askwhere/locate; share @last loop; ignore; bool to_id; who census regression |
| `tests.test_mp_reliability_v0598` | refund_chat restore_afk unit; whisper/invite/share/poke/askwhere/accept fail restore AFK |
| `tests.test_features_v0599` | thank/ty; share→thank; ignore; bool to_id; help |
| `tests.test_mp_reliability_v0599` | offline invite clear; soft reconnect accept; thank fail restore AFK |
| `tests.test_features_v05127` | status message + multiplayer census WS |
| `tests.test_mp_reliability_v05127` | status extract unit · nearby census · social summary |
| `tests.test_features_v05128` | self peeks WS · version |
| `tests.test_mp_reliability_v05128` | self_peeks extract · gold/vitals/buffs MP context · xp/spells zone |
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
