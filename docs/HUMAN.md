# DQ1 MMO — Human guide

For **people**: players, operators, and human contributors.

| You want… | Open this |
|:----------|:----------|
| Install & overview | [../README.md](../README.md) |
| Docs map (human vs agent) | [README.md](README.md) |
| Swap sprites / art | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) |
| Protocol / AI agent notes | [../AGENTS.md](../AGENTS.md) — **coding agents only** (skip if you just want to play) |

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.60-7c3aed?style=flat-square" />
  <img alt="tests" src="https://img.shields.io/badge/tests-269-059669?style=flat-square" />
  <img alt="audience" src="https://img.shields.io/badge/audience-humans-2563eb?style=flat-square" />
</p>

**Version:** 0.5.60 · **269** tests · **humans here** · agents → [AGENTS.md](../AGENTS.md) only

---

## What is this?

A multiplayer **Dragon Quest I–style** game:

- Account + hero (starting gold + **3 herbs**)
- Shared **town / field / dungeon** on one map
- Server-side combat (attack, magic, flee, herbs)
- Town **inn** and **field magic**
- Chat: **global**, **nearby**, **zone**, **whisper**, and **system** (level-ups · zone-enter · fights · defeats)
- Emotes, **look**, **`/find`**, **`/who`** · **`/players`** · **`/near`** · **`/zone`** · **`/counts`**, **`/roll`**, **`/ignore`**, **`/r`** reply, **`/version`** · **`/time`**, online roster (idle/AFK clears when you chat), status sheet (**F** / `/status` / `/whoami`)
- Join toast with **online count** when you enter the world
- Shop, gear (through Full Plate / Silver Shield · sell-back toasts), **bag limits** (12 kinds · 8 each · **D** discard), swappable PNG art
- Up to **3 heroes** per account (create / delete)

**Not in the MVP:** parties, PvP, trade, quests, multi-map worlds.

---

## First session

1. Start the server · run `love client` (see [README](../README.md))
2. Register · create a hero · **Enter World**
3. You spawn in **town** (safe — no random fights)
4. A **welcome** toast shows how many heroes are online

Hero select: **N** new · **D** delete (confirm **Y**) · max 3 heroes.

---

## Zones

| Zone | Notes |
|:-----|:------|
| **Town** | Shop · **inn (R)** · no random encounters |
| **Field** | Random encounters |
| **Water** | Blocked |
| **Dungeon** | Harder fights · **Outside** spell exits to the field |

Your current zone shows as a **ZONE** badge on the HUD and on the **F** status sheet.  
Use **`/zone`** (or **`/where`**) anytime for your area, map position, **who is in the same zone**, and how many heroes are in town / field / dungeon.  
When someone nearby walks from town → field (or similar), you may see a short **system** line: *“Name entered the field.”*  
When a nearby hero starts a fight: *“Name is fighting!”*  
Battle ends nearby: *“was victorious!”* · *“fled battle!”* · *“was defeated!”*  
Someone AFK long enough may show as **went idle** when they leave your view.  
**`/who`** (or **O**) and **`/counts`** show online + zone totals.

---

## Combat

Menu: **Attack** · **Flee** · **Spells** · **Herb (H)**.

- Defeat → respawn in town, **lose half your gold** (shown as gold lost), partial HP
- Disconnect mid-fight: about **60 seconds** to reconnect and resume

---

## Inn

Press **R** in town to **see the inn cost**, then **R again** (within a few seconds) to rest and pay.

- Cost: **max(4, level × 4)** gold (free if already full HP/MP)  
- If you can’t afford it, the quote shows how much you need  
- Slash: **`/inn`** or **`/rest`** also requests a cost quote

---

## Field magic

| Key | Action |
|:---:|:-------|
| **H** | Heal / Healmore (if known) |
| **M** | Cycle field spells (Return, Repel, Outside, Radiant, …) |
| **K** | List field + battle spells you know |

| Spell | Effect |
|:------|:-------|
| **Return** | Warp to town |
| **Repel** | Fewer random fights (HUD: remaining steps) |
| **Radiant** | Soft light — fewer dungeon fights for a while (HUD: **light N**) |
| **Outside** | Leave dungeon → field |
| **Fairy Water** | Same idea as Repel (item) |

---

## Items

| Item | Effect |
|:-----|:-------|
| **Herb** | Heal (world + battle) |
| **Wings** | Warp to town |
| **Fairy Water** | Temporary repel |

