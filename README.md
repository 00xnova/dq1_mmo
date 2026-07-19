# Dragon Quest 1 MMO

<p align="center">
  <img alt="banner" src="https://img.shields.io/badge/DQ1_MMO-Server--authoritative_multiplayer-1e1b4b?style=for-the-badge&labelColor=0f172a" />
</p>

<p align="center">
  <b>A Dragon Quest&nbsp;I–style multiplayer adventure</b><br/>
  <sub>One shared overworld · classic 1v1 combat · Love2D client · FastAPI server</sub><br/>
  <sub><b>v0.5.92</b> · <b>431</b> tests green · play with friends · docs for people ≠ agents</sub>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.92-7c3aed?style=for-the-badge" />
  <img alt="status" src="https://img.shields.io/badge/status-playable_MVP-16a34a?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-431_passing-059669?style=for-the-badge" />
  <img alt="stack" src="https://img.shields.io/badge/stack-Love2D_·_FastAPI_·_SQLite-0ea5e9?style=for-the-badge" />
  <img alt="docs" src="https://img.shields.io/badge/docs-humans_≠_agents-6366f1?style=for-the-badge" />
</p>

<p align="center">
  <a href="https://github.com/Im-Nova-Dev/dq1_mmo/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/Im-Nova-Dev/dq1_mmo?style=flat-square&color=fbbf24" /></a>
  <a href="https://github.com/Im-Nova-Dev/dq1_mmo/network/members"><img alt="forks" src="https://img.shields.io/github/forks/Im-Nova-Dev/dq1_mmo?style=flat-square&color=94a3b8" /></a>
  <a href="https://github.com/Im-Nova-Dev/dq1_mmo/issues"><img alt="issues" src="https://img.shields.io/github/issues/Im-Nova-Dev/dq1_mmo?style=flat-square" /></a>
  <a href="https://github.com/Im-Nova-Dev/dq1_mmo/commits/main"><img alt="last commit" src="https://img.shields.io/github/last-commit/Im-Nova-Dev/dq1_mmo?style=flat-square&color=6366f1" /></a>
  <img alt="python" src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="love2d" src="https://img.shields.io/badge/Love2D-11.x-EA316E?style=flat-square" />
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-WebSocket-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img alt="sqlite" src="https://img.shields.io/badge/SQLite-local_first-003B57?style=flat-square&logo=sqlite&logoColor=white" />
  <img alt="license" src="https://img.shields.io/badge/fan_project-not_Square_Enix-6b7280?style=flat-square" />
</p>

<p align="center">
  <a href="#-quick-start"><b>Quick start</b></a>
  ·
  <a href="#-whats-new"><b>What's new</b></a>
  ·
  <a href="#-highlights"><b>Highlights</b></a>
  ·
  <a href="#-controls"><b>Controls</b></a>
  ·
  <a href="docs/HUMAN.md"><b>Player guide</b></a>
  ·
  <a href="client/assets/ATTRIBUTION.md"><b>Art</b></a>
  ·
  <a href="#-documentation"><b>Docs map</b></a>
</p>

---

<p align="center">
  Explore <b>town</b>, <b>field</b>, and <b>dungeon</b> with other heroes on one shared grid.<br/>
  Server-side 1v1 · inn · shop · field magic · whisper · <b>/wave</b> · <b>/invite</b> · AFK · soft reconnect.
</p>

<p align="center">
  <img alt="zones" src="https://img.shields.io/badge/zones-town_·_field_·_dungeon-0ea5e9?style=flat-square" />
  <img alt="combat" src="https://img.shields.io/badge/combat-server_1v1-f43f5e?style=flat-square" />
  <img alt="social" src="https://img.shields.io/badge/social-whisper_·_/wave_·_/invite-8b5cf6?style=flat-square" />
  <img alt="mp" src="https://img.shields.io/badge/multiplayer-soft_reconnect_·_AFK-06b6d4?style=flat-square" />
  <img alt="shop" src="https://img.shields.io/badge/shop-friendly_names-eab308?style=flat-square" />
  <img alt="magic" src="https://img.shields.io/badge/magic-/cast_/repel_/return-a855f7?style=flat-square" />
  <img alt="afk" src="https://img.shields.io/badge/AFK-/busy_lunch-f97316?style=flat-square" />
  <img alt="meet" src="https://img.shields.io/badge/meetup-/invite_Name-ec4899?style=flat-square" />
  <img alt="acct" src="https://img.shields.io/badge/account-change_password-64748b?style=flat-square" />
  <img alt="bag" src="https://img.shields.io/badge/bag-12_×_8-f59e0b?style=flat-square" />
  <img alt="art" src="https://img.shields.io/badge/art-CC0_pixel_·_SVG-10b981?style=flat-square" />
  <img alt="suite" src="https://img.shields.io/badge/tests-431_green-059669?style=flat-square" />
