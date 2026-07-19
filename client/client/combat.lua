--- Combat UI integration — wired in Phase 4.
local Combat = {
  active = false,
  enemy = nil,
  log = {},
}

function Combat.start(enemy)
  Combat.active = true
  Combat.enemy = enemy
  Combat.log = { "A " .. (enemy.name or "monster") .. " draws near!" }
end

function Combat.end_battle()
  Combat.active = false
  Combat.enemy = nil
end

function Combat.push(text)
  Combat.log[#Combat.log + 1] = text
  if #Combat.log > 8 then
    table.remove(Combat.log, 1)
  end
end

return Combat