In inventory: **Enter** uses consumables or equips gear (don’t equip herbs — use them).  
**Tab** opens the shop list in town.  
**Herbs** at full HP on the field are not consumed.  
You can **sell equipped** gear (the slot clears automatically).  
Shop listings show **buy** and **sell-back** prices (sell is half of buy).  
Your bag also shows each item’s **sell** value so you know what **S** will earn.  
After **buying** or **selling**, you see a toast with gold spent or gained.  
If you can’t afford an item, the toast shows **how much gold you need**.  
Helmets for sale include **Leather Helmet**, **Iron Helmet**, and **Dragon’s Scale**.  
Weapons include up through **Broad Sword**; armor includes **Half Plate** and **Full Plate**; shields up through **Silver Shield**.  
You cannot open the **shop** (or buy/sell) while in combat.  
Your bag holds up to **12** kinds of items, **8** of each (DQ-style limit). Buying more shows *stack full* or *inventory full*.  
Press **D** in the bag to **discard** one unit of the selected item (frees space; cannot undo).

---

## Social

| Key / command | Effect |
|:--------------|:-------|
| **T** | Open chat (global channel) |
| **Y** | Open chat (nearby) |
| **/say message** · **/s message** | Nearby chat (same as **Y**) |
| **/g message** · **/global message** | Global chat |
| **/w Name message** | Whisper (private); also `/tell` — **unique name prefix OK** (e.g. `/w Uni hi`) |
| **/z message** | Zone chat — everyone in the same zone type (town / field / dungeon) |
| **/emote wave** · **/e wave** | Emote by name (also **E** cycles) |
| **/roll** · **/dice** · **/roll 20** | Nearby dice roll (default d100) |
| **/counts** · **/census** | Online + nearby + zone population totals |
| **E** | Cycle emotes (wave, bow, cheer, dance, …) |
| **F** | Status sheet — refreshes from server (stats, gear, EXP, spells, zone, buffs) |
| **/status** or **/me** or **/whoami** | Same status sheet via chat |
| **/version** · **/about** | Server version + online count + uptime |
| **/time** · **/uptime** | Server clock and how long the world has been up |
| **/motd** · **/rules** | Message of the day |
| **/afk** · **/away** · **/back** | Show AFK on the roster (clears when you chat, emote, or **walk**) |
| **/block Name** · **/unblock Name** | Same as ignore / unignore |
| **/quit** · **/logout** | Leave the world gracefully |
| **/find Name** | Search who’s online by name prefix (zone type only — no positions) |
| **/find Name zone:field** | Same, limited to town / field / dungeon |
| **/find zone:town** | List everyone in that zone (still no map positions) |
| **/help** or **?** | Server list of commands / keys |
| **/ignore Name** | Mute chat/emotes from that hero |
| **/unignore Name** | Stop ignoring |
| **/ignores** | List who you are ignoring (names stay if they log off) |
| **/who** | Online / nearby + zone counts (same as **O**) |
| **/players** | Same as `/who` |
| **/near** · **/here** | List heroes nearby (view range) |
| **/zone** · **/where** · **/whereami** · **/coords** | Your zone, map position, **who is here**, population by area |
| **/stats** · **/sheet** | Same as **/status** |
| **/r message** | Reply to the last whisper you got (works even after a brief reconnect) |
| **/** | Open chat ready for a slash command |
| **O** or **P** / **Tab** | Who’s online · nearby list *(zone counts on who)* · `/players` same as `/who` |
| **L** | Look at a nearby (or roster) adventurer — alone, looks at yourself |
| **C** | Toggle chat panel |

**HUD:** nearby · online · **repel N** · **light N** (Radiant) when active.  
**F** status sheet: level, EXP (+ to next), gold, **zone**, **your map position** (x, y), repel/light steps, ATK/DEF bonuses, gear, spells.  
**Online roster** (O / player list) shows names/levels, zone type, ⚔ in combat, idle/AFK — **not** map positions for online list.  
Nearby list still shows coordinates for people you can see.  
**`/zone`** also lists heroes currently in the **same zone type** as you (names & levels — not map coordinates of others).  
Roster updates also keep **town / field / dungeon** counts so you can see where people are gathering.

Your own chat and emotes always appear once in your log (global, nearby, and zone).  
Failed whispers (yourself, offline targets, or a dropped connection) do not block the next message you try to send.

**Brief disconnects (~1 minute):** your **mute list**, **last whisper partner** (so **`/r`** still works), and **Repel / Radiant** buffs come back when you rejoin. Other players see a cleaner join/leave when someone reconnects.  
Chatting, whispering, emoting, or **walking** clears your **AFK** badge for people nearby. **Zone chat** only works while you are in town, field, or dungeon.

Chat tags in the log:

| Tag | Meaning |
|:----|:--------|
| *(none / accent)* | Global |
| `[near]` | Nearby (in view range) |
| `[zone]` | Same zone type |
| `[w]` | Whisper |
| `[*]` | System (nearby level-up · zone-enter) |

Only **online** characters can be whispered (`/w Name message`). A **unique prefix** of the name is enough; if several players match, you get an error instead of a wrong target.  
**`/find`** never reveals map positions — only names, levels, combat flag, and **zone type** (town/field/dungeon).  
Filter with **`zone:town`**, **`zone:field`**, or **`zone:dungeon`** (also `in:field`).  
Bare **`/find zone:town`** lists all online heroes in town. Invalid zone names are rejected with an error.

---

## Controls (summary)

| Context | Keys |
|:--------|:-----|
| **Hero select** | ↑↓ · Enter · N new · D delete (Y confirm) · Esc logout |
| **Overworld** | WASD · T/Y chat · /w · /z · /say · /g · /roll · /counts · /find · /who · /players · /near · /zone · /ignore · /status · /help · /r · E · F · L · R · H/M · K · O · I · Esc |
| **Combat** | ↑↓ · Enter · **1–9** menu · A / F / H |
| **Inventory** | Enter · R inn · S sell · D discard · U unequip · Tab shop |

---

## Art (swap anytime)

Game loads PNGs under `client/assets/`. **File names are the contract.**

| Folder | What |
|:-------|:-----|
| `tiles/` | Map tiles (field, wall, town, water, dungeon) |
| `sprites/heroes/` | You + other players |
| `sprites/enemies/` | One PNG per enemy id (`slime.png`, …) |
| `svg/enemies/` | Optional vector templates (game uses PNG) |

Current placeholders are **CC0** pixel art ([Kenney](https://kenney.nl) + [Tiny Creatures](https://opengameart.org/content/tiny-creatures)).  
Drop your own art over those files and restart Love2D. Full names & licenses → [ATTRIBUTION.md](../client/assets/ATTRIBUTION.md).

```bash
# regenerate from open packs (optional)
python3 tools/import_open_assets.py --download
```

---

## Hosting (operators)

```bash
cd server && source .venv/bin/activate && ./run.sh
```

| Check | |
|:------|:--|
| Health | `GET /health` — `status`, `online`, **`zones`** (town/field/dungeon), `combats` |
| API docs | `http://127.0.0.1:8000/docs` |

**Production checklist**

- Strong `SECRET_KEY`
- `ENV=production`
- `ALLOW_DEBUG=0`
- Durable `DATABASE_URL` path
- Tight `CORS_ORIGINS`

Env vars are listed in the [root README](../README.md#-configuration) and `.env.example`.

---

## Multiplayer on one PC

```bash
./tools/mp_sim.sh              # headless bots
./tools/mp_love.sh 2           # two Love2D windows
```

Automated tests (for contributors):

```bash
cd server && source .venv/bin/activate && python tests/run_tests.py
# expect: 269 passed
```

---

## Humans vs agents

| Audience | Docs | What belongs here |
|:---------|:-----|:------------------|
| **You (human)** | This file + [README](../README.md) | Install, controls, gameplay, hosting, art swap |
| **Coding agents / LLMs** | [AGENTS.md](../AGENTS.md) **only** | WebSocket protocol, reliability rules, test matrix |

You do **not** need agent docs to play or host.  
Agents should **not** copy protocol tables into this guide.  
Live version badges above match `server/config.py` → `VERSION` (**0.5.60** · **269** tests).

| Do | Don’t |
|:---|:------|
| Link to AGENTS if a developer needs the protocol | Paste protocol tables into this guide |
| Keep slash-commands accurate (`/w` `/z` `/say` `/g` `/roll` `/counts` `/find` `/who` `/players` `/near` `/zone` `/version` `/time` `/ignore` `/status`) | Document unfinished features as shipped |

Index & rules → [docs/README.md](README.md)
