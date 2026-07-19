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
| Auth JWT, equip/shop/sell/discard (bag caps), consumables, inn, field magic (radiant), XP, UI + PNGs | Final commercial art (placeholders OK to replace) |
| Char create/delete (max 3) · SQLite · free-port multiplayer tests · soft grace (buffs/ignore/last whisper) · AOI self-heal · online/health/find zones · buy/sell gold feedback · combat outcome system chat · zone on presence · `/players` · `/near` · `/zone` · `/counts` · auth welcome | Binary protocol |

**Version:** `0.5.66` (`server/config.py` → `VERSION`) · **301** tests in `server/tests/run_tests.py`  
**Docs:** humans → `README.md` + `docs/HUMAN.md` · agents → **this file only** (protocol / tests / reliability).  
When docs fire: sync version badges + test count; **never** copy protocol tables into human docs.  
Human entry points only: `README.md`, `docs/HUMAN.md`, `docs/README.md`, `client/assets/ATTRIBUTION.md`.  
Human “What’s new” should use plain language (no `session_id` / message-type catalogs / AOI jargon).  
GitHub README may use badges and callouts; still **no** protocol dumps.

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
| `chat` | `text`, optional `channel` | Default **global**; `nearby` AOI; `zone` same tile-zone; `whisper` + `to`/`to_id` |
| `say` | `text` | **Nearby** (AOI) chat |
| `whisper` / `tell` | `to` (name) and/or `to_id`/`player_id`, `text` | Private to one **online** player (echo to self) |
| `reply` | `text` (or whisper with `reply:true` / `to:@last`) | Reply to last whisper peer (server-tracked, soft-grace) |
| `emote` | `emote` | Nearby social: wave, bow, cheer, dance, cry, laugh, point, sit, think |
| `who` / `players` / `online_list` | — | Nearby players + `online` count + `zones` counts (town/field/dungeon); lightweight |
| `look` / `examine` | `name` or `player_id` | Public card; coords only if nearby. Rate-exempt. |
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
71. Whisper: `send()` failure → `player not online` (no self-echo / no reply peer note) + **`refund_chat`** so rate is not burned.
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
87. `manager.refund_chat(cid)` clears `last_chat_at` after failed multiplayer delivery.
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
| `tests.test_features_v0564` | status.you afk; bag/inv aliases; gold; spells |
| `tests.test_mp_reliability_v0540` | zone on presence, live zone chat, roster sort, /players alias |
| `tests.test_features_v0541` | shop blocked in combat; broad_sword/half_plate shop |
| `tests.test_mp_expand_v0542` | live name resolve, /near, auth welcome, who.nearby_count |
| `tests.test_features_v0543` | /zone, fairy water repel, wings zone, full_plate/silver_shield shop |
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
