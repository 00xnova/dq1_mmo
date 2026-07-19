local World = {
  map = {
    {1,1,1,1,1,1,1,1},
    {1,0,0,0,0,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,0,0,0,0,0,0,1},
    {1,1,1,1,1,1,1,1},
  },
  tile_size = 48,
  players = {},
  local_player = nil,
}

function World.is_walkable(x, y)
  local row = World.map[y + 1]
  if not row then
    return false
  end
  return row[x + 1] == 0
end

function World.set_local(character)
  World.local_player = {
    id = character.id,
    name = character.name,
    x = math.floor(character.world_x or 4),
    y = math.floor(character.world_y or 4),
    level = character.level or 1,
  }
end

function World.set_players(list)
  World.players = {}
  for _, p in ipairs(list or {}) do
    World.players[p.id] = {
      id = p.id,
      name = p.name,
      x = math.floor(p.world_x or p.x or 0),
      y = math.floor(p.world_y or p.y or 0),
      level = p.level or 1,
    }
  end
end

function World.update_player(id, x, y)
  if World.local_player and World.local_player.id == id then
    World.local_player.x = x
    World.local_player.y = y
    return
  end
  local p = World.players[id]
  if p then
    p.x = x
    p.y = y
  end
end

return World
