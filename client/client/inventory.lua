--- Inventory state — Phase 5.
local Inventory = {
  items = {},
  equipment = {
    weapon = nil,
    armor = nil,
    shield = nil,
    helmet = nil,
  },
}

function Inventory.set(items, equipment)
  Inventory.items = items or {}
  if equipment then
    Inventory.equipment = equipment
  end
end

return Inventory
