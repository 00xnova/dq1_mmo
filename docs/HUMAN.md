# DQ1 MMO — Human guide

For **people**: players, operators, and human contributors.

| You want… | Open this |
|:----------|:----------|
| Install & overview | [../README.md](../README.md) |
| Docs map (human vs agent) | [README.md](README.md) |
| Swap sprites / art | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) |
| Protocol / AI agent notes | [../AGENTS.md](../AGENTS.md) — **coding agents only** (skip if you just want to play) |

**Version:** 0.5.41 · **175** tests · **humans here** · agents → [AGENTS.md](../AGENTS.md) only

---

## What is this?

A multiplayer **Dragon Quest I–style** game:

- Account + hero (starting gold + **3 herbs**)
- Shared **town / field / dungeon** on one map
- Server-side combat (attack, magic, flee, herbs)
- Town **inn** and **field magic**
- Chat: **global**, **nearby**, **zone**, **whisper**, and **system** (level-ups nearby; zone-enter notes)
- Emotes, **look**, **`/find`** (optional **zone:** filter), **`/who`** · **`/players`**, **`/ignore`** / **`/ignores`**, **`/r`** reply, online roster (idle/AFK), status sheet (**F** / `/status`)
- Shop, gear (sell-back prices + gold spent/gained toasts), swappable PNG art
- Up to **3 heroes** per account (create / delete)

**Not in the MVP:** parties, PvP, trade, quests, multi-map worlds.

---

## First session

1. Start the server · run `love client` (see [README](../README.md))
2. Register · create a hero · **Enter World**
3. You spawn in **town** (safe — no random fights)

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
When someone nearby walks from town → field (or similar), you may see a short **system** line: *“Name entered the field.”*  
**`/who`** (or **O**) also shows how many online players are in town, field, and dungeon.

---

## Combat

Menu: **Attack** · **Flee** · **Spells** · **Herb (H)**.

- Defeat → respawn in town, **lose half your gold** (shown as gold lost), partial HP
- Disconnect mid-fight: about **60 seconds** to reconnect and resume

---

## Inn

Press **R** in town for full HP/MP.

- Cost: **max(4, level × 4)** gold  
- If you can’t afford it, the client shows how much you need

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
Weapons include up through **Broad Sword**; armor includes **Half Plate**.  
You cannot open the **shop** (or buy/sell) while in combat.

---

## Social

| Key / command | Effect |
|:--------------|:-------|
| **T** | Open chat (global channel) |
| **Y** | Open chat (nearby) |
| **/w Name message** | Whisper (private); also `/tell` |
| **/z message** | Zone chat — everyone in the same zone type (town / field / dungeon) |
| **E** | Cycle emotes (wave, bow, cheer, dance, …) |
| **F** | Status sheet — refreshes from server (stats, gear, EXP, spells, zone, buffs) |
| **/status** or **/me** | Same status sheet via chat |
| **/find Name** | Search who’s online by name prefix (zone type only — no positions) |
| **/find Name zone:field** | Same, limited to town / field / dungeon |
| **/find zone:town** | List everyone in that zone (still no map positions) |
| **/help** or **?** | Server list of commands / keys |
| **/ignore Name** | Mute chat/emotes from that hero |
| **/unignore Name** | Stop ignoring |
| **/ignores** | List who you are ignoring |
| **/who** | Online / nearby + zone counts (same as **O**) |
| **/players** | Same as `/who` |
| **/r message** | Reply to the last whisper you got (works even after a brief reconnect) |
| **/** | Open chat ready for a slash command |
| **O** or **P** / **Tab** | Who’s online · nearby list *(zone counts on who)* · `/players` same as `/who` |
| **L** | Look at a nearby (or roster) adventurer |
| **C** | Toggle chat panel |

**HUD:** nearby · online · **repel N** · **light N** (Radiant) when active.  
**F** status sheet: level, EXP (+ to next), gold, **zone**, **your map position** (x, y), repel/light steps, ATK/DEF bonuses, gear, spells.  
**Online roster** (O / player list) shows names/levels, zone type, ⚔ in combat, idle/AFK — **not** map positions for online list.  
Nearby list still shows coordinates for people you can see.  
Roster updates also keep **town / field / dungeon** counts so you can see where people are gathering.

Chat tags in the log:

| Tag | Meaning |
|:----|:--------|
| *(none / accent)* | Global |
| `[near]` | Nearby (in view range) |
| `[zone]` | Same zone type |
| `[w]` | Whisper |
| `[*]` | System (nearby level-up · zone-enter) |

Only **online** characters can be whispered (by name: `/w Name message`).  
**`/find`** never reveals map positions — only names, levels, combat flag, and **zone type** (town/field/dungeon).  
Filter with **`zone:town`**, **`zone:field`**, or **`zone:dungeon`** (also `in:field`).  
Bare **`/find zone:town`** lists all online heroes in town. Invalid zone names are rejected with an error.

---

## Controls (summary)

| Context | Keys |
|:--------|:-----|
| **Hero select** | ↑↓ · Enter · N new · D delete (Y confirm) · Esc logout |
| **Overworld** | WASD · T/Y chat · /w · /z · /find · /who · /players · /ignore · /ignores · /status · /help · /r · E · F · L · R · H/M · K · O · I · Esc |
| **Combat** | ↑↓ · Enter · **1–9** menu · A / F / H |
| **Inventory** | Enter · R inn · S sell · U unequip · Tab shop |

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
# expect: 175 passed
```

---

## Humans vs agents

| Audience | Docs | What belongs here |
|:---------|:-----|:------------------|
| **You (human)** | This file + [README](../README.md) | Install, controls, gameplay, hosting, art swap |
| **Coding agents / LLMs** | [AGENTS.md](../AGENTS.md) **only** | WebSocket protocol, reliability rules, test matrix |

| Do | Don’t |
|:---|:------|
| Link to AGENTS if a developer needs the protocol | Paste protocol tables into this guide |
| Keep slash-commands accurate (`/w` `/z` `/find` `/who` `/players` `/ignore` `/status`) | Document unfinished features as shipped |

Index & rules → [docs/README.md](README.md)
