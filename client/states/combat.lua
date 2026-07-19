local Assets = require("client.assets")
local Network = require("client.network")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Combat = {
  enemy = nil,
  hero = nil,
  log = {},
  legal = {},
  status = "",
  ended = false,
  result = nil,
  selected = 1,
  menu = {},
  waiting = false,
}

local function push_log(self, text)
  if not text or text == "" then
    return
  end
  self.log[#self.log + 1] = text
  while #self.log > 12 do
    table.remove(self.log, 1)
  end
end

local function rebuild_menu(self)
  self.menu = {
    { label = "Attack", hint = "A", action = { type = "attack" } },
    { label = "Flee", hint = "F", action = { type = "flee" } },
  }
  for _, a in ipairs(self.legal or {}) do
    if a.type == "spell" then
      local id = tostring(a.id or "?")
      local pretty = id:gsub("^%l", string.upper)
      self.menu[#self.menu + 1] = {
        label = pretty,
        hint = "✦",
        action = { type = "use_spell", spell = a.id },
      }
    end
  end
  -- Herb from inventory if we still have any (server validates)
  local inv = Session.character and Session.character.inventory
  local herbs = 0
  if type(inv) == "table" then
    for _, it in ipairs(inv) do
      if it.item_id == "herb" then
        herbs = herbs + (tonumber(it.quantity) or 1)
      end
    end
  end
  -- Always offer herb; server rejects if none
  self.menu[#self.menu + 1] = {
    label = herbs > 0 and ("Herb ×" .. tostring(herbs)) or "Herb",
    hint = "H",
    action = { type = "use_item", item = "herb" },
  }
  if self.selected > #self.menu then
    self.selected = 1
  end
end

local function apply_events(self, events)
  for _, e in ipairs(events or {}) do
    push_log(self, e.message or e.kind)
  end
end

function Combat:enter(payload)
  payload = payload or {}
  Network.clear_handlers()
  self.enemy = payload.enemy
  self.hero = payload.hero or {
    hp = Session.character and Session.character.current_hp or 15,
    max_hp = Session.character and Session.character.max_hp or 15,
    mp = Session.character and Session.character.current_mp or 0,
    max_mp = Session.character and Session.character.max_mp or 0,
    name = Session.character and Session.character.name or "Hero",
    level = Session.character and Session.character.level or 1,
  }
  self.log = {}
  self.legal = payload.legal_actions or { { type = "attack" }, { type = "flee" } }
  self.status = "Your turn"
  self.ended = false
  self.result = nil
  self.selected = 1
  self.waiting = false
  apply_events(self, payload.events)
  -- Refresh bag so Herb ×N is accurate
  Network.send({ type = "inventory" })
  rebuild_menu(self)

  Network.on("combat_update", function(data)
    self.waiting = false
    if data.enemy then
      self.enemy = data.enemy
    end
    if data.player_hp ~= nil then
      self.hero.hp = data.player_hp
      self.hero.mp = data.player_mp or self.hero.mp
      self.hero.max_hp = data.player_max_hp or self.hero.max_hp
      self.hero.max_mp = data.player_max_mp or self.hero.max_mp
    end
    self.legal = data.legal_actions or self.legal
    apply_events(self, data.events)
    rebuild_menu(self)
    if data.outcome and data.outcome ~= "ongoing" then
      self.status = "Battle ending…"
    else
      self.status = "Your turn"
    end
  end)

  Network.on("combat_end", function(data)
    self.waiting = false
    self.ended = true
    self.result = data.result
    apply_events(self, data.events)
    if data.character then
      Session.character = data.character
    end
    local line = "Victory!"
    if data.result == "fled" then
      line = "You fled."
    elseif data.result == "defeat" then
      line = "Defeated… returned to town."
    else
      line = string.format("Victory! +%s XP  +%s G", tostring(data.xp or 0), tostring(data.gold or 0))
    end
    push_log(self, line)
    self.status = line .. "   (Enter to continue)"
  end)

  Network.on("level_up", function(data)
    push_log(self, "★ LEVEL UP! Now level " .. tostring(data.new_level))
    UI.toast("Level up! Lv " .. tostring(data.new_level), "ok")
  end)

  Network.on("error", function(data)
    self.waiting = false
    if data.reason and data.reason ~= "wait for your turn" then
      self.status = tostring(data.reason)
    else
      self.status = "Your turn"
    end
  end)

  Network.on("item_used", function(data)
    if data.message then
      push_log(self, data.message)
    end
  end)

  Network.on("inventory_update", function(data)
    if data.character then
      Session.character = data.character
    end
    if data.items and Session.character then
      Session.character.inventory = data.items
    end
    rebuild_menu(self)
  end)

  Network.on("combat_resume", function(data)
    self.waiting = false
    self.ended = false
    if data.enemy then
      self.enemy = data.enemy
    end
    if data.hero then
      self.hero = data.hero
    end
    self.legal = data.legal_actions or self.legal
    apply_events(self, data.events)
    rebuild_menu(self)
    self.status = "Battle resumed — your turn"
  end)

  Network.on("auth_ok", function(data)
    if data.character then
      Session.character = data.character
    end
    if data.in_combat then
      push_log(self, "Reconnected — restoring battle…")
      self.status = "Reconnecting battle…"
      return
    end
    push_log(self, "Reconnected — battle was lost.")
    self.ended = true
    self.waiting = false
    self.status = "Battle ended while away (Enter to continue)"
  end)
end

function Combat:leave() end

function Combat:update(dt)
  Network.update(dt)
end

function Combat:_send(action)
  if self.ended or self.waiting then
    return
  end
  self.waiting = true
  if action.type == "attack" then
    Network.send({ type = "attack" })
  elseif action.type == "flee" then
    Network.send({ type = "flee" })
  elseif action.type == "use_spell" then
    Network.send({ type = "use_spell", spell = action.spell })
  elseif action.type == "use_item" then
    Network.send({ type = "use_item", item = action.item or "herb" })
  end
  self.status = "…"
end

function Combat:keypressed(key)
  if self.ended then
    if key == "return" or key == "space" or key == "escape" then
      State.switch("overworld")
    end
    return
  end
  if key == "up" then
    self.selected = math.max(1, self.selected - 1)
  elseif key == "down" then
    self.selected = math.min(#self.menu, self.selected + 1)
  elseif key == "return" or key == "space" then
    local item = self.menu[self.selected]
    if item then
      self:_send(item.action)
    end
  elseif key == "a" then
    self:_send({ type = "attack" })
  elseif key == "f" then
    self:_send({ type = "flee" })
  elseif key == "h" then
    self:_send({ type = "use_item", item = "herb" })
  elseif key == "escape" then
    self:_send({ type = "flee" })
  else
    -- Number keys 1–9 pick menu rows (Attack, Flee, spells, Herb, …)
    local n = tonumber(key)
    if n and n >= 1 and n <= 9 and self.menu[n] then
      self.selected = n
      self:_send(self.menu[n].action)
    end
  end
end

function Combat:mousepressed(x, y, button)
  if button ~= 1 then
    return
  end
  if self.ended then
    State.switch("overworld")
    return
  end
  local w, h = love.graphics.getDimensions()
  local menu_x, menu_y = 36, h - 168
  local menu_w = 240
  for i, item in ipairs(self.menu) do
    local iy = menu_y + 36 + (i - 1) * 32
    if UI.hit(x, y, menu_x + 10, iy, menu_w - 20, 28) then
      self.selected = i
      self:_send(item.action)
      return
    end
  end
end

function Combat:draw()
  UI.draw_bg({ plain = false })
  -- combat arena floor
  local w, h = love.graphics.getDimensions()
  love.graphics.setColor(0.12, 0.08, 0.14, 0.55)
  love.graphics.ellipse("fill", w * 0.55, h * 0.48, w * 0.38, 48)
  love.graphics.setColor(0.2, 0.12, 0.18, 0.25)
  love.graphics.ellipse("fill", w * 0.55, h * 0.48, w * 0.28, 28)

  -- top status window
  UI.panel(24, 18, w - 48, 100, {
    title = "COMBAT",
    subtitle = self.waiting and "resolving…" or (self.ended and "ended" or "your turn"),
    title_h = 28,
    accent = self.ended and (self.result == "defeat" and "danger" or "ok") or nil,
  })

  if self.hero then
    local hp = self.hero.hp or 0
    local mhp = math.max(1, self.hero.max_hp or 1)
    local mp = self.hero.mp or 0
    local mmp = math.max(0, self.hero.max_mp or 0)
    UI.set_font("body")
    UI.color("gold")
    love.graphics.print(
      string.format("%s   Lv %d", self.hero.name or "Hero", self.hero.level or 1),
      44,
      56
    )
    UI.bar(44, 80, 220, 14, hp / mhp, "hp", string.format("HP  %d / %d", hp, mhp))
    if mmp > 0 then
      UI.bar(280, 80, 160, 14, mp / mmp, "mp", string.format("MP  %d / %d", mp, mmp))
    end
  end

  if self.enemy then
    local ehp = self.enemy.hp or 0
    local emhp = math.max(1, self.enemy.max_hp or 1)
    UI.set_font("small")
    UI.color("danger")
    local ename = self.enemy.name or "Enemy"
    local st = self.enemy.status
    if type(st) == "table" then
      local tags = {}
      if st.sleep then
        tags[#tags + 1] = "SLEEP"
      end
      if st.stopspell then
        tags[#tags + 1] = "MUTE"
      end
      if #tags > 0 then
        ename = ename .. "  [" .. table.concat(tags, ",") .. "]"
      end
    end
    love.graphics.print(ename, w - 280, 56)
    UI.bar(w - 280, 80, 220, 14, ehp / emhp, "hp", string.format("%d / %d", ehp, emhp))
  end

  -- figures (sprites with procedural fallback)
  local hero_img = Assets.hero_battle()
  local hx, hy = w * 0.28, h * 0.42
  if hero_img then
    local bob = math.sin((UI._t or 0) * 2.5) * 3
    local scale = 96 / math.max(hero_img:getWidth(), hero_img:getHeight())
    local iw, ih = hero_img:getWidth() * scale, hero_img:getHeight() * scale
    love.graphics.setColor(0, 0, 0, 0.35)
    love.graphics.ellipse("fill", hx, hy + 40, 28, 9)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(hero_img, hx - iw / 2, hy + bob - ih * 0.7, 0, scale, scale)
  else
    UI.draw_hero_figure(hx, hy)
  end

  local pulse = 1
  if self.enemy and self.enemy.hp and self.enemy.max_hp and self.enemy.hp < self.enemy.max_hp * 0.3 then
    pulse = 0.85 + 0.15 * math.sin((UI._t or 0) * 8)
  end
  local eid = self.enemy and (self.enemy.id or self.enemy.name)
  -- normalize name to id-ish if needed
  if self.enemy and self.enemy.id then
    eid = self.enemy.id
  end
  local enemy_img = Assets.enemy(eid)
  local ex, ey = w * 0.68, h * 0.40
  if enemy_img then
    local bob = math.sin((UI._t or 0) * 2.2) * 4
    local scale = 120 / math.max(enemy_img:getWidth(), enemy_img:getHeight())
    scale = scale * pulse
    local iw, ih = enemy_img:getWidth() * scale, enemy_img:getHeight() * scale
    love.graphics.setColor(0, 0, 0, 0.4)
    love.graphics.ellipse("fill", ex, ey + 48, 42, 12)
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(enemy_img, ex - iw / 2, ey + bob - ih * 0.55, 0, scale, scale)
    if self.enemy and self.enemy.name then
      UI.set_font("body")
      local font = love.graphics.getFont()
      local n = self.enemy.name
      local tw = font:getWidth(n) + 20
      local nx, ny = ex - tw / 2, ey + bob - ih * 0.55 - 32
      love.graphics.setColor(0.05, 0.04, 0.08, 0.85)
      love.graphics.rectangle("fill", nx, ny, tw, 26, 4, 4)
      UI.color("danger")
      love.graphics.setLineWidth(1.5)
      love.graphics.rectangle("line", nx, ny, tw, 26, 4, 4)
      UI.color("text")
      love.graphics.print(n, nx + 10, ny + 5)
    end
  else
    UI.draw_enemy_figure(ex, ey, self.enemy and self.enemy.name, pulse)
  end

  -- message log
  UI.panel(24, h - 300, w - 48, 110, { title = "Battle log", title_h = 26, no_ornament = true })
  UI.set_font("small")
  local ly = h - 266
  local start = math.max(1, #self.log - 4)
  for i = start, #self.log do
    UI.color(i == #self.log and "text" or "muted")
    love.graphics.print(self.log[i], 44, ly)
    ly = ly + 18
  end

  -- command menu
  local menu_h = 36 + #self.menu * 32 + 12
  UI.panel(24, h - 178, 250, math.min(menu_h, 170), {
    title = "Command",
    title_h = 28,
    no_ornament = true,
  })
  for i, item in ipairs(self.menu) do
    local iy = h - 142 + (i - 1) * 32
    local sel = i == self.selected and not self.ended
    UI.list_row(36, iy, 226, 28, sel, item.label, item.hint or "")
  end

  -- status line
  UI.panel(290, h - 70, w - 314, 48, { no_ornament = true, radius = 4 })
  UI.set_font("body")
  if self.ended then
    if self.result == "defeat" then
      UI.color("danger")
    elseif self.result == "fled" then
      UI.color("muted")
    else
      UI.color("ok")
    end
  else
    UI.color("gold")
  end
  love.graphics.print(self.status or "", 308, h - 54)

  UI.set_font("tiny")
  UI.color("muted")
  love.graphics.print("↑↓  ·  Enter  ·  A attack  ·  F flee", 308, h - 36)
  UI.reset_color()
end

return Combat
