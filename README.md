# Dragon Quest 1 MMO

<p align="center">
  <img alt="banner" src="https://img.shields.io/badge/DQ1_MMO-Server--authoritative_multiplayer-1e1b4b?style=for-the-badge&labelColor=0f172a" />
</p>

<p align="center">
  <b>A Dragon Quest&nbsp;I–style multiplayer adventure</b><br/>
  <sub>Share one overworld · classic 1v1 combat · Love2D client · FastAPI server</sub>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.5.19-7c3aed?style=for-the-badge" />
  <img alt="status" src="https://img.shields.io/badge/status-playable_MVP-16a34a?style=for-the-badge" />
  <img alt="tests" src="https://img.shields.io/badge/tests-103_passing-059669?style=for-the-badge" />
</p>

<p align="center">
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
  <a href="docs/HUMAN.md"><b>Player guide</b></a>
  ·
  <a href="client/assets/ATTRIBUTION.md"><b>Art</b></a>
  ·
  <a href="AGENTS.md"><b>Agents</b></a>
</p>

---

Explore **town**, **field**, and **dungeon** with other heroes on a shared grid. Fight server-authoritative 1v1 battles, rest at the **inn**, cast **field magic**, shop for gear, and socialize with **global / nearby / zone** chat, private **whispers**, emotes, and **look**.

> **Fan project.** Inspired by *Dragon Quest I / Dragon Warrior*. **Not** affiliated with Square Enix.

---

## ✨ Highlights

<table>
<tr>
<td width="50%">

| | Feature |
|:--|:--|
| 🗺️ | Shared grid · safe **town** · field · **dungeon** |
| ⚔️ | Server-side DQ1 combat · reconnect grace |
| 🏠 | Inn · shop · equip · **sell equipped** gear |
| ✨ | Heal · Return · **Repel** · **Radiant** · Outside |

</td>
<td width="50%">

| | Feature |
|:--|:--|
| 💬 | Global · nearby · **zone** · **/w** whisper · emotes |
| 👀 | **Look (L)** · online roster *(no map radar)* |
| 🦸 | Up to **3 heroes** · create / delete · XP to next |
| 🎨 | Drop-in PNGs · Kenney **CC0** + SVG placeholders |

</td>
</tr>
</table>

| Also | |
|:-----|:--|
| **Items** | Herb · wings · fairy water · weapons & armor |
| **HUD** | HP/MP · gold · nearby/online · **repel N** · **light N** · status (**F**) |
| **Reliability** | Authoritative moves · combat resume · `session_id` · free-port tests |

**Out of scope for this MVP:** parties · PvP · trade · quests · multi-map worlds.

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
| Health | http://127.0.0.1:8000/health |
| WebSocket | `ws://127.0.0.1:8000/ws` |

### 2 · Client

```bash
love client
```

1. **Register** → create a hero (gold + **3 herbs**)
2. Hero select: **N** new · **D** delete (**Y** confirm) · max **3** heroes
3. **Enter World** — spawn in **town** (safe)
4. **R** inn · **I** bag/shop · field for fights · **F** status

### 3 · Tests

```bash
cd server && source .venv/bin/activate
python tests/run_tests.py
# expect: 103 passed
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
| **/w Name msg** | Whisper (also `/tell`) |
| **/z msg** | Zone chat (same area type: town / field / dungeon) |
| **E** | Cycle emotes |
| **F** | Status sheet (stats, gear, EXP to next, spells) |
| **R** | Inn rest *(town)* |
| **H** / **M** | Field Heal · cycle field spells |
| **K** | List known spells |
| **O** | Who’s online / nearby |
| **L** | Look / examine a player |
| **P** / **Tab** | Toggle player list |
| **C** | Toggle chat panel |
| **I** | Inventory / shop |
| **B** | Debug slime fight *(if `ALLOW_DEBUG=1`)* |
| **?** / **/** | Help toast |
| **Esc** | Disconnect & quit |

</details>

<details>
<summary><b>Combat</b></summary>

<br/>

| Key | Action |
|:---:|:-------|
| **↑ ↓** · **Enter** | Menu |
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

📖 Full player guide → **[docs/HUMAN.md](docs/HUMAN.md)**

---

## 🎨 Look & art

Drop PNGs into [`client/assets/`](client/assets/) — **filenames are the contract**. Missing files fall back to procedural drawing.

| Path | Files |
|:-----|:------|
| `tiles/` | `field` · `wall` · `town` · `water` · `dungeon` |
| `sprites/heroes/` | `hero.png` · `hero_battle.png` · `other.png` |
| `sprites/enemies/` | `{enemy_id}.png` e.g. `slime.png` |
| `src/kenney/` | 16×16 CC0 masters (optional regen) |

**Tiles / heroes / many enemies:** [Kenney](https://kenney.nl) **CC0**.  
**Dragons / wyverns / etc.:** project SVG placeholders.  
Swap any PNG anytime — no code change required.

```bash
./tools/gen_placeholder_assets.sh
# or refresh Kenney packs:
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
├── client/                   ← Love2D + assets
├── server/                   ← FastAPI · combat · WebSocket
├── shared/                   ← dq1_data.json (canonical game data)
└── tools/                    ← multiplayer sims · asset gen
```

---

## 📚 Documentation

**Human docs** and **agent / LLM docs** stay intentionally separate.

| Audience | Document | Contents |
|:---------|:---------|:---------|
| **Everyone** | [README.md](README.md) | Install · features · controls |
| **Players / ops** | [docs/HUMAN.md](docs/HUMAN.md) | Gameplay · inn · magic · social · hosting |
| **Coding agents** | [AGENTS.md](AGENTS.md) | Protocol · hot paths · tests · reliability |
| **Docs map** | [docs/README.md](docs/README.md) | How to keep the split clean |
| **Artists** | [client/assets/ATTRIBUTION.md](client/assets/ATTRIBUTION.md) | PNG names & licenses |
| **History** | [plan.md](plan.md) | Original plan — may be outdated |

```text
┌─────────────────┐              ┌──────────────────┐
│     Humans      │              │  Agents / LLMs   │
└────────┬────────┘              └────────┬─────────┘
         │                                │
         ▼                                ▼
    README.md                         AGENTS.md
    docs/HUMAN.md                     · WebSocket protocol
    docs/README.md                    · hot paths & tests
    (no protocol tables)              · reliability rules
```

| | |
|:--|:--|
| **Players** | Start here → then [docs/HUMAN.md](docs/HUMAN.md) |
| **Agents** | Start at [`AGENTS.md`](AGENTS.md). Do not invent features from `plan.md`. |
| **Protocol** | Lives **only** in AGENTS — never mirrored into human docs. |

---

## 🙏 Credits

- Inspired by **Dragon Quest I / Dragon Warrior** (NES-era combat math; not a ROM dump)
- Related library: [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat)
- Art: [Kenney.nl](https://kenney.nl) (CC0) + project SVG placeholders — see [ATTRIBUTION](client/assets/ATTRIBUTION.md)
- Fan project — **not** Square Enix
