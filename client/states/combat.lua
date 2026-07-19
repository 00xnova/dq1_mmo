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
}

local function push_log(self, text)
  if not text or text == "" then
    return
  end
  self.log[#self.log + 1] = text
  while #self.log > 10 do
    table.remove(self.log, 1)
  end
end

local function rebuild_menu(self)
  self.menu = { { label = "Attack", action = { type = "attack" } }, { label = "Flee", action = { type = "flee" } } }
  for _, a in ipairs(self.legal or {}) do
    if a.type == "spell" then
      self.menu[#self.menu + 1] = {
        label = "Spell: " .. tostring(a.id),
        action = { type = "use_spell", spell = a.id },
      }
    end
  end
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
  -- Keep socket; replace handlers so overworld move handlers don't fight us
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
  apply_events(self, payload.events)
  rebuild_menu(self)

  Network.on("combat_update", function(data)
    if data.enemy then
      self.enemy = data.enemy
    end
    if data.player_hp then
      self.hero.hp = data.player_hp
      self.hero.mp = data.player_mp or self.hero.mp
      self.hero.max_hp = data.player_max_hp or self.hero.max_hp
      self.hero.max_mp = data.player_max_mp or self.hero.max_mp
    end
    self.legal = data.legal_actions or self.legal
    apply_events(self, data.events)
    rebuild_menu(self)
    if data.outcome and data.outcome ~= "ongoing" then
      self.status = "Battle ending..."
    else
      self.status = "Your turn"
    end
  end)

  Network.on("combat_end", function(data)
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
      line = "Defeated... returned to town."
    else
      line = string.format("Victory! +%s XP  +%s G", tostring(data.xp or 0), tostring(data.gold or 0))
    end
    push_log(self, line)
    self.status = line .. "  (Enter: continue)"
  end)

  Network.on("level_up", function(data)
    push_log(self, "LEVEL UP! Now level " .. tostring(data.new_level))
  end)
end

function Combat:leave() end

function Combat:update(dt)
  Network.update(dt)
end

function Combat:_send(action)
  if self.ended then
    return
  end
  if action.type == "attack" then
    Network.send({ type = "attack" })
  elseif action.type == "flee" then
    Network.send({ type = "flee" })
  elseif action.type == "use_spell" then
    Network.send({ type = "use_spell", spell = action.spell })
  end
  self.status = "..."
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
  elseif key == "escape" then
    self:_send({ type = "flee" })
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
  local mx, my = 40, h - 160
  for i, item in ipairs(self.menu) do
    local iy = my + (i - 1) * 28
    if UI.hit(x, y, mx, iy, 220, 26) then
      self.selected = i
      self:_send(item.action)
      return
    end
  end
end

function Combat:draw()
  love.graphics.clear(0.08, 0.05, 0.1)
  local w, h = love.graphics.getDimensions()

  UI.panel(30, 30, w - 60, 130)
  love.graphics.setColor(1, 0.92, 0.45)
  love.graphics.print("COMBAT", 50, 45)
  love.graphics.setColor(0.9, 0.9, 0.95)
  if self.hero then
    local hp = self.hero.hp or 0
    local mhp = math.max(1, self.hero.max_hp or 1)
    local mp = self.hero.mp or 0
    local mmp = math.max(0, self.hero.max_mp or 0)
    love.graphics.print(
      string.format("%s  Lv%d", self.hero.name or "Hero", self.hero.level or 1),
      50,
      72
    )
    love.graphics.setColor(0.2, 0.2, 0.25)
    love.graphics.rectangle("fill", 50, 96, 200, 12)
    love.graphics.setColor(0.85, 0.25, 0.28)
    love.graphics.rectangle("fill", 50, 96, 200 * math.min(1, hp / mhp), 12)
    love.graphics.setColor(1, 1, 1)
    love.graphics.print(string.format("HP %d/%d", hp, mhp), 54, 94)
    if mmp > 0 then
      love.graphics.setColor(0.2, 0.2, 0.25)
      love.graphics.rectangle("fill", 270, 96, 140, 12)
      love.graphics.setColor(0.3, 0.5, 0.95)
      love.graphics.rectangle("fill", 270, 96, 140 * math.min(1, mp / mmp), 12)
      love.graphics.setColor(1, 1, 1)
      love.graphics.print(string.format("MP %d/%d", mp, mmp), 274, 94)
    end
  end
  if self.enemy then
    local ehp = self.enemy.hp or 0
    local emhp = math.max(1, self.enemy.max_hp or 1)
    love.graphics.setColor(1, 0.55, 0.55)
    love.graphics.print(self.enemy.name or "?", 50, 120)
    love.graphics.setColor(0.2, 0.15, 0.15)
    love.graphics.rectangle("fill", 160, 122, 200, 10)
    love.graphics.setColor(0.9, 0.35, 0.25)
    love.graphics.rectangle("fill", 160, 122, 200 * math.min(1, ehp / emhp), 10)
    love.graphics.setColor(1, 1, 1)
    love.graphics.print(string.format("%d/%d", ehp, emhp), 370, 118)
  end

  -- enemy blob
  love.graphics.setColor(0.7, 0.25, 0.35)
  love.graphics.circle("fill", w * 0.7, h * 0.42, 50)
  love.graphics.setColor(1, 1, 1)
  if self.enemy then
    local n = self.enemy.name or "?"
    local font = love.graphics.getFont()
    love.graphics.print(n, w * 0.7 - font:getWidth(n) / 2, h * 0.42 - 70)
  end

  UI.panel(30, h - 280, w - 60, 120)
  love.graphics.setColor(0.85, 0.9, 0.85)
  local ly = h - 265
  for i = math.max(1, #self.log - 5), #self.log do
    love.graphics.print(self.log[i], 50, ly)
    ly = ly + 20
  end

  UI.panel(30, h - 150, 260, 120)
  for i, item in ipairs(self.menu) do
    local iy = h - 135 + (i - 1) * 28
    if i == self.selected and not self.ended then
      love.graphics.setColor(0.35, 0.3, 0.12)
      love.graphics.rectangle("fill", 40, iy, 220, 26, 3, 3)
    end
    love.graphics.setColor(1, 1, 0.9)
    love.graphics.print((i == self.selected and "> " or "  ") .. item.label, 50, iy + 4)
  end

  love.graphics.setColor(0.75, 0.8, 0.9)
  love.graphics.print(self.status or "", 320, h - 40)
  love.graphics.setColor(1, 1, 1)
end

return Combat
