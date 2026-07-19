--- Inventory state placeholder — Phase 5.
local InventoryState = {}

function InventoryState:enter() end
function InventoryState:leave() end
function InventoryState:update(dt) end
function InventoryState:draw()
  love.graphics.clear(0.05, 0.08, 0.1)
  love.graphics.print("Inventory (Phase 5)", 40, 40)
end

return InventoryState
