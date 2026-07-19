local Network = require("client.network")
local Renderer = require("client.renderer")
local Session = require("client.session")
local World = require("client.world")

local Overworld = {
  status = "",
  move_cooldown = 0,
}

function Overworld:enter()
  World.set_local(Session.character)
  self.status = "Connecting..."
  Network.clear_handlers()
  Network.on("auth_ok", function(data)
    self.status = "Connected"
    if data.character then
      World.set_local(data.character)
    end
  end)
  Network.on("auth_fail", function(data)
    self.status = "Auth failed: " .. tostring(data.reason)
  end)
  Network.on("world_state", function(data)
    World.set_players(data.players)
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
      level = 1,
    }
  end)
  Network.on("player_left", function(data)
    World.players[data.player_id] = nil
  end)
  Network.on("error", function(data)
    self.status = "Error: " .. tostring(data.reason)
  end)

  local ok, err = Network.connect(Session.server_ws)
  if ok then
    Network.auth(Session.character.id)
    self.status = "Authenticating..."
  else
    self.status = tostring(err) .. " (local preview mode)"
  end
end

function Overworld:leave()
  Network.disconnect()
end

function Overworld:update(dt)
  Network.update(dt)
  self.move_cooldown = math.max(0, self.move_cooldown - dt)
  if self.move_cooldown > 0 or not World.local_player then
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
      World.local_player.x = nx
      World.local_player.y = ny
      Network.send({ type = "move", x = nx, y = ny })
      self.move_cooldown = 0.15
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
  if p then
    love.graphics.print(
      string.format("%s  Lv%d  (%d,%d)", p.name, p.level or 1, p.x, p.y),
      16,
      36
    )
  end
  love.graphics.print(self.status, 16, 60)
  love.graphics.print("Arrows/WASD move  |  Esc quit to desktop", 16, love.graphics.getHeight() - 28)
  love.graphics.setColor(1, 1, 1)
end

function Overworld:keypressed(key)
  if key == "escape" then
    love.event.quit()
  end
end

return Overworld
