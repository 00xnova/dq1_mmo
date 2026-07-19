local Network = require("client.network")
local Renderer = require("client.renderer")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")
local World = require("client.world")

local Overworld = {
  status = "",
  move_cooldown = 0,
  zone = "town",
  locked = false,
  net_info = "",
  show_list = true,
}

local MOVE_COOLDOWN = 0.12
local MAX_PENDING = 3

local function zone_name(x, y)
  local row = World.map and World.map[y + 1]
  if not row then
    return "?"
  end
  local t = row[x + 1]
  if t == 2 then
    return "town"
  end
  if t == 0 then
    return "field"
  end
  if t == 4 then
    return "dungeon"
  end
  if t == 3 then
    return "water"
  end
  return "wall"
end

local function zone_color(z)
  if z == "town" then
    return "gold"
  end
  if z == "dungeon" then
    return "accent"
  end
  if z == "field" then
    return "ok"
  end
  return "muted"
end

local function bind_handlers(self)
  Network.clear_handlers()

  Network.on("auth_ok", function(data)
    self.status = "Connected"
    self.locked = false
    if data.character then
      Session.character = data.character
      World.set_local(data.character)
    end
    if data.map then
      World.set_map(data.map)
    end
    if World.local_player then
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
    UI.toast("Entered the world", "ok")
  end)

  Network.on("combat_resume", function(data)
    self.locked = true
    World.pending = {}
    UI.toast("Battle resumed!", "danger")
    State.switch("combat", data)
  end)

  Network.on("auth_fail", function(data)
    self.status = "Auth failed: " .. tostring(data.reason)
    UI.toast("Auth failed", "danger")
  end)

  Network.on("world_state", function(data)
    if data.map then
      World.set_map(data.map)
    end
    World.set_players(data.players)
    if data.you and World.local_player and World.pending_count() == 0 then
      World.local_player.x = math.floor(data.you.x)
      World.local_player.y = math.floor(data.you.y)
      World.server_x = World.local_player.x
      World.server_y = World.local_player.y
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
  end)

  Network.on("move_ok", function(data)
    World.apply_move_ok(data)
    if World.local_player then
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
    if data.ok == false and data.reason and data.reason ~= "rate_limit" and data.reason ~= "in combat" then
      self.status = "Move: " .. tostring(data.reason)
    end
  end)

  Network.on("player_moved", function(data)
    World.update_player(data.player_id, data.x, data.y)
    local p = World.players[data.player_id]
    if p and data.level then
      p.level = data.level
    end
    if p and data.name then
      p.name = data.name
    end
  end)

  Network.on("player_joined", function(data)
    local id = data.player_id
    local existing = World.players[id]
    World.players[id] = {
      id = id,
      name = data.name or (existing and existing.name) or ("P" .. tostring(id)),
      x = math.floor(data.x or 0),
      y = math.floor(data.y or 0),
      tx = math.floor(data.x or 0),
      ty = math.floor(data.y or 0),
      level = data.level or (existing and existing.level) or 1,
    }
    if not existing then
      UI.toast((data.name or "Hero") .. " appeared nearby", "join")
    end
  end)

  Network.on("player_left", function(data)
    local p = World.players[data.player_id]
    local name = data.name or (p and p.name) or ("#" .. tostring(data.player_id))
    World.remove_player(data.player_id)
    if data.reason == "out_of_range" then
      -- quiet — walking out of range is normal
    else
      UI.toast(name .. " left the area", "leave")
    end
  end)

  Network.on("player_update", function(data)
    local p = World.players[data.player_id]
    if not p then
      return
    end
    if data.name then
      p.name = data.name
    end
    if data.level then
      p.level = data.level
    end
    if data.x and data.y then
      p.tx = data.x
      p.ty = data.y
    end
  end)

  Network.on("combat_start", function(data)
    self.locked = true
    World.pending = {}
    local en = data.enemy and data.enemy.name or "monster"
    UI.toast("Encounter: " .. en .. "!", "danger")
    State.switch("combat", data)
  end)

  Network.on("error", function(data)
    if data.reason == "blocked" or data.reason == "invalid step" then
      if data.x and data.y then
        World.apply_move_ok({ ok = false, x = data.x, y = data.y, seq = data.seq })
        if World.local_player then
          self.zone = zone_name(World.local_player.x, World.local_player.y)
        end
      end
      return
    end
    if data.reason == "in combat" or data.reason == "rate_limit" then
      return
    end
    self.status = "Error: " .. tostring(data.reason)
    UI.toast(tostring(data.reason), "danger")
  end)

  Network.on("pong", function() end)
end

