-- Shared spell ids (mirror dq1-combat; server will port fully in Phase 4)
return {
  heal = { id = "heal", name = "Heal", mp_cost = 3, kind = "heal" },
  hurt = { id = "hurt", name = "Hurt", mp_cost = 2, kind = "attack" },
  sleep = { id = "sleep", name = "Sleep", mp_cost = 2, kind = "status" },
  stopspell = { id = "stopspell", name = "Stopspell", mp_cost = 2, kind = "status" },
  healmore = { id = "healmore", name = "Healmore", mp_cost = 8, kind = "heal" },
  hurtmore = { id = "hurtmore", name = "Hurtmore", mp_cost = 5, kind = "attack" },
}
