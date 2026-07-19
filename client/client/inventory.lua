--- Shared inventory cache.
local Inventory = {
  items = {},
  equipment = {
    weapon = nil,
    armor = nil,
    shield = nil,
    helmet = nil,
  },
  bonuses = nil,
}

function Inventory.set(items, character)
  Inventory.items = items or {}
  if character then
    Inventory.equipment = {
      weapon = character.equipment_weapon,
      armor = character.equipment_armor,
      shield = character.equipment_shield,
      helmet = character.equipment_helmet,
    }
    Inventory.bonuses = character.bonuses
  end
end

return Inventory
