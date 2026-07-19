# Dragon Quest 1 MMO

<p align="center">
  <img alt="banner" src="https://img.shields.io/badge/DQ1_MMO-Server--authoritative_multiplayer-1e1b4b?style=for-the-badge&labelColor=0f172a" />
</p>

<p align="center">
  <b>A Dragon Quest&nbsp;I–style multiplayer adventure</b><br/>
  <sub>Share one overworld · classic 1v1 combat · Love2D client · FastAPI server</sub>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.54-7c3aed?style=for-the-badge" />
  <img alt="status" src="https://img.shields.io/badge/status-playable_MVP-16a34a?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-232_passing-059669?style=for-the-badge" />
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
Fight server-authoritative 1v1 battles, rest at the **inn**, cast **field magic**, shop for gear (limited bag · discard), and socialize — global / nearby / zone chat, whispers (unique name prefixes), **`/r`**, **`/find`**, **`/who`** · **`/counts`** · **`/zone`**, **`/roll`**, emotes, and look.

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
| 🆕 | [What's new](#-whats-new) — **v0.5.54** |
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
  <img alt="latest" src="https://img.shields.io/badge/latest-v0.5.54-7c3aed?style=flat-square" />
  <img alt="tests" src="https://img.shields.io/badge/tests-232_passing-059669?style=flat-square" />
  <img alt="mvp" src="https://img.shields.io/badge/MVP-playable-16a34a?style=flat-square" />
</p>

| | **v0.5.54** |
|:--|:--|
| 🔄 | **Brief disconnects** keep your mute list, last whisper partner, and buffs so **`/r`** still works after you rejoin |
| 💬 | Failed private messages no longer “eat” your next chat attempt |
| 👀 | Other players see cleaner join / leave presence when people reconnect mid-session |
| ✅ | **232** automated tests |

<details>
<summary><b>Earlier releases</b></summary>

<br/>

| Version | Highlights |
|:--------|:-----------|
| **0.5.53** | Look always shows zone · empty chat no longer blocks the next line |
| **0.5.52** | Whisper / look / ignore **unique name prefixes** · join welcome may mention nearby |
| **0.5.51** | Inn: **R** quotes cost, **R again** to rest · bag-full buy tips |
| **0.5.50** | `/counts` · victory/flee/defeat notices · idle leave |
| **0.5.49** | Discard (**D**) · bag used/max UI |
| **0.5.48** | `/roll` · fight notices · safer whispers |
| **0.5.46–47** | Bag limits · reserved names · `/say` `/g` `/emote` |
| **0.5.40–45** | `/zone` · `/near` · `/players` · presence · open art |

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
| 🏠 | Inn (quote then confirm) · shop · equip · sell · discard |
| ✨ | Heal · Return · **Repel** · **Radiant** · Outside |

</td>
<td width="50%" valign="top">

### Social & meta

| | |
|:--|:--|
| 💬 | Global · nearby · **zone** · whisper (prefix) · **`/r`** · emotes · **`/roll`** |
| 🔍 | **`/find`** · **`/who`** · **`/counts`** · **`/near`** · **`/zone`** · **`/ignore`** · look |
| 🦸 | Up to **3 heroes** · create / delete · XP to next |
| 🎨 | Drop-in PNGs · Kenney + Tiny Creatures **CC0** |

</td>
</tr>
</table>

| Also | |
|:-----|:--|
| **Items** | Herb · wings · fairy water · weapons · armor · helmets · Full Plate · Silver Shield |
| **Bag** | **12** stacks · **8** each · **D** discard · sell/buy in town |
| **HUD** | HP/MP · gold · zone · your position · nearby/online · repel · light · **F** status |
| **Shop UX** | Gold toasts · need-N-G · sell-back · **town only** (not in combat) |
| **Stability** | Server-authoritative movement · combat resume · soft reconnect · presence repair · **232** tests |

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
3. **Enter World** — spawn in **town** · welcome toast with online / nearby
4. **R** inn (quote → confirm) · **I** bag (**D** discard) · **`/counts`** · **`/roll`** · **`/w Name`**

### 3 · Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
# expect: 232 passed
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
| **/z msg** | Zone chat |
| **/roll** · **/dice** · **/roll 20** | Nearby dice |
| **/counts** · **/census** | Online + zone totals |
| **/find Name** · **/find zone:town** | Search online (no map coords) |
| **/who** · **/players** | Online + nearby + zones (**O**) |
| **/near** · **/here** | Heroes in view |
| **/zone** · **/where** | Your area + who is here |
| **/status** · **/me** · **F** | Status sheet |
| **/ignore** · **/unignore** · **/ignores** | Mute list |
| **/r message** | Reply last whisper |
| **/inn** · **/rest** | Inn cost quote |
| **E** | Cycle emotes |
| **R** | Inn quote → **R** again to stay *(town)* |
| **H** / **M** | Field heal / cycle field spells |
| **K** | List spells |
| **L** | Look at a player |
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
| `/say` · `/s` · `/g` · `/z` | Nearby · global · zone chat |
| `/roll` · `/dice` · `/roll 20` | Nearby dice (default d100) |
| `/counts` · `/census` | Online + zone population |
| `/find Name` · `/find zone:field` | Search (zone type only, no coords) |
| `/who` · `/players` · `/near` · `/zone` | Rosters & area info |
| `/ignore` · `/unignore` · `/ignores` | Mute list |
| `/r message` | Reply last whisper |
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

```bash
./tools/mp_sim.sh
./tools/mp_sim.sh -n 5 --scenario wander --seconds 30
./tools/mp_love.sh 2
```

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
Humans → README · HUMAN · ATTRIBUTION
Agents → AGENTS.md ONLY
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
  <sub>
    <b>v0.5.54</b> · 232 tests · humans ↔ agents docs stay separate ·
    <a href="docs/HUMAN.md">Player guide</a> ·
    <a href="AGENTS.md">Agent contract</a> ·
    <a href="docs/README.md">Docs map</a>
  </sub>
</p>