function Overworld:enter()
  self.locked = false
  self.move_cooldown = 0.15
  bind_handlers(self)

  if Network.connected and Network.authenticated then
    if Session.character then
      if World.pending_count() == 0 and World.local_player == nil then
        World.set_local(Session.character)
      elseif World.local_player and Session.character then
        World.local_player.name = Session.character.name
        World.local_player.level = Session.character.level or World.local_player.level
        World.local_player.id = Session.character.id
      elseif Session.character and not World.local_player then
        World.set_local(Session.character)
      end
      if World.local_player then
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
    end
    self.status = "Connected"
    Network.sync()
    return
  end

  World.reset()
  if Session.character then
    World.set_local(Session.character)
    self.zone = zone_name(World.local_player.x, World.local_player.y)
  end
  self.status = "Connecting..."

  local ok, err = Network.connect(Session.server_ws)
  if ok then
    Network.auth(Session.character.id)
    self.status = "Authenticating..."
  else
    self.status = tostring(err) .. " (local preview)"
  end
end

function Overworld:leave() end

function Overworld:update(dt)
  Network.update(dt)
  World.tick_remote(dt)

  local rtt_ms = math.floor((Network.rtt or 0) * 1000)
  local others = 0
  for _ in pairs(World.players) do
    others = others + 1
  end
  self.net_info = string.format("%s · %dms · %d nearby", Network.status(), rtt_ms, others)

  if self.locked then
    return
  end
  if not Network.connected or not Network.authenticated then
    return
  end

  self.move_cooldown = math.max(0, self.move_cooldown - dt)
  if self.move_cooldown > 0 or not World.local_player then
    return
  end
  if World.pending_count() >= MAX_PENDING then
    return
  end

  local dx, dy = 0, 0
  if love.keyboard.isDown("left") or love.keyboard.isDown("a") then
    dx = -1
  elseif love.keyboard.isDown("right") or love.keyboard.isDown("d") then
    dx = 1
  elseif love.keyboard.isDown("up") or love.keyboard.isDown("w") then
    dy = -1
  elseif love.keyboard.isDown("down") or love.keyboard.isDown("s") then
    dy = 1
  end

  if dx ~= 0 or dy ~= 0 then
    local nx = World.local_player.x + dx
    local ny = World.local_player.y + dy
    if World.is_walkable(nx, ny) then
      local seq = Network.move(nx, ny)
      World.predict_move(seq, nx, ny)
      self.zone = zone_name(nx, ny)
      self.move_cooldown = MOVE_COOLDOWN
    end
  end
end

function Overworld:draw()
  UI.draw_bg()
  Renderer.draw_overworld()

  local w, h = love.graphics.getDimensions()
  local c = Session.character or {}
  local p = World.local_player

  -- Top-left HUD
  UI.panel(12, 12, 280, 118)
  UI.set_font("large")
  UI.color("gold")
  love.graphics.print("DQ1 MMO", 24, 20)
  UI.set_font("small")
  UI.color("muted")
  love.graphics.print(self.net_info, 24, 46)

  if p then
    UI.set_font("body")
    UI.color("text")
    love.graphics.print(
      string.format("%s  Lv%d", p.name or "?", (c.level or p.level or 1)),
      24,
      68
    )
    local hp = tonumber(c.current_hp) or 0
    local mhp = math.max(1, tonumber(c.max_hp) or 1)
    local mp = tonumber(c.current_mp) or 0
    local mmp = math.max(0, tonumber(c.max_mp) or 0)
    UI.bar(24, 92, 160, 12, hp / mhp, "hp", string.format("HP %d/%d", hp, mhp))
    if mmp > 0 then
      UI.bar(24, 108, 160, 10, mp / mmp, "mp", string.format("MP %d/%d", mp, mmp))
    end
    UI.set_font("small")
    UI.color("gold")
    love.graphics.print(tostring(c.gold or "0") .. " G", 200, 92)
  end

  -- Zone badge
  UI.panel(12, 140, 140, 36)
  UI.set_font("small")
  UI.color(zone_color(self.zone))
  love.graphics.print("ZONE  " .. string.upper(self.zone or "?"), 24, 150)
  if p then
    UI.color("muted")
    love.graphics.print(string.format("(%d, %d)", math.floor(p.x + 0.01), math.floor(p.y + 0.01)), 24, 162)
  end

  -- Minimap
  UI.minimap(w - 148, 12, 128, World)

  -- Player list
  if self.show_list then
    UI.player_list(w - 250, 156, 238, 200, World.local_player, World.players, "Adventurers nearby")
  end

  -- Bottom help bar
  UI.panel(12, h - 48, w - 24, 36)
  UI.set_font("small")
  UI.color("muted")
  love.graphics.print(
    "WASD move   ·   I inventory   ·   P player list   ·   field/dungeon battles   ·   B debug fight   ·   Esc quit",
    24,
    h - 36
  )

  if self.status and self.status ~= "Connected" then
    UI.set_font("small")
    UI.color("ok")
    love.graphics.print(self.status, 24, 188)
  end
  UI.reset_color()
end

function Overworld:keypressed(key)
  if key == "escape" then
    Network.disconnect()
    love.event.quit()
  elseif key == "b" and not self.locked then
    Network.send({ type = "debug_encounter", enemy = "slime" })
  elseif key == "i" and not self.locked then
    State.switch("inventory")
  elseif key == "p" or key == "tab" then
    self.show_list = not self.show_list
    UI.toast(self.show_list and "Player list on" or "Player list off", "info")
  end
end

return Overworld
