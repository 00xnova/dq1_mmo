# Documentation index

**Human** documentation and **agent / LLM** documentation are intentionally separate.
Do not copy protocol tables, test matrices, or reliability rule lists into player-facing pages.

**Last docs refresh:** **v0.5.46** (2026-07-19) · suite green **197** tests · `VERSION` in `server/config.py`  
**Rule:** humans never need protocol files; agents never treat README as the contract.

---

## Start here by audience

| You are… | Open this | Then |
|:---------|:----------|:-----|
| **Player / operator** | [../README.md](../README.md) | [HUMAN.md](HUMAN.md) for gameplay & hosting |
| **Artist** | [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) | Drop PNGs; names are the contract |
| **Coding agent / LLM** | [../AGENTS.md](../AGENTS.md) **only** | Protocol, hot paths, tests, reliability |
| **Curious about history** | [../plan.md](../plan.md) | Original roadmap — **not** live truth |

```text
┌─────────────────────────┐          ┌─────────────────────────┐
│         HUMANS          │          │     AGENTS / LLMs       │
├─────────────────────────┤          ├─────────────────────────┤
│ README.md  (GitHub)     │          │ AGENTS.md  (only file)  │
│ docs/HUMAN.md           │          │  · WebSocket catalog    │
│ docs/README.md (map)    │          │  · reliability rules    │
│ client/assets/          │          │  · test matrix          │
│   ATTRIBUTION.md        │          │  · hot paths            │
└────────────┬────────────┘          └────────────┬────────────┘
             │                                    │
             └──────── never mix contents ────────┘
```

---

## Human docs (plain language)

| Document | Purpose |
|:---------|:--------|
| [../README.md](../README.md) | Install, features, controls, polish for GitHub |
| [HUMAN.md](HUMAN.md) | Gameplay, inn, magic, social, hosting, art swap |
| [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) | PNG paths, CC0 sources, how to replace art |

**Covered for players (current):**

- Install & quick start · overworld / combat / inventory keys
- Zones (town / field / dungeon) · zone badge · zone-enter chat notes
- **`/zone`** shows **who is in your area** (names/levels) + population by zone type
- Bag limits: **12** item kinds · **8** each; *stack full* / *inventory full* at the shop
- Nearby system lines when someone is **defeated** in battle
- Shop buy/sell gold toasts · need-N-G when short · helmets in shop · inn · field magic
- Social: `/say` · `/g` · `/w` · `/z` · `/emote` · `/find` (+ `zone:`) · `/who` · `/players` · `/near` · `/zone` · `/ignore` · `/r` · `/status`
- Join welcome toast with online count; nearby list via `/near`
- Chat & emotes always appear once for you (no missing / double self-lines)
- **`/ignores`** keeps names if someone goes offline
- High-tier shop gear: Broad Sword · Half/Full Plate · Silver Shield · helmets
- Shop **town only** and **not in combat**; bag Tab checks town before requesting shop
- Status sheet: **own** position + zone + repel/light; online roster shows **zone type** only (never others’ coords)
- Nearby join toasts may show peer **zone**; zone chat stays within town / field / dungeon
- CC0 pixel art + optional SVG companions under `client/assets/`

---

## Agent docs (technical contract)

| Document | Purpose |
|:---------|:--------|
| [../AGENTS.md](../AGENTS.md) | **Single** agent source of truth |

**Belongs only in AGENTS.md** (do not paste into README / HUMAN):

- Full WebSocket message catalogs (client ↔ server)
- Reliability rules (AOI, soft grace, rates, reconnect, finite coords, bag caps, …)
- Test module matrix (`server/tests/run_tests.py`)
- Hot paths, architecture, coding constraints

Agents: prefer AGENTS.md over guessing; treat `plan.md` as history only.

---

## Audience rules

| Do | Don’t |
|:---|:------|
| Put install & controls in README / HUMAN | Dump WS protocol tables into README or HUMAN |
| Put protocol, tests, agent constraints in `AGENTS.md` | Put player install steps only in AGENTS |
| Treat `plan.md` as history | Treat `plan.md` as the current backlog |
| Bump `VERSION` with user-visible changes | Leave badges / HUMAN version out of date |
| Link across audiences | Mix agent-only tables into player prose |
| Keep slash-commands accurate in HUMAN | Claim unfinished features as shipped |
| Use plain language in README “What’s new” | Leak internal IDs, message types, or test matrices to players |

---

## When the game changes

Checklist for contributors (human or agent):

- [ ] `server/config.py` → `VERSION`
- [ ] [README.md](../README.md) version badge · features · controls · test count
- [ ] [HUMAN.md](HUMAN.md) if player-facing
- [ ] [AGENTS.md](../AGENTS.md) if protocol / tests / reliability changed
- [ ] This index “last refresh” line
- [ ] Human prose stays free of protocol dumps
