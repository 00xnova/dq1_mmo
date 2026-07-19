# Documentation index

**Human** documentation and **agent / LLM** documentation are intentionally separate.

| Document | Audience | Purpose |
|:---------|:---------|:--------|
| [../README.md](../README.md) | Everyone (GitHub) | Install, features, controls — polished human entry |
| [HUMAN.md](HUMAN.md) | Players, operators | Gameplay, inn, magic, social, hosting |
| [../AGENTS.md](../AGENTS.md) | Coding agents / LLMs | Protocol matrices, hot paths, tests, reliability rules |
| [../client/assets/ATTRIBUTION.md](../client/assets/ATTRIBUTION.md) | Artists | PNG names & licenses |
| [../plan.md](../plan.md) | Historical only | Original roadmap — **not** live source of truth |

**Last docs refresh:** **v0.5.19** (2026-07-19)  
Zone chat (`/z`) · AOI rebuild on sync · whisper by id · Kenney + SVG art · **103** tests · protocol only in AGENTS.md.

---

## Audience rules

| Do | Don’t |
|:---|:------|
| Put install & controls in README / HUMAN | Dump full WS protocol tables into README or HUMAN |
| Put protocol, tests, agent constraints in `AGENTS.md` | Put “how to install Love2D for players” only in AGENTS |
| Treat `plan.md` as history | Treat `plan.md` as the current backlog |
| Bump `VERSION` in `server/config.py` with user-visible changes | Leave README / HUMAN version badges out of date |
| Link across audiences (README → HUMAN / AGENTS) | Mix long agent protocol into human prose |
| Keep chat slash-commands (`/w`, `/z`) accurate in HUMAN | Claim client features that only exist on the server |

### Quick map

```text
Humans  ──►  README.md  +  docs/HUMAN.md
Agents  ──►  AGENTS.md   (protocol + tests + hot paths ONLY)
Art     ──►  client/assets/ATTRIBUTION.md
History ──►  plan.md     (outdated; do not treat as backlog)
```

```text
┌─────────────────┐              ┌──────────────────┐
│     Humans      │              │  Agents / LLMs   │
└────────┬────────┘              └────────┬─────────┘
         │                                │
         ▼                                ▼
    README.md                         AGENTS.md
    docs/HUMAN.md                     · WebSocket catalog
                                      · reliability rules
                                      · test matrix
```

---

## When the game changes

Checklist for contributors (human or agent):

- [ ] `server/config.py` → `VERSION`
- [ ] [README.md](../README.md) version badge · features · controls · test count
- [ ] [HUMAN.md](HUMAN.md) gameplay if player-facing
- [ ] [AGENTS.md](../AGENTS.md) protocol / tests / reliability if agent-facing
- [ ] This index “last refresh” line
