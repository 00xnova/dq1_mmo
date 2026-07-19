# DQ1 MMO — Human guide

For **people**: players, operators, and human contributors.

| You want… | Open this |
|:----------|:----------|
| Install & overview | [../README.md](../README.md) |
| Docs map (human vs agent) | [README.md](README.md) |
| Swap sprites | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) |
| Protocol / AI agent notes | [../AGENTS.md](../AGENTS.md) — **agents only** |

**Version:** 0.5.19 · docs refreshed 2026-07-19

---

## What is this?

A multiplayer **Dragon Quest I–style** game:

- Account + hero (starting gold + **3 herbs**)
- Shared **town / field / dungeon** on one map
- Server-side combat (attack, magic, flee, herbs)
- Town **inn** and **field magic**
- Chat: **global**, **nearby**, **zone**, and **whisper**
- Emotes, **look** at other players, live **online roster**, status sheet (EXP to next)
- Shop, gear (sell equipped OK), swappable PNG art
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

Your current zone shows as a **ZONE** badge on the HUD.

---

## Combat

Menu: **Attack** · **Flee** · **Spells** · **Herb (H)**.

- Defeat → respawn in town, lose half your gold, partial HP
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

---

## Social

| Key / command | Effect |
|:--------------|:-------|
| **T** | Open chat (global channel) |
| **Y** | Open chat (nearby / AOI) |
| **/w Name message** | Whisper (private); also `/tell` |
| **/z message** | Zone chat — everyone in the same zone type (town / field / dungeon) |
| **E** | Cycle emotes (wave, bow, cheer, dance, …) |
| **F** | Status sheet (stats, gear, EXP to next, spells) |
| **O** or **P** / **Tab** | Who’s online · nearby list |
| **L** | Look at a nearby (or roster) adventurer |
| **C** | Toggle chat panel |

**HUD:** nearby · online · **repel N** · **light N** (Radiant) when active.  
**F** status sheet: level, EXP (+ to next), gold, gear, spells.  
**Online roster** shows names/levels (and ⚔ if in combat) — **not** map positions.

Chat tags in the log:

| Tag | Meaning |
|:----|:--------|
| *(none / accent)* | Global |
| `[near]` | Nearby (in view range) |
| `[zone]` | Same zone type |
| `[w]` | Whisper |

Only **online** characters can be whispered (by name).

---

## Controls (summary)

| Context | Keys |
|:--------|:-----|
| **Hero select** | ↑↓ · Enter · N new · D delete (Y confirm) · Esc logout |
| **Overworld** | WASD · T/Y chat · /w · /z · E · F · L · R · H/M · K · O · ? · I · Esc |
| **Combat** | ↑↓ · Enter · **1–9** menu · A / F / H |
| **Inventory** | Enter · R inn · S sell · U unequip · Tab shop |

---

## Hosting (operators)

```bash
cd server && source .venv/bin/activate && ./run.sh
```

| Check | |
|:------|:--|
| Health | `GET /health` |
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
# expect: 103 passed
```

---

## Humans vs agents

| Audience | Docs |
|:---------|:-----|
| **You (human)** | This file + [README](../README.md) |
| **Coding agents / LLMs** | [AGENTS.md](../AGENTS.md) for protocol, hot paths, tests, reliability |

Do **not** put long WebSocket protocol tables in human docs — they live only in `AGENTS.md`.
