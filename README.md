# Dragon Quest 1 MMO

<p align="center">
  <img alt="banner" src="https://img.shields.io/badge/DQ1_MMO-Server--authoritative_multiplayer-1e1b4b?style=for-the-badge&labelColor=0f172a" />
</p>

<p align="center">
  <b>A Dragon Quest&nbsp;I–style multiplayer adventure</b><br/>
  <sub>Share one overworld · classic 1v1 combat · Love2D client · FastAPI server</sub>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.46-7c3aed?style=for-the-badge" />
  <img alt="status" src="https://img.shields.io/badge/status-playable_MVP-16a34a?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-197_passing-059669?style=for-the-badge" />
</p>

<p align="center">
  <a href="https://github.com/Im-Nova-Dev/dq1_mmo/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/Im-Nova-Dev/dq1_mmo?style=flat-square&color=fbbf24" /></a>
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
  <a href="#-controls"><b>Controls</b></a>
  ·
  <a href="#-whats-new"><b>What's new</b></a>
  ·
  <a href="#-highlights"><b>Highlights</b></a>
  ·
  <a href="docs/HUMAN.md"><b>Player guide</b></a>
  ·
  <a href="client/assets/ATTRIBUTION.md"><b>Art</b></a>
  ·
  <a href="#-documentation"><b>Docs map</b></a>
</p>

---

Explore **town**, **field**, and **dungeon** with other heroes on a shared grid.  
Fight server-authoritative 1v1 battles, rest at the **inn**, cast **field magic**, shop for gear (limited bag), and socialize — global / nearby / zone chat, whispers + **`/r`**, **`/find`**, **`/who`** · **`/players`** · **`/near`** · **`/zone`**, **`/ignore`**, emotes, and look.

> [!NOTE]
> **Fan project.** Inspired by *Dragon Quest I / Dragon Warrior*. **Not** affiliated with Square Enix.

<table>
<tr>
<td width="33%" valign="top" align="center">

### 👤 Players
[docs/HUMAN.md](docs/HUMAN.md)  
play · controls · hosting

</td>
<td width="33%" valign="top" align="center">

### 🎨 Artists
[ATTRIBUTION.md](client/assets/ATTRIBUTION.md)  
swap PNGs anytime

</td>
<td width="33%" valign="top" align="center">

### 🤖 Agents / LLMs
[AGENTS.md](AGENTS.md) **only**  
protocol · tests · not for players

</td>
</tr>
</table>

---

## 📌 Contents

