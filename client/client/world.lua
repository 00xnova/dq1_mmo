local World = {
  map = nil,
  width = 16,
  height = 12,
  tile_size = 40,
  players = {},
  local_player = nil,
  -- predicted move pipeline: {seq, x, y}
  pending = {},
  server_x = 2,
  server_y = 2,
}

local DEFAULT_MAP = {
  {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
  {1,2,2,2,2,1,0,0,0,0,0,0,0,0,0,1},
  {1,2,2,2,2,1,0,0,0,0,0,0,0,0,0,1},
  {1,2,2,2,2,0,0,0,0,0,1,1,0,0,0,1},
  {1,2,2,2,2,0,0,0,0,0,1,1,0,0,0,1},
  {1,1,1,0,1,0,0,0,0,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,3,3,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,3,3,0,0,0,0,0,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,1,1,1,0,1},
  {1,0,0,0,0,0,0,0,0,0,0,1,0,0,0,1},
  {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1},
}

function World.reset()
  World.map = DEFAULT_MAP
  World.width = #DEFAULT_MAP[1]
  World.height = #DEFAULT_MAP
  World.players = {}
  World.local_player = nil
  World.pending = {}
  World.server_x = 2
  World.server_y = 2
end

function World.set_map(map_data)
  if not map_data or not map_data.tiles then
    return
  end
  World.map = map_data.tiles
  World.width = map_data.width or #map_data.tiles[1]
  World.height = map_data.height or #map_data.tiles
end

function World.is_walkable(x, y)
  local row = World.map and World.map[y + 1]
  if not row then
    return false
  end
  local t = row[x + 1]
  return t == 0 or t == 2
end

function World.set_local(character)
  local x = math.floor(character.world_x or character.x or 2)
  local y = math.floor(character.world_y or character.y or 2)
  World.local_player = {
    id = character.id,
    name = character.name,
    x = x,
    y = y,
    level = character.level or 1,
  }
  World.server_x = x
  World.server_y = y
  World.pending = {}
end

function World.set_players(list)
  local keep = {}
  for _, p in ipairs(list or {}) do
    local id = p.id
    keep[id] = true
    local existing = World.players[id]
    local tx = math.floor(p.world_x or p.x or 0)
    local ty = math.floor(p.world_y or p.y or 0)
    if existing then
      existing.tx = tx
      existing.ty = ty
      existing.name = p.name or existing.name
      existing.level = p.level or existing.level
    else
      World.players[id] = {
        id = id,
        name = p.name or ("P" .. tostring(id)),
        x = tx,
        y = ty,
        tx = tx,
        ty = ty,
        level = p.level or 1,
      }
    end
  end
  -- drop players not in snapshot
  for id in pairs(World.players) do
    if not keep[id] then
      World.players[id] = nil
    end
  end
end

function World.predict_move(seq, x, y)
  World.pending[#World.pending + 1] = { seq = seq, x = x, y = y }
  if World.local_player then
    World.local_player.x = x
    World.local_player.y = y
  end
end

--- Apply server move_ok. Replays unconfirmed predictions after ack.
function World.apply_move_ok(data)
  local sx = data.x
  local sy = data.y
  local seq = data.seq
  World.server_x = sx
  World.server_y = sy

  if data.ok == false then
    -- hard snap + drop all pending
    World.pending = {}
    if World.local_player then
      World.local_player.x = sx
      World.local_player.y = sy
    end
    return
  end

  if seq ~= nil then
    local kept = {}
    for _, m in ipairs(World.pending) do
      if m.seq > seq then
        kept[#kept + 1] = m
      end
    end
    World.pending = kept
  else
    World.pending = {}
  end

  -- rebuild predicted position from server + remaining pending
  local px, py = sx, sy
  for _, m in ipairs(World.pending) do
    px, py = m.x, m.y
  end
  if World.local_player then
    World.local_player.x = px
    World.local_player.y = py
  end
end

function World.update_player(id, x, y)
  if World.local_player and World.local_player.id == id then
    -- remote echo of self — ignore; move_ok is authoritative
    return
  end
  local p = World.players[id]
  if p then
    p.tx = x
    p.ty = y
  else
    World.players[id] = {
      id = id,
      name = "P" .. tostring(id),
      x = x,
      y = y,
      tx = x,
      ty = y,
      level = 1,
    }
  end
end

function World.remove_player(id)
  World.players[id] = nil
end

--- Smooth remote players toward targets (grid lerp).
function World.tick_remote(dt)
  local speed = 10 -- tiles/sec toward target
  for _, p in pairs(World.players) do
    local tx = p.tx or p.x
    local ty = p.ty or p.y
    local dx = tx - p.x
    local dy = ty - p.y
    if math.abs(dx) < 0.01 and math.abs(dy) < 0.01 then
      p.x, p.y = tx, ty
    else
      local dist = math.sqrt(dx * dx + dy * dy)
      local step = speed * dt
      if step >= dist then
        p.x, p.y = tx, ty
      else
        p.x = p.x + dx / dist * step
        p.y = p.y + dy / dist * step
      end
    end
  end
end

function World.pending_count()
  return #World.pending
end

World.reset()

return World
