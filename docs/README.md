# Documentation index

**Human** documentation and **agent / LLM** documentation are intentionally separate.
Do not copy protocol tables, test matrices, or reliability rule lists into player-facing pages.

**Last docs refresh:** **v0.5.54** (2026-07-19) · suite green **232** tests · `VERSION` in `server/config.py`  
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
- Zones · `/zone` · `/counts` · bag limits · **D** discard · inn **R** quote then confirm
- Whisper / look / ignore: full name or **unique prefix** (ambiguous names rejected)
- Nearby system lines: fight start · victory · flee · defeat · zone enter · level-ups · idle leave
- Social: `/say` `/g` `/w` `/z` `/roll` `/find` `/who` `/near` `/ignore` `/r` `/inn` …
- Shop town-only · not in combat · gold toasts · high-tier gear
- Join welcome may mention nearby heroes
- Soft reconnect: mute list, last whisper partner, and buffs survive a brief disconnect
- Failed private messages do not block your next chat line
- CC0 pixel art + SVG companions

---

## Agent docs (technical contract)

| Document | Purpose |
|:---------|:--------|
| [../AGENTS.md](../AGENTS.md) | **Single** agent source of truth |

**Belongs only in AGENTS.md** (do not paste into README / HUMAN):

- Full WebSocket message catalogs
- Reliability rules (AOI, soft grace, rates, `resolve_live_name`, bag caps, …)
- Test module matrix (`server/tests/run_tests.py`)
- Hot paths, architecture, coding constraints

---

## Audience rules

| Do | Don’t |
|:---|:------|
| Put install & controls in README / HUMAN | Dump WS protocol tables into README or HUMAN |
| Put protocol, tests, constraints in `AGENTS.md` | Put player install only in AGENTS |
| Bump `VERSION` with user-visible changes | Leave badges / HUMAN version out of date |
| Use plain language in README “What’s new” | Leak message types or test matrices to players |

---

## When the game changes

- [ ] `server/config.py` → `VERSION`
- [ ] [README.md](../README.md) badges · features · controls · test count
- [ ] [HUMAN.md](HUMAN.md) if player-facing
- [ ] [AGENTS.md](../AGENTS.md) if protocol / tests / reliability changed
- [ ] This index “last refresh” line
- [ ] Human prose stays free of protocol dumps
