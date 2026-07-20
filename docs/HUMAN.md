# DQ1 MMO — Human guide

<p align="center">
  <img alt="audience" src="https://img.shields.io/badge/audience-humans_only-2563eb?style=for-the-badge" />
  <img alt="version" src="https://img.shields.io/badge/version-0.5.139-7c3aed?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-719-059669?style=for-the-badge" />
  <img alt="split" src="https://img.shields.io/badge/agents-use_AGENTS.md_only-7c3aed?style=for-the-badge" />
</p>

For **people**: players, operators, and human contributors.  
Coding agents use **[AGENTS.md](../AGENTS.md) only** — you do **not** need that file to play or host.  
Protocol tables and test matrices stay **out** of this guide.

| You want… | Open this |
|:----------|:----------|
| Install & overview | [../README.md](../README.md) |
| Docs map (human vs agent) | [README.md](README.md) |
| Swap sprites / art | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) |
| Protocol / AI agent notes | [../AGENTS.md](../AGENTS.md) — **coding agents only** |

**Version:** 0.5.139 · **719** tests · matches `server/config.py` → `VERSION`

**Recent for players/ops (v0.5.139):** **`/share Hero`** confirms with near/far · they still receive your zone and map spot · failed shares restore AFK · **@share** / **@from** memory still soft-reconnects · **719** tests.

> [!TIP]
> **Share your spot:** **`/share Hero`** (or after **`/askwhere`**, they **`/share @last`**) — they get zone + coords; you see near/far. Soft reconnect keeps **@share** / **@from**.  
> **Thank someone:** **`/thank Hero`** or **`/ty @from`** after a share — you see near/far (and zone); they get a private thanks. Failed delivery refunds chat rate and restores AFK.  
> **Poke a friend:** **`/poke Hero`** or **`/nudge @last`** — you see near/far (and zone); they get a private “trying to get your attention.” Failed delivery won’t leave you stuck rate-limited or wrongly AFK.  
> **Find friends:** **`/find Hero`** · **`/find zone:field`** · **`/find combat:yes`** — you get a plain line (how many matched · how many online), never someone else’s map coords.  
> **Step away cleanly:** **`/afk lunch`** · **`/back`**. **Mute:** **`/ignore`** · **`/ignores`** · **`/unignore`**.

---

## What is this?

A multiplayer **Dragon Quest I–style** game on one shared map.

| Pillar | What you get |
|:-------|:-------------|
| **Hero** | Account · up to **3** heroes · start with gold + **3 herbs** + **clothes** |
| **World** | **Town** (safe) · **field** · **dungeon** · shared grid |
| **Combat** | Server-side 1v1 · attack · magic · flee · herbs |
| **Town life** | Inn · shop · **`/buy copper sword`** (friendly names) · equip · **`/discard`** (bag **12×8**) |
| **Magic** | Field heal · return · repel · radiant · outside · **`/cast`** from chat |
| **Social** | Global · nearby · zone · yell · whisper · `/r` · invite / cancel / pending · **share** · **`/lastshare`** · **`@share`** / **`@from`** · **wave** · **`/lastemote`** (to + from) · **`@emote`** / **`@emotedby`** · askwhere · thank · poke · accept / decline · fighting · social (near/far) · emotes · roll · **look** (near coords · far zone · plain line) · find · who |
| **Peeks** | **`/hp`** · **`/xp`** · **`/gold`** · **`/buffs`** · **`/played`** · **`/version`** · **`/time`** · **`/ping`** · **`/bag`** · **`/status`** · nearby combat · zone population |
| **Meta** | **`/afk lunch`** · **`/busy`** · soft reconnect ( **`/played` age** · **mute list near/far** · **last whisper** near/far · **share** · **emote** · **invite** peers · buffs) · **`/stuck` home** · **change password** · swappable PNG art |

**Not in the MVP:** parties · PvP · trade · quests · multi-map worlds.

---

