--- Combat state placeholder — Phase 4.
local CombatState = {}

function CombatState:enter() end
function CombatState:leave() end
function CombatState:update(dt) end
function CombatState:draw()
  love.graphics.clear(0.1, 0.05, 0.08)
  love.graphics.print("Combat (Phase 4)", 40, 40)
end

return CombatState
