local Network = require("client.network")
local Renderer = require("client.renderer")
local Session = require("client.session")
local State = require("client.state")
local World = require("client.world")

local Overworld = {
  status = "",
  move_cooldown = 0,
  zone = "town",
  locked = false,
  net_info = "",
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
  if t == 3 then
    return "water"
  end
  return "wall"
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
  end)

  Network.on("auth_fail", function(data)
    self.status = "Auth failed: " .. tostring(data.reason)
  end)

  Network.on("world_state", function(data)
    if data.map then
      World.set_map(data.map)
    end
    World.set_players(data.players)
    if data.you and World.local_player then
      -- authoritative snap when no pending predictions
      if World.pending_count() == 0 then
        World.local_player.x = math.floor(data.you.x)
        World.local_player.y = math.floor(data.you.y)
        World.server_x = World.local_player.x
        World.server_y = World.local_player.y
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
    end
  end)

  Network.on("move_ok", function(data)
    World.apply_move_ok(data)
    if World.local_player then
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
    if data.ok == false and data.reason and data.reason ~= "rate_limit" then
      if data.reason == "in combat" then
        return
      end
      self.status = "Move: " .. tostring(data.reason)
    end
  end)

  Network.on("player_moved", function(data)
    World.update_player(data.player_id, data.x, data.y)
  end)

  Network.on("player_joined", function(data)
    World.players[data.player_id] = {
      id = data.player_id,
      name = data.name or ("P" .. tostring(data.player_id)),
      x = math.floor(data.x or 0),
      y = math.floor(data.y or 0),
      tx = math.floor(data.x or 0),
      ty = math.floor(data.y or 0),
      level = data.level or 1,
    }
  end)

  Network.on("player_left", function(data)
    World.remove_player(data.player_id)
  end)

  Network.on("combat_start", function(data)
    self.locked = true
    World.pending = {}
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
  end)

  Network.on("pong", function() end)
end

function Overworld:enter()
  self.locked = false
  self.move_cooldown = 0.15
  bind_handlers(self)

  if Network.connected and Network.authenticated then
    if Session.character then
      -- keep predicted pos if any; otherwise use session
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
  self.net_info = string.format(
    "%s  rtt %dms  pend %d",
    Network.status(),
    rtt_ms,
    World.pending_count()
  )

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
    local base_x = World.local_player.x
    local base_y = World.local_player.y
    local nx = base_x + dx
    local ny = base_y + dy
    if World.is_walkable(nx, ny) then
      local seq = Network.move(nx, ny)
      World.predict_move(seq, nx, ny)
      self.zone = zone_name(nx, ny)
      self.move_cooldown = MOVE_COOLDOWN
    end
  end
end

function Overworld:draw()
  love.graphics.clear(0.04, 0.05, 0.08)
  Renderer.draw_overworld()

  love.graphics.setColor(1, 0.92, 0.45)
  love.graphics.print("DQ1 MMO — Overworld", 16, 12)
  love.graphics.setColor(0.8, 0.85, 0.9)
  local p = World.local_player
  local c = Session.character
  if p then
    local hp = tonumber(c and c.current_hp) or 0
    local mhp = math.max(1, tonumber(c and c.max_hp) or 1)
    local mp = tonumber(c and c.current_mp) or 0
    local mmp = math.max(0, tonumber(c and c.max_mp) or 0)
    love.graphics.print(
      string.format(
        "%s  Lv%d  (%d,%d)  [%s]  G %s",
        p.name,
        (c and c.level) or p.level or 1,
        math.floor(p.x + 0.01),
        math.floor(p.y + 0.01),
        self.zone,
        tostring(c and c.gold or "0")
      ),
      16,
      36
    )
    love.graphics.setColor(0.2, 0.2, 0.25)
    love.graphics.rectangle("fill", 16, 58, 160, 12)
    love.graphics.setColor(0.8, 0.2, 0.25)
    love.graphics.rectangle("fill", 16, 58, 160 * math.min(1, hp / mhp), 12)
    love.graphics.setColor(1, 1, 1)
    love.graphics.print(string.format("HP %d/%d", hp, mhp), 20, 56)
    if mmp > 0 then
      love.graphics.setColor(0.2, 0.2, 0.25)
      love.graphics.rectangle("fill", 16, 74, 160, 10)
      love.graphics.setColor(0.25, 0.45, 0.9)
      love.graphics.rectangle("fill", 16, 74, 160 * math.min(1, mp / mmp), 10)
      love.graphics.setColor(1, 1, 1)
      love.graphics.print(string.format("MP %d/%d", mp, mmp), 20, 72)
    end
  end
  local others = 0
  for _ in pairs(World.players) do
    others = others + 1
  end
  love.graphics.setColor(0.8, 0.85, 0.9)
  love.graphics.print(self.status .. "  |  nearby: " .. others, 16, 96)
  love.graphics.setColor(0.55, 0.65, 0.7)
  love.graphics.print(self.net_info, 16, 116)
  love.graphics.setColor(0.8, 0.85, 0.9)
  love.graphics.print(
    "WASD move  |  I inventory  |  field battles  |  B debug fight  |  Esc quit",
    16,
    love.graphics.getHeight() - 28
  )
  love.graphics.setColor(1, 1, 1)
end

function Overworld:keypressed(key)
  if key == "escape" then
    Network.disconnect()
    love.event.quit()
  elseif key == "b" and not self.locked then
    Network.send({ type = "debug_encounter", enemy = "slime" })
  elseif key == "i" and not self.locked then
    State.switch("inventory")
  end
end

return Overworld