</p>

> [!NOTE]
> **Fan project.** Inspired by *Dragon Quest I / Dragon Warrior*. **Not** affiliated with Square Enix.  
> **Two audiences on purpose:** people use this page + [HUMAN](docs/HUMAN.md) · coding agents use **[AGENTS.md](AGENTS.md) only** (never a player guide — no protocol dumps here).

<table>
<tr>
<td width="33%" valign="top" align="center">

### 👤 Players
**[docs/HUMAN.md](docs/HUMAN.md)**  
play · controls · hosting  
<sub>plain language only</sub>

</td>
<td width="33%" valign="top" align="center">

### 🎨 Artists
**[ATTRIBUTION.md](client/assets/ATTRIBUTION.md)**  
drop-in PNGs anytime  
<sub>CC0 · filenames are the contract</sub>

</td>
<td width="33%" valign="top" align="center">

### 🤖 Agents / LLMs
**[AGENTS.md](AGENTS.md) only**  
protocol · tests · reliability  
<sub>not a player guide</sub>

</td>
</tr>
</table>

<p align="center">
  <img alt="loop" src="https://img.shields.io/badge/loop-town_→_field_→_fight_→_shop_→_social-334155?style=for-the-badge" />
</p>

```text
  Register  →  Create hero (clothes + herbs)  →  Town (safe)
       │              │                              │
       │              └──── /shop · inn · equip ─────┤
       │                                              ▼
       └──────── /wave · /invite · /busy ◄── Field / Dungeon
                      │
                 /stuck home · logout
```

<table>
<tr>
<td align="center" width="20%"><b>🗺️ Play</b><br/><sub>shared grid</sub></td>
<td align="center" width="20%"><b>⚔️ Fight</b><br/><sub>server 1v1</sub></td>
<td align="center" width="20%"><b>🛒 Shop</b><br/><sub>friendly names</sub></td>
<td align="center" width="20%"><b>👋 Social</b><br/><sub>wave · invite</sub></td>
<td align="center" width="20%"><b>☕ AFK</b><br/><sub>/busy · /back</sub></td>
</tr>
</table>

<p align="center">
  <sub>
    <b>Docs stay split:</b>
    <a href="docs/HUMAN.md">players</a> ·
    <a href="client/assets/ATTRIBUTION.md">artists</a> ·
    <a href="AGENTS.md">agents only</a> ·
    <a href="docs/README.md">map</a>
  </sub>
</p>

---

## 📌 Contents

