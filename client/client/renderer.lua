local World = require("client.world")

local Renderer = {}

local COLORS = {
  wall = {0.25, 0.22, 0.35},
  grass = {0.18, 0.42, 0.22},
  grid = {0.12, 0.28, 0.15},
  local_p = {0.95, 0.85, 0.25},
  other_p = {0.35, 0.65, 0.95},
}

function Renderer.draw_overworld()
  local ts = World.tile_size
  local map = World.map
  local ox = 80
  local oy = 60

  for y = 1, #map do
    for x = 1, #map[y] do
      local tile = map[y][x]
      local px = ox + (x - 1) * ts
      local py = oy + (y - 1) * ts
      if tile == 1 then
        love.graphics.setColor(COLORS.wall)
      else
        love.graphics.setColor(COLORS.grass)
      end
      love.graphics.rectangle("fill", px, py, ts, ts)
      love.graphics.setColor(COLORS.grid)
      love.graphics.rectangle("line", px, py, ts, ts)
    end
  end

  for _, p in pairs(World.players) do
    Renderer._draw_player(p, ox, oy, ts, COLORS.other_p)
  end

  if World.local_player then
    Renderer._draw_player(World.local_player, ox, oy, ts, COLORS.local_p)
  end

  love.graphics.setColor(1, 1, 1, 1)
end

function Renderer._draw_player(p, ox, oy, ts, color)
  local px = ox + p.x * ts + ts / 2
  local py = oy + p.y * ts + ts / 2
  love.graphics.setColor(color)
  love.graphics.circle("fill", px, py, ts * 0.28)
  love.graphics.setColor(0, 0, 0, 0.8)
  love.graphics.circle("line", px, py, ts * 0.28)
  love.graphics.setColor(1, 1, 1, 1)
  local label = p.name or "?"
  local font = love.graphics.getFont()
  love.graphics.print(label, px - font:getWidth(label) / 2, py - ts * 0.55)
end

return Renderer