## First session

1. Start the server · run `love client` (see [README](../README.md))
2. Register · create a hero (clothes + **3 herbs** + gold) · **Enter World**
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
| **/z message** · **/yell message** · **/shout message** | Zone chat — everyone in the same zone type (town / field / dungeon); not world-wide |
| **/stuck** · **/unstuck** · **/home** | Free return to town spawn if you’re lost (not during combat; nearby heroes may see a short system line; confirm notes online/nearby) |
| **/emote** · **/emotes** · **/wave** · **/wave Name** · **/wave @last** · **/wave @emotedby** | List emotes, perform one, or direct an emote at a hero |
| **/lastemote** | Who you last waved **at** and who last waved **at you** (near/far when online) |
| **/w @emote** · **/wave @emote** | Reuse who *you* last directed an emote at (**@** required) |
| **/w @emotedby** · **/wave @emotedby** | Reuse who last directed an emote *at you* (**@** required) |
| **/invite Name** · **/meet Name** · **/meet @last** | Private meetup invite (not a party) — they get a toast with your zone · **/accept** or **/decline** |
| **/accept** · **/coming** · **/decline** · **/later** | Answer the last invite you received (one answer only) |
| **/cancel** · **/uninvite** | Take back **your** last invite (they get a notice) |
| **/share Name** · **/share @last** | Privately share your **zone and map position** (opt-in only) · near/far confirm for you |
| **/askwhere Name** · **/locate @last** | Ask them where they are — they can **/share @last** to answer · near/far confirm |
| **/thank Name** · **/ty @last** | Private thanks (handy after someone shares a location) · near/far confirm |
| **/poke Name** · **/nudge @last** | Private “trying to get your attention” (not a party) · confirm near/far · zone |
| **/lastinvite** | Who last invited you **and** who you last invited (near/far when online) |
| **/pending** · **/invites** · **/meetup** | Pending meetup invites (incoming + outgoing) |
| **/social** · **/peers** | Whisper · invite · emote peers (online/offline) |
| **/find @pending** · **/find @last** | Find your meetup or last social peer online |
| **/fighting** · **/combats** | List nearby heroes currently in combat |
| **/shop** · **/buy copper sword** · **/sell herb 2** | Town shop — **display names or ids** (spaces OK; unique short names work) |
| **/use herbs** · **/equip copper sword** | Use a consumable · equip gear (slot chosen automatically) |
| **/cast heal** · **/repel** · **/return** · **/outside** · **/radiant** | Field magic when you know the spell (same as **H**/**M** keys) |
| **/discard fairy water** · **/discard herb 2** | Destroy items from the bag |
| **/ping** | Check connection latency |
| **/emote wave** · **/e wave** | Emote by name (also **E** cycles) |
| **/roll** · **/dice** · **/roll 20** | Nearby dice roll (default d100) · plain line with zone · nearby |
| **/counts** · **/census** | Online + nearby + zone population totals |
| **E** | Cycle emotes (wave, bow, cheer, dance, …) |
| **F** | Status sheet — stats, gear, EXP, spells, zone, buffs, nearby census |
| **/status** or **/me** or **/whoami** | Status sheet via chat — HP/MP plus nearby counts and a plain summary |
| **/version** · **/about** · **/server** · **/info** | Server version + online census + plain summary (nearby when you’re logged in) |
| **/time** · **/uptime** | Server clock / uptime + online census · plain summary |
| **/played** · **/session** | How long **this connection** has been open (not lifetime playtime) — survives a brief disconnect · zone · fighting · nearby when useful |
| **/motd** · **/rules** | Message of the day + online census |
| **/afk** · **/away** · **/busy** · **/back** | Show AFK on the roster. Optional reason: **`/afk lunch`** or **`/busy lunch`** (nearby heroes may see it; looks & whispers can show the tip). Confirmations note zone · nearby · online. Clears when you chat, emote, **walk**, or shop/use items |
| **/block Name** · **/unblock Name** | Same as ignore / unignore |
| **/quit** · **/logout** | Leave the world gracefully (farewell may note your zone) |
| **/find Name** | Search who’s online by name prefix (zone type only — no positions) · plain summary + online census |
| **/find Name zone:field** | Same, limited to town / field / dungeon |
| **/find zone:town** | List everyone in that zone (still no map positions) |
| **/find afk** · **/find afk:yes** | List heroes marked AFK (combine with `zone:…`) |
| **/find combat:yes** · **/find fighting** | List heroes currently in combat (no map positions) |
| **/find idle** · **/find idle:yes** | List idle heroes (AFK or soft timeout) |
| **/help** or **?** | Server list of commands / keys + online / AFK summary |
| **/ignore Name** | Mute chat/emotes from that hero — plain confirmation |
| **/unignore Name** | Stop ignoring — plain confirmation |
| **/ignores** · **/blocklist** | List who you are ignoring (online near/far · zone · names stay if they log off) |
| **/inspect Name** · **/profile Name** · **/card Name** · **/whereis Name** | Same as look / examine |
| **/who** | Online / nearby + zone counts + AFK / combat peeks (same as **O**) |
| **/players** | Same as `/who` |
| **/near** · **/here** | List heroes nearby (view range) — may note how many are AFK or fighting |
| **/zone** · **/where** · **/whereami** · **/coords** · **/mapinfo** | Your zone, map position, **who is here**, population by area |
| **/stats** · **/sheet** | Same as **/status** |
| **/gold** · **/money** | How much gold you have (zone · fighting when relevant) |
| **/hp** · **/vitals** · **/mp** | Quick HP / MP check (zone · fighting · nearby) |
| **/xp** · **/level** · **/exp** | Level and XP toward the next level (zone · nearby) |
| **/buffs** · **/effects** | Repel, radiant, AFK flags (zone when empty; nearby when active) |
| **/keys** · **/controls** | Keybind summary + online census |
| **/spells** · **/magic** | Known battle + field spells (zone) |
| **/bag** · **/inv** · **/items** | Open bag (same as **I**) |
| **/unequip slot** · **/takeoff slot** | Unequip weapon / armor / shield / helmet |
| **/r message** | Reply to the last whisper you got (works even after a brief reconnect) |
| **/last** · **/lastwhisper** | See who **/r** will reply to (near/far when online) |
| **/** | Open chat ready for a slash command |
| **O** or **P** / **Tab** | Who’s online · nearby list *(zone counts on who)* · `/players` same as `/who` |
| **L** · **/look** · **/look Name** | Look at a nearby or online adventurer — alone, looks at yourself · far targets show zone only (no map coords) |
| **C** | Toggle chat panel |

**HUD:** nearby · online · **repel N** · **light N** (Radiant) when active.  
**F** status sheet: level, EXP (+ to next), gold, **zone**, **your map position** (x, y), repel/light steps, ATK/DEF bonuses, gear, spells.  
**Online roster** (O / player list) shows names/levels, zone type, ⚔ in combat, idle/AFK — **not** map positions for online list.  
Nearby list still shows coordinates for people you can see.  
**`/zone`** also lists heroes currently in the **same zone type** as you (names & levels — not map coordinates of others).  
Roster updates also keep **town / field / dungeon** counts so you can see where people are gathering.

Your own chat and emotes always appear once in your log (global, nearby, and zone).  
Failed whispers and private social messages (yourself, offline targets, or a dropped connection) do **not** block the next message you try to send — and if you were AFK, your AFK badge stays on after a failed delivery.  
If someone invited you and then went offline, **`/accept`** or **`/decline`** clears that stuck invite so you are not stuck forever.

**Brief disconnects (~1 minute):** your **mute list**, **last whisper partner** (full near/far card so **`/r`** still works), **share partners** (`@share` / `@from`), **emote partners** (`@emote` / `@emotedby`), **meetup invite peers** (`/pending` / `/lastinvite`), and **Repel / Radiant** buffs come back when you rejoin — and your **`/played`** timer keeps counting. The welcome toast may list what was restored (including **session timer** for `/played`). Other players see a cleaner join/leave when someone reconnects.  
Chatting, whispering, emoting, or **walking** clears your **AFK** badge for people nearby. **Zone chat** only works while you are in town, field, or dungeon.

**Two-way social memory (plain language):** after you **`/share`**, **`/wave`**, or **`/invite`**, partners are remembered when possible — and a brief disconnect keeps them. Always type the **`@`**.

| Shortcut | Points to | Survives soft reconnect? |
|:---------|:----------|:-------------------------|
| **`@share`** | who *you* last shared your spot with | yes |
| **`@from`** | who last shared *their* spot with you | yes |
| **`@emote`** | who *you* last waved / emoted at | yes |
| **`@emotedby`** | who last waved / emoted *at you* | yes |
| **`@last`** | last whisper / social peer (command-specific) | yes (whisper) |
| **`@pending`** | pending meetup invite peer | yes |

Handy: **`/lastshare`** · **`/lastemote`** · **`/lastinvite`** · **`/social`** · **`/pending`**.  
Example: **`/w @emotedby hi`** · **`/thank @from`** · **`/wave @emote`**.

Chat tags in the log:

| Tag | Meaning |
|:----|:--------|
| *(none / accent)* | Global |
| `[near]` | Nearby (in view range) |
| `[zone]` | Same zone type |
| `[w]` | Whisper |
| `[*]` | System (nearby level-up · zone-enter) |

Only **online** characters can be whispered (`/w Name message`). A **unique prefix** of the name is enough; if several players match, you get an error instead of a wrong target.  
**`/find`** never reveals map positions — only names, levels, combat flag, **zone type**, and AFK — never map coordinates of others.  
Filter with **`zone:town`**, **`zone:field`**, or **`zone:dungeon`** (also `in:field`).  
Bare **`/find zone:town`** lists all online heroes in town. Invalid zone names are rejected with an error.  
Whispering someone who is AFK still delivers the message; you get a short note that they may be away (and their reason, if they set one).

---

## Controls (summary)

| Context | Keys |
|:--------|:-----|
| **Hero select** | ↑↓ · Enter · N new · D delete (Y confirm) · Esc logout |
| **Overworld** | WASD · T/Y chat · /w · /z · /invite · /share · /askwhere · /thank · /poke · /shop · /cast · /afk · /stuck · /who · /find · E · F · L · R · H/M · K · O · I · Esc |
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
| Health | `GET /health` — `status`, `online`, **AFK count**, **zones** (town/field/dungeon), `combats` |
| API docs | `http://127.0.0.1:8000/docs` |
| Password | `POST /auth/password` with bearer token — `{current_password, new_password}` (email accounts) |

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
# expect: 719 passed
```

---

## Humans vs agents

| Audience | Docs | What belongs here |
|:---------|:-----|:------------------|
| **You (human)** | This file + [README](../README.md) | Install, controls, gameplay, hosting, art swap |
| **Coding agents / LLMs** | [AGENTS.md](../AGENTS.md) **only** | WebSocket protocol, reliability rules, test matrix |

You do **not** need agent docs to play or host.  
Agents should **not** copy protocol tables into this guide.  
Live version badges above match `server/config.py` → `VERSION` (**0.5.139** · **719** tests).

| Do | Don’t |
|:---|:------|
| Link to AGENTS if a developer needs the protocol | Paste protocol tables into this guide |
| Keep slash-commands accurate (`/w` `/askwhere` `/thank` `/share` `/cast` `/buy` `/stuck` …) | Document unfinished features as shipped |
| Use plain language for players | Leak message-type catalogs or test matrices |

Index & rules → [docs/README.md](README.md)