| | Section |
|:--|:--------|
| 🆕 | [What's new](#-whats-new) — **v0.5.46** |
| ✨ | [Highlights](#-highlights) |
| 🚀 | [Quick start](#-quick-start) |
| 🎮 | [Controls](#-controls) |
| 🎨 | [Look & art](#-look--art) |
| 👥 | [Multiplayer tools](#-multiplayer-tools) |
| ⚙️ | [Configuration](#️-configuration) |
| 📁 | [Project layout](#-project-layout) |
| 📚 | [Documentation](#-documentation) — humans vs agents |
| 🙏 | [Credits](#-credits) |

---

## 🆕 What's new

<p align="center">
  <img alt="latest" src="https://img.shields.io/badge/latest-v0.5.46-7c3aed?style=flat-square" />
  <img alt="tests" src="https://img.shields.io/badge/tests-197_passing-059669?style=flat-square" />
  <img alt="mvp" src="https://img.shields.io/badge/MVP-playable-16a34a?style=flat-square" />
</p>

| | **v0.5.46** |
|:--|:--|
| 🎒 | **Bag limits** — 12 item kinds · max 8 each (DQ-style) |
| 💀 | Nearby heroes see when someone is **defeated** |
| 💬 | Slash: **`/say`** · **`/g`** · **`/emote`** · zone toast lists **who is here** |
| ✅ | **197** automated tests |

<details>
<summary><b>Earlier releases</b></summary>

<br/>

| Version | Highlights |
|:--------|:-----------|
| **0.5.45** | `/zone` who-is-here · reliable chat/emote self-echo · ignore names offline · richer pong |
| **0.5.44** | Failed whispers no longer block the next chat · global self-echo |
| **0.5.43** | `/zone` · wings/respawn zone · Full Plate / Silver Shield · fairy water |
| **0.5.42** | Welcome toast · `/near` · live name lookup |
| **0.5.41** | Shop combat gate · Broad Sword / Half Plate |
| **0.5.40** | Presence zone · `/players` · live zone chat |
| **0.5.39** | Invalid find zones · integer-only moves |
| **0.5.35–38** | Helmets · status position · zone find · gold toasts |
| **0.5.19–34** | Zone chat · `/r` · presence self-heal · open art |

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

### World & combat

| | |
|:--|:--|
| 🗺️ | Shared grid · safe **town** · field · **dungeon** |
| ⚔️ | Server-side DQ1 1v1 · reconnect mid-fight |
| 🏠 | Inn · shop · equip · sell equipped gear |
| ✨ | Heal · Return · **Repel** · **Radiant** · Outside |

</td>
<td width="50%" valign="top">

### Social & meta

| | |
|:--|:--|
| 💬 | Global · nearby · **zone** · whisper · **`/r` reply** · emotes |
| 🔍 | **`/find`** · **`/who`** · **`/players`** · **`/near`** · **`/zone`** · **`/ignore`** · look |
| 🦸 | Up to **3 heroes** · create / delete · XP to next |
| 🎨 | Drop-in PNGs · Kenney + Tiny Creatures **CC0** |

</td>
</tr>
</table>

| Also | |
|:-----|:--|
| **Items** | Herb · wings · fairy water · weapons · armor · **helmets** · Full Plate · Silver Shield |
| **Bag** | **12** stacks · **8** per stack · buy blocked when full |
| **HUD** | HP/MP · gold · zone · **your position** · nearby/online · repel · light · status (**F**) |
| **Shop UX** | Buy/sell gold toasts · need-N-G when short · sell-back · **town only** (not in combat) |
| **Stability** | Server-authoritative movement · combat resume · auto presence repair · **197** tests |

**Not in this MVP:** parties · PvP · trade · quests · multi-map worlds.

---

## 🚀 Quick start

| Need | |
|:-----|:--|
| **Python 3.11+** | 3.12–3.14 fine |
| **Love2D 11.x** | Game client |
| Port **8000** | Default (changeable) |

### 1 · Server

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./run.sh
```

| | URL |
|:--|:----|
| OpenAPI | http://127.0.0.1:8000/docs |
| Health | http://127.0.0.1:8000/health · online + zone counts |
| WebSocket | `ws://127.0.0.1:8000/ws` |

### 2 · Client

```bash
love client
```

1. **Register** → create a hero (gold + **3 herbs**)
2. Hero select: **N** new · **D** delete (**Y** confirm) · max **3** heroes
3. **Enter World** — spawn in **town** (safe) · welcome toast with online count
4. **R** inn · **I** bag/shop · field for fights · **F** status · **`/near`** / **`/zone`** for multiplayer awareness

### 3 · Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
# expect: 197 passed
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
| **/say msg** · **/s msg** | Nearby chat (slash) |
| **/g msg** · **/global msg** | Global chat (slash) |
| **/w Name msg** | Whisper (also `/tell`) |
| **/z msg** | Zone chat (same area type: town / field / dungeon) |
| **/emote wave** · **/e wave** | Emote by name |
| **/find Name** | Search online players by name prefix |
| **/find zone:town** | List everyone online in that zone |
| **/who** · **/players** | Online + nearby + zone counts (same as **O**) |
| **/near** · **/here** | Heroes in view range (names toast) |
| **/zone** · **/where** | Your zone, map position, **who is here**, population |
| **/status** · **/me** | Status sheet (same as **F** · shows zone & position) |
| **/help** · **?** | Command / key hints |
| **/ignore Name** | Mute a player's chat & emotes |
| **/unignore Name** | Unmute |
| **/ignores** | List who you muted (names kept if offline) |
| **/r message** | Reply to last whisper |
| **/** | Open chat with `/` draft |
| **E** | Cycle emotes |
| **F** | Status sheet (zone · your position · repel/light) |
| **R** | Inn rest *(town)* |
| **H** / **M** | Field Heal · cycle field spells |
| **K** | List known spells |
| **O** | Who’s online / nearby / zone counts |
| **L** | Look / examine a player |
| **P** / **Tab** | Toggle player list |
| **C** | Toggle chat panel |
| **I** | Inventory / shop |
| **B** | Debug slime fight *(if `ALLOW_DEBUG=1`)* |
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
| **Enter** | Use / equip |
| **S** / **U** | Sell · unequip |
| **R** | Inn *(town)* |
| **Tab** | Shop list *(town)* |

Bag holds **12** item kinds, up to **8** of each.

</details>

<details>
<summary><b>Hero select</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** | Select hero |
| **Enter** | Enter world |
| **N** | New hero |
| **D** then **Y** | Delete hero |
| **Esc** | Log out |

</details>

### Chat slash commands

| Command | Effect |
|:--------|:-------|
| `/say message` · `/s message` | Nearby chat |
| `/g message` · `/global message` | Global chat |
| `/w Name message` | Private whisper (`/tell` works too) |
| `/z message` | Zone chat (everyone in town *or* field *or* dungeon) |
| `/emote wave` · `/e wave` | Emote by name |
| `/find Name` | Online search by prefix — zone type only, **no map positions** |
| `/find Name zone:field` | Limit search to town / field / dungeon |
| `/find zone:town` | List everyone online in that zone (no coords) |
| `/who` · `/players` | Online roster + nearby + town/field/dungeon counts |
| `/near` · `/here` | Heroes in view range only (names toast) |
| `/zone` · `/where` | Your zone, position, **who is here**, area population |
| `/ignore Name` · `/unignore Name` | Mute / unmute chat & emotes |
| `/ignores` | List who you are ignoring (names stay after they leave) |
| `/status` · `/me` | Status sheet (stats, gear, EXP, **zone**, **your position**, buffs) |
| `/r message` | Reply to last whisper (works after a brief reconnect) |
| `/help` · **?** | Server command list |

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
| `sprites/enemies/` | `{enemy_id}.png` e.g. `slime.png` (**40** enemies) |
| `svg/enemies/` | Editable SVG companions (optional; game loads PNG) |
| `src/kenney/` | 16×16 Kenney masters (regen) |
| `src/tiny-creatures/` | 16×16 Tiny Creatures masters |

| Source | Used for | License |
|:-------|:---------|:--------|
| [Kenney.nl](https://kenney.nl) | Tiles, heroes, slimes, knights, mages, … | **CC0** |
| [Tiny Creatures](https://opengameart.org/content/tiny-creatures) | Dragons, wolves, golems, ghosts, … | **CC0** |

```bash
./tools/gen_placeholder_assets.sh
# re-download open packs:
python3 tools/import_open_assets.py --download
```

Licenses & file names → **[client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)**

---

## 👥 Multiplayer tools

```bash
./tools/mp_sim.sh                                    # headless bots
./tools/mp_sim.sh -n 5 --scenario wander --seconds 30
./tools/mp_love.sh 2                                 # two Love2D windows
```

---

## ⚙️ Configuration

Optional: copy [`.env.example`](.env.example) → `.env`

| Variable | Purpose |
|:---------|:--------|
| `ENV` | `development` / `production` |
| `SECRET_KEY` | JWT signing — **strong secret in prod** |
| `DATABASE_URL` | SQLite path |
| `ALLOW_DEBUG` | `1` enables debug encounters (**B**) |
| `STARTING_GOLD` | New hero gold |
| `COMBAT_GRACE_SECONDS` | Mid-battle reconnect window |
| `GOOGLE_CLIENT_*` | Optional Google OAuth |
| `CORS_ORIGINS` | Browser CORS allow-list |

**Production checklist:** strong `SECRET_KEY` · `ENV=production` · `ALLOW_DEBUG=0` · durable DB · tight CORS.

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
├── client/                   ← Love2D + assets (PNG / SVG companions)
├── server/                   ← FastAPI · combat · WebSocket
├── shared/                   ← dq1_data.json (canonical game data)
└── tools/                    ← multiplayer sims · asset import
```

---

## 📚 Documentation

<p align="center">
  <img alt="humans" src="https://img.shields.io/badge/humans-README_+_HUMAN.md-2563eb?style=for-the-badge" />
  &nbsp;
  <img alt="agents" src="https://img.shields.io/badge/agents-AGENTS.md_only-7c3aed?style=for-the-badge" />
</p>

<p align="center">
  <b>Human</b> docs and <b>agent / LLM</b> docs stay separate on purpose.<br/>
  <sub>Players never need the protocol file. Agents should not treat the README as the contract.</sub>
</p>

<table>
<tr>
<td width="55%" valign="top">

#### 👤 For people

| Document | Contents |
|:---------|:---------|
| **[README.md](README.md)** *(this page)* | Install · features · controls |
| **[docs/HUMAN.md](docs/HUMAN.md)** | Gameplay · inn · magic · social · hosting |
| **[client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md)** | PNG names · CC0 licenses · how to swap art |
| **[docs/README.md](docs/README.md)** | Docs map & contributor checklist |
| [plan.md](plan.md) | Historical roadmap only — **not** live truth |

</td>
<td width="45%" valign="top">

#### 🤖 For coding agents / LLMs

| Document | Contents |
|:---------|:---------|
| **[AGENTS.md](AGENTS.md)** | **Only** agent entry |
| | Protocol · hot paths · tests · reliability |

```text
Humans → README · HUMAN · ATTRIBUTION
Agents → AGENTS.md ONLY
```

</td>
</tr>
</table>

| Role | Start here |
|:-----|:-----------|
| **Player** | This README → [docs/HUMAN.md](docs/HUMAN.md) |
| **Host / ops** | [Quick start](#-quick-start) · [Configuration](#️-configuration) · HUMAN hosting |
| **Artist** | [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md) |
| **Coding agent** | **[`AGENTS.md`](AGENTS.md) only** — never invent features from `plan.md` |

| Do | Don’t |
|:---|:------|
| Keep install & controls in human docs | Paste protocol / message catalogs into README / HUMAN |
| Put protocol, reliability, test matrices in `AGENTS.md` | Treat `plan.md` as the live backlog |
| Link across audiences | Mix agent-only tables into player prose |
| Keep slash-commands accurate for players | Document unfinished features as shipped |

---

## 🙏 Credits

| | |
|:--|:--|
| **Inspiration** | *Dragon Quest I / Dragon Warrior* (NES-era combat math — not a ROM dump) |
| **Combat reference** | [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat) |
| **Art (CC0)** | [Kenney.nl](https://kenney.nl) · [Tiny Creatures](https://opengameart.org/content/tiny-creatures) (Clint Bellanger) — [ATTRIBUTION](client/assets/ATTRIBUTION.md) |
| **Disclaimer** | Fan project — **not** Square Enix |

---

<p align="center">
  <sub>
    <b>v0.5.46</b> · 197 tests ·
    <a href="docs/HUMAN.md">Player guide</a> ·
    <a href="AGENTS.md">Agent contract</a> ·
    <a href="docs/README.md">Docs map</a>
  </sub>
</p>