| | Section |
|:--|:--------|
| 🆕 | [What's new](#-whats-new) — **v0.5.92** |
| ✨ | [Highlights](#-highlights) |
| 🚀 | [Quick start](#-quick-start) |
| 🎮 | [Controls](#-controls) |
| 🎨 | [Look & art](#-look--art) |
| 👥 | [Multiplayer tools](#-multiplayer-tools) |
| ⚙️ | [Configuration](#️-configuration) |
| 📁 | [Project layout](#-project-layout) |
| 📚 | [Documentation](#-documentation) — **humans ≠ agents** |
| 🙏 | [Credits](#-credits) |

---

## 🆕 What's new

<p align="center">
  <img alt="latest" src="https://img.shields.io/badge/latest-v0.5.92-7c3aed?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/431_tests_green-059669?style=for-the-badge" />
</p>

<p align="center">
  <img alt="mvp" src="https://img.shields.io/badge/MVP-playable-16a34a?style=for-the-badge" />
  <img alt="ship" src="https://img.shields.io/badge/focus-social_·_shop_·_reliability-7c3aed?style=for-the-badge" />
  <img alt="split" src="https://img.shields.io/badge/docs-humans_≠_agents-6366f1?style=for-the-badge" />
</p>

| | **v0.5.92** — meetup invites + social polish |
|:--|:--|
| 🤝 | **`/invite Name`** · **`/meet @last`** — private meetup ask (**not** a party) |
| 👋 | **`/wave` · `/bow` …** · **`/wave @last`** · **`/lastemote`** |
| 💤 | **`/busy lunch`** (same as AFK) · clearer **`/who` · `/near`** peeks |
| 📊 | See AFK count and how many nearby heroes are fighting |
| ✅ | **431** automated tests green |

> [!TIP]
> **First hour:** register · create a hero (clothes + 3 herbs) · **`/buy copper sword`** · **`/wave Hero`** · **`/invite Hero`** · **`/busy lunch`** · **`/near`** · **`/stuck`** if lost.

<details>
<summary><b>Earlier releases</b></summary>

<br/>

| Version | Highlights |
|:--------|:-----------|
| **0.5.91** | Safer player IDs · clean AFK text · hunt suite |
| **0.5.90** | Emote shortcuts · lastemote · busy · nearby combat |
| **0.5.89** | Starter clothes + 3 herbs · no emotes mid-combat · shop under load |
| **0.5.88** | Directed emotes respect mute / ignore |
| **0.5.87** | `/wave Name` directed emotes · join AFK census |
| **0.5.86** | Health AFK count · change password · `/stuck` clears AFK |
| **0.5.85** | Near / zone AFK census peeks |
| **0.5.84** | Bad `/roll` no longer clears AFK |
| **0.5.83** | Friendly item names · `/buy copper sword` · aliases |
| **0.5.82** | AFK reason · how many AFK online · whisper tip |
| **0.5.81** | `/cast` field magic · `/discard` · cast clears AFK |
| **0.5.80** | Hardening · AFK / shop multiplayer edges |
| **0.5.79** | AFK/back lines · shop clears AFK · AFK duration peeks |
| **0.5.78** | `/buy` · `/sell` · `/use` · `/equip` · `/ping` · `/wave` |
| **0.5.77** | Hardening · stuck / AFK / ignore edges |
| **0.5.76** | Stuck rate fix · nearby return notice · AFK duration |
| **0.5.75** | `/stuck` · `/yell` · `/emote` list |
| **0.5.74** | Hardening · combat gates · AFK whisper · qty/move edges |
| **0.5.73** | `/played` · `/whereis` · reconnect timer · mute list |
| **0.5.72** | `/played` · `/profile` · `/mapinfo` · `/server` · `/s` `/g` |
| **0.5.71** | Hardening · combat move gate · clean first join |
| **0.5.70** | Counts self-card · find idle · soft restore flags |
| **0.5.69** | `/buffs` · `/keys` · `/inspect` · `/blocklist` |
| **0.5.68** | Shout = zone · bare buy/sell need an item |
| **0.5.67** | Join refreshes roster · `/find afk` |
| **0.5.66** | `/hp` · `/xp` · `/unequip` · `/last` · equip toasts |
| **0.5.65** | AFK on rosters · whisper tip · last-whisper after reconnect |
| **0.5.64** | `/gold` · `/spells` · bag aliases · status AFK |
| **0.5.63** | Faster leave roster · cleaner chat / look |
| **0.5.61–62** | Safer buy quantities · multi-buy |
| **0.5.60** | Walk clears AFK · reconnect keeps mute / whisper partner |
| **0.5.58–59** | MOTD · AFK · quit · sell qty fix |
| **0.5.55–57** | `/version` · `/time` · zone chat · safer roll/discard |
| **0.5.40–54** | Soft reconnect · zone social · bag limits · open art |

</details>

<p align="center">
  <a href="docs/HUMAN.md"><img alt="players" src="https://img.shields.io/badge/Players-docs%2FHUMAN.md-2563eb?style=for-the-badge" /></a>
  &nbsp;
  <a href="AGENTS.md"><img alt="agents" src="https://img.shields.io/badge/Agents%20%2F%20LLMs-AGENTS.md_only-7c3aed?style=for-the-badge" /></a>
</p>

---

## ✨ Highlights

<table>
<tr>
<td width="50%" valign="top">

### 🗺️ World & combat

| | |
|:--|:--|
| 🗺️ | Shared grid · safe **town** · field · **dungeon** |
| ⚔️ | Server-side DQ1 1v1 · reconnect mid-fight |
| 🏠 | Inn (quote then confirm) · shop · equip · sell · discard |
| ✨ | Heal · Return · **Repel** · **Radiant** · Outside |

</td>
<td width="50%" valign="top">

### 💬 Social & meta

| | |
|:--|:--|
| 💬 | Global · nearby · **zone** · **`/yell`** · whisper · **`/r`** · **`/roll`** |
| 👋 | **`/wave Name`** · **`/wave @last`** · **`/lastemote`** · **`/invite`** · **`/meet`** |
| 🔍 | **`/find`** · **`/who`** · **`/counts`** · **`/near`** · **`/zone`** · **`/whereis`** |
| 📊 | **`/hp`** · **`/xp`** · **`/gold`** · **`/buffs`** · **`/played`** · **`/bag`** |
| 🏠 | **`/stuck`** · **`/home`** free town return · soft reconnect |
| 🛒 | **`/buy copper sword`** · **`/sell`** · **`/use`** · **`/equip`** · **`/shop`** |
| ✨ | **`/cast`** · **`/repel`** · **`/return`** field magic from chat |
| ☕ | **`/afk lunch`** · **`/busy`** · **`/back`** |
| 🔑 | Email accounts can **change password** via API |
| 🦸 | Up to **3 heroes** · start with **clothes** + **3 herbs** |
| 🎨 | Drop-in PNGs · Kenney + Tiny Creatures **CC0** |

</td>
</tr>
</table>

| Also | |
|:-----|:--|
| **Start kit** | Gold · **3 herbs** · **clothes** equipped |
| **Items** | Herb · wings · fairy water · weapons · armor · helmets · Full Plate · Silver Shield |
| **Names** | Shop & gear accept **display names** or short unique nicknames (spaces OK) |
| **Bag** | **12** stacks · **8** each · **D** discard · sell/buy in town |
| **HUD** | HP/MP · gold · zone · position · nearby/online · repel · light · **F** status |
| **Shop UX** | Gold toasts · need-N-G · sell-back · **town only** (not in combat) |
| **Ops** | Health endpoint · AFK census · zone population |
| **Stability** | Server-authoritative movement · combat resume · soft reconnect · **431** tests |

> [!TIP]
> **Docs stay split on purpose.** Players use this page and [docs/HUMAN.md](docs/HUMAN.md). Coding agents use **[AGENTS.md](AGENTS.md) only** — never as a player guide.

**Not in this MVP:** parties · PvP · trade · quests · multi-map worlds.

---

## 🚀 Quick start

<p align="center">
  <img alt="py" src="https://img.shields.io/badge/need-Python_3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img alt="love" src="https://img.shields.io/badge/need-Love2D_11.x-EA316E?style=flat-square" />
  <img alt="port" src="https://img.shields.io/badge/port-8000-0ea5e9?style=flat-square" />
</p>

<table>
<tr>
<td width="50%" valign="top">

### 1 · Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./run.sh
```

| | |
|:--|:--|
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health |
| WebSocket | `ws://127.0.0.1:8000/ws` |

</td>
<td width="50%" valign="top">

### 2 · Client

```bash
love client
```

1. **Register** → hero (**clothes** + gold + **3 herbs**)
2. **N** new · **D**/**Y** delete · max **3**
3. **Enter World** → **town** (safe)
4. **R** inn · **`/shop`** · **`/buy copper sword`** · **`/wave`** when friends join

</td>
</tr>
</table>

### 3 · Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
# expect: 431 passed
```

---

## 🎮 Controls

<details open>
<summary><b>Overworld</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **WASD** | Move |
| **T** / **Y** | Global / nearby chat |
| **/say** · **/s** | Nearby chat |
| **/g** · **/global** | Global chat |
| **/w Name msg** | Whisper (unique **prefix** OK) |
| **/z msg** · **/yell msg** · **/shout msg** | Zone chat |
| **/stuck** · **/unstuck** · **/home** | Free return to town (not in combat) |
| **/emote** · **/emotes** · **/wave** · **/wave Name** · **/wave @last** | List, perform, or direct an emote |
| **/lastemote** | Who your last directed emote targeted |
| **/invite Name** · **/meet @last** | Private meetup invite (not a party) |
| **/busy [reason]** | AFK alias (same as **/afk**) |
| **/buy copper sword** · **/sell herb** · **/shop** | Town shop — **names or ids** (optional qty) |
| **/use herb** · **/equip copper sword** | Use consumable · equip gear (slot auto) |
| **/cast heal** · **/repel** · **/return** | Field magic (when learned) |
| **/discard fairy water** | Destroy bag items (optional qty) |
| **/ping** | Latency check |
| **/r message** | Reply last whisper |
| **/last** | Who `/r` will target |
| **/roll** · **/dice** · **/roll 20** | Nearby dice |
| **/counts** · **/census** | Online + zone totals |
| **/find Name** · **/find zone:town** · **/find afk** | Search online (no map coords) |
| **/who** · **/players** | Online + nearby + zones (**O**) |
| **/near** · **/here** | Heroes in view |
| **/zone** · **/where** · **/whereami** · **/mapinfo** | Your area + who is here |
| **/whereis Name** · **/profile Name** | Examine a hero (or yourself) |
| **/status** · **/me** · **/whoami** · **/stats** · **F** | Status sheet |
| **/hp** · **/vitals** | HP / MP peek |
| **/xp** · **/level** | Level + XP to next |
| **/buffs** · **/effects** | Repel · radiant · AFK |
| **/keys** · **/controls** | Keybind summary |
| **/gold** · **/money** | Wallet peek |
| **/spells** · **/magic** | Known battle + field spells |
| **/bag** · **/inv** · **/items** · **I** | Inventory / bag |
| **/inspect Name** · **/look Name** | Examine a hero |
| **/unequip slot** · **/takeoff slot** | Unequip weapon / armor / shield / helmet |
| **/version** · **/about** · **/server** · **/info** | Server version + uptime |
| **/time** · **/uptime** | Server clock + uptime |
| **/played** · **/session** | How long this session has been open (+ zone / online) |
| **/profile** · **/card** · **/whereis** | Look / examine a hero (or yourself) |
| **/mapinfo** | Same as **/zone** — area + who is here |
| **/motd** · **/afk [reason]** · **/busy [reason]** · **/back** · **/quit** | Welcome · AFK · leave world |
| **/block** · **/blocklist** · **/unblock** | Mute list helpers |
| **/ignore** · **/unignore** · **/ignores** | Mute list |
| **/inn** · **/rest** | Inn cost quote |
| **E** | Cycle emotes |
| **R** | Inn quote → **R** again to stay *(town)* |
| **H** / **M** | Field heal / cycle field spells |
| **K** | List spells |
| **L** | Look at a player (alone → yourself) |
| **I** | Inventory / shop |
| **Esc** | Disconnect & quit |

</details>

<details>
<summary><b>Combat</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** · **Enter** | Menu (spells show **MP cost**) |
| **1–9** | Jump to menu row |
| **A** / **F** / **H** | Attack · Flee · Herb |

</details>

<details>
<summary><b>Inventory</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **Enter** | Use / equip / buy |
| **S** | Sell *(town)* |
| **D** | Discard one unit |
| **U** | Unequip |
| **R** | Inn *(town)* |
| **Tab** | Shop *(town)* |

Bag: **12** kinds · **8** each · title shows **used/max**.

</details>

<details>
<summary><b>Hero select</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** · **Enter** | Select / enter world |
| **N** | New hero |
| **D** then **Y** | Delete hero |
| **Esc** | Log out |

</details>

### Chat slash commands

| Command | Effect |
|:--------|:-------|
| `/w Name message` | Whisper — full name or **unique prefix** |
| `/r message` | Reply last whisper |
| `/last` · `/lastwhisper` | See who `/r` targets |
| `/say` · `/s` · `/g` · `/z` · `/yell` · `/shout` | Nearby · global · zone chat |
| `/stuck` · `/unstuck` · `/home` | Free return to town |
| `/emote` · `/emotes` · `/wave` · `/wave Name` · `/wave @last` | List, perform, or direct an emote |
| `/lastemote` | Who you last directed an emote at |
| `/invite Name` · `/meet` · `/meet @last` | Meetup invite (private; not a party) |
| `/busy [reason]` | Same as `/afk` — show as away |
| `/shop` · `/buy copper sword` · `/sell herb 2` | Town shop — **friendly names** (optional qty) |
| `/use herbs` · `/equip copper sword` | Use / equip (names OK; slot auto) |
| `/cast heal` · `/repel` · `/return` | Field magic when learned |
| `/discard fairy water` | Destroy bag items |
| `/ping` | Latency check |
| `/roll` · `/dice` · `/roll 20` | Nearby dice (default d100) |
| `/counts` · `/census` | Online + zone population |
| `/find Name` · `/find zone:field` · `/find afk` | Search (zone / AFK filters, no coords) |
| `/who` · `/players` · `/near` · `/zone` | Rosters & area info |
| `/hp` · `/vitals` · `/xp` · `/level` | HP/MP · level + XP |
| `/buffs` · `/effects` | Repel · radiant · AFK flags |
| `/keys` · `/controls` | Keybind cheat sheet |
| `/gold` · `/spells` · `/bag` · `/inv` | Wallet · magic list · inventory |
| `/inspect Name` · `/look Name` · `/profile Name` · `/whereis Name` | Examine a hero |
| `/unequip weapon` · `/takeoff armor` | Unequip a gear slot |
| `/version` · `/server` · `/info` · `/time` · `/whoami` | Server info · self sheet |
| `/played` · `/session` | This connection’s age |
| `/mapinfo` · `/zone` · `/where` | Your area + who is here |
| `/motd` · `/afk [reason]` · `/busy [reason]` · `/back` · `/quit` | Welcome · AFK badge · leave world |
| `/block` · `/blocklist` · `/ignore` · `/unignore` · `/ignores` | Mute list |
| `/inn` · `/rest` | Inn cost quote |
| `/help` · **?** | Command list |

<p align="center">
  📖 <b>Player guide</b> → <a href="docs/HUMAN.md"><code>docs/HUMAN.md</code></a>
  &nbsp;·&nbsp;
  🤖 <b>Agents only</b> → <a href="AGENTS.md"><code>AGENTS.md</code></a>
</p>

---

## 🎨 Look & art

Drop PNGs into [`client/assets/`](client/assets/) — **filenames are the contract**.  
Missing files fall back to procedural drawing.

| Path | Files |
|:-----|:------|
| `tiles/` | `field` · `wall` · `town` · `water` · `dungeon` |
| `sprites/heroes/` | `hero.png` · `hero_battle.png` · `other.png` |
| `sprites/enemies/` | `{enemy_id}.png` (**40** enemies) |
| `svg/enemies/` | Editable SVG companions (optional) |
| `src/kenney/` · `src/tiny-creatures/` | CC0 masters |

```bash
./tools/gen_placeholder_assets.sh
python3 tools/import_open_assets.py --download
```

Licenses → **[client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)**

---

## 👥 Multiplayer tools

| Tool | Purpose |
|:-----|:--------|
| `./tools/mp_sim.sh` | Headless multiplayer bots |
| `./tools/mp_sim.sh -n 5 --scenario wander --seconds 30` | Custom load |
| `./tools/mp_love.sh 2` | Two Love2D windows on one machine |

---

## ⚙️ Configuration

Optional: copy [`.env.example`](.env.example) → `.env`

| Variable | Purpose |
|:---------|:--------|
| `ENV` | `development` / `production` |
| `SECRET_KEY` | JWT — **strong secret in prod** |
| `DATABASE_URL` | SQLite path |
| `ALLOW_DEBUG` | `1` enables debug encounters (**B**) |
| `STARTING_GOLD` | New hero gold |
| `COMBAT_GRACE_SECONDS` | Mid-battle reconnect window |
| `GOOGLE_CLIENT_*` | Optional Google OAuth |
| `CORS_ORIGINS` | Browser CORS allow-list |

**Production:** strong `SECRET_KEY` · `ENV=production` · `ALLOW_DEBUG=0` · durable DB · tight CORS.

**Account:** change password with a logged-in token — `POST /auth/password`  
`{ "current_password": "…", "new_password": "…" }` (email/password accounts only).  
See OpenAPI at `/docs` or [docs/HUMAN.md](docs/HUMAN.md#hosting-operators).

---

## 📁 Project layout

```text
dq1_mmo/
├── README.md                 ← you are here (humans / GitHub)
├── AGENTS.md                 ← coding agents & LLMs only
├── plan.md                   ← historical roadmap (not live truth)
├── docs/
│   ├── README.md             ← docs map & audience rules
│   └── HUMAN.md              ← players & operators
├── client/                   ← Love2D + assets
├── server/                   ← FastAPI · combat · WebSocket
├── shared/                   ← dq1_data.json
└── tools/                    ← multiplayer sims · asset import
```

---

## 📚 Documentation

<p align="center">
  <img alt="humans" src="https://img.shields.io/badge/humans-README_+_HUMAN.md-2563eb?style=for-the-badge" />
  &nbsp;
  <img alt="agents" src="https://img.shields.io/badge/agents-AGENTS.md_only-7c3aed?style=for-the-badge" />
  &nbsp;
  <img alt="suite" src="https://img.shields.io/badge/suite-431_green-059669?style=for-the-badge" />
  &nbsp;
  <img alt="ver" src="https://img.shields.io/badge/docs_@-v0.5.92-6366f1?style=for-the-badge" />
</p>

<p align="center">
  <b>Human</b> docs and <b>agent / LLM</b> docs stay separate on purpose.<br/>
  <sub>Players never need the protocol file. Agents should not treat the README as the contract.</sub>
</p>

> [!IMPORTANT]
> **Two audiences, two trees — do not mix.**  
> Play / host / art → this README + [docs/HUMAN.md](docs/HUMAN.md) + [ATTRIBUTION](client/assets/ATTRIBUTION.md).  
> Code agents → **[AGENTS.md](AGENTS.md) only** (protocol · tests · reliability).  
> **Never** paste WebSocket catalogs or test matrices into player-facing pages.

<table>
<tr>
<td width="55%" valign="top">

#### 👤 For people

| Document | Contents |
|:---------|:---------|
| **[README.md](README.md)** *(this page)* | Install · features · controls |
| **[docs/HUMAN.md](docs/HUMAN.md)** | Gameplay · inn · magic · social · hosting |
| **[client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)** | PNG names · CC0 licenses |
| **[docs/README.md](docs/README.md)** | Docs map & checklist |
| [plan.md](plan.md) | Historical only — **not** live truth |

</td>
<td width="45%" valign="top">

#### 🤖 For coding agents / LLMs

| Document | Contents |
|:---------|:---------|
| **[AGENTS.md](AGENTS.md)** | **Only** agent entry |
| | Protocol · hot paths · tests · reliability |

```text
┌──────── HUMANS ────────┐     ┌────── AGENTS ──────┐
│ README · HUMAN · Art   │  ≠  │ AGENTS.md ONLY     │
└────────────────────────┘     └────────────────────┘
```

</td>
</tr>
</table>

| Role | Start here |
|:-----|:-----------|
| **Player** | This README → [docs/HUMAN.md](docs/HUMAN.md) |
| **Host / ops** | [Quick start](#-quick-start) · [Configuration](#️-configuration) |
| **Artist** | [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md) |
| **Coding agent** | **[`AGENTS.md`](AGENTS.md) only** |

| Do | Don’t |
|:---|:------|
| Keep install & controls in human docs | Paste protocol catalogs into README / HUMAN |
| Put protocol, reliability, tests in `AGENTS.md` | Treat `plan.md` as the live backlog |
| Keep slash-commands accurate for players | Document unfinished features as shipped |
| Bump version badges when `VERSION` changes | Leave HUMAN / README out of date |

---

## 🙏 Credits

| | |
|:--|:--|
| **Inspiration** | *Dragon Quest I / Dragon Warrior* (NES-era combat math — not a ROM dump) |
| **Combat reference** | [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat) |
| **Art (CC0)** | [Kenney.nl](https://kenney.nl) · [Tiny Creatures](https://opengameart.org/content/tiny-creatures) — [ATTRIBUTION](client/assets/ATTRIBUTION.md) |
| **Disclaimer** | Fan project — **not** Square Enix |

---

<p align="center">
  <img alt="v" src="https://img.shields.io/badge/v0.5.92-7c3aed?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/431_tests-059669?style=for-the-badge" />
  <img alt="docs" src="https://img.shields.io/badge/docs-humans_≠_agents-6366f1?style=for-the-badge" />
</p>

<p align="center">
  <a href="docs/HUMAN.md"><img alt="player" src="https://img.shields.io/badge/📖_Player_guide-2563eb?style=for-the-badge" /></a>
  &nbsp;
  <a href="AGENTS.md"><img alt="agent" src="https://img.shields.io/badge/🤖_Agents_only-7c3aed?style=for-the-badge" /></a>
  &nbsp;
  <a href="docs/README.md"><img alt="map" src="https://img.shields.io/badge/🗺_Docs_map-475569?style=for-the-badge" /></a>
  &nbsp;
  <a href="client/assets/ATTRIBUTION.md"><img alt="art" src="https://img.shields.io/badge/🎨_Art-10b981?style=for-the-badge" /></a>
</p>

<p align="center">
  <sub>Made for <b>people</b> first · coding agents use <b>AGENTS.md only</b> · fan project, not Square Enix</sub>
</p>
