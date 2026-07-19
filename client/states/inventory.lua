local Network = require("client.network")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Inventory = {
  mode = "bag", -- bag | shop | equip
  items = {},
  shop = {},
  selected = 1,
  status = "",
  character = nil,
}

local SLOTS = { "weapon", "armor", "shield", "helmet" }

function Inventory:enter()
  self.mode = "bag"
  self.selected = 1
  self.status = "Loading..."
  self.character = Session.character
  self.items = {}
  self.shop = {}

  Network.clear_handlers()
  Network.on("inventory_update", function(data)
    self.items = data.items or {}
    if data.character then
      self.character = data.character
      Session.character = data.character
    end
    self.status = "Gold: " .. tostring((self.character and self.character.gold) or "0")
    if self.selected > math.max(1, #self.items) then
      self.selected = 1
    end
  end)
  Network.on("shop_list", function(data)
    self.shop = data.items or {}
    self.mode = "shop"
    self.selected = 1
    self.status = "Town shop — Enter buy, Esc back"
  end)
  Network.on("error", function(data)
    self.status = tostring(data.reason or "error")
  end)

  Network.send({ type = "inventory" })
end

function Inventory:leave() end

function Inventory:update(dt)
  Network.update(dt)
end

function Inventory:_list()
  if self.mode == "shop" then
    return self.shop
  end
  return self.items
end

function Inventory:keypressed(key)
  local list = self:_list()
  if key == "escape" then
    if self.mode == "shop" then
      self.mode = "bag"
      self.selected = 1
      self.status = "Inventory"
      return
    end
    -- persist character from inventory into session before world
    if self.character then
      Session.character = self.character
    end
    State.switch("overworld")
    return
  elseif key == "up" then
    self.selected = math.max(1, self.selected - 1)
  elseif key == "down" then
    self.selected = math.min(math.max(1, #list), self.selected + 1)
  elseif key == "tab" then
    if self.mode == "bag" then
      Network.send({ type = "shop" })
    else
      self.mode = "bag"
      self.status = "Inventory"
    end
  elseif key == "return" or key == "space" then
    local item = list[self.selected]
    if not item then
      return
    end
    if self.mode == "shop" then
      Network.send({ type = "buy", item = item.id })
    else
      local def = item["def"] or item.def
      local slot = def and def.slot
      if slot and slot ~= "consumable" then
        Network.send({ type = "equip", slot = slot, item = item.item_id })
      else
        self.status = "Can't equip that"
      end
    end
  elseif key == "u" and self.mode == "bag" then
    -- unequip first filled slot cycle
    local c = self.character or {}
    for _, slot in ipairs(SLOTS) do
      local keyname = "equipment_" .. slot
      if c[keyname] then
        Network.send({ type = "unequip", slot = slot })
        return
      end
    end
    self.status = "Nothing equipped"
  elseif key == "s" and self.mode == "bag" then
    local item = list[self.selected]
    if item then
      Network.send({ type = "sell", item = item.item_id })
    end
  end
end

function Inventory:draw()
  love.graphics.clear(0.05, 0.07, 0.1)
  local w, h = love.graphics.getDimensions()
  UI.panel(40, 30, w - 80, h - 60)

  love.graphics.setColor(1, 0.92, 0.45)
  local title = self.mode == "shop" and "SHOP" or "INVENTORY"
  love.graphics.print(title, 60, 50)

  local c = self.character or {}
  local b = c.bonuses or {}
  love.graphics.setColor(0.85, 0.9, 0.95)
  love.graphics.print(
    string.format(
      "%s  Lv%d  Gold %s  ATK %s  DEF %s",
      tostring(c.name or "?"),
      tonumber(c.level or 1),
      tostring(c.gold or "0"),
      tostring(b.attack_power or "?"),
      tostring(b.defense_power or "?")
    ),
    60,
    80
  )

  love.graphics.setColor(0.95, 0.85, 0.5)
  love.graphics.print("Equipment", 60, 120)
  love.graphics.setColor(0.85, 0.85, 0.9)
  local y = 145
  for _, slot in ipairs(SLOTS) do
    local val = c["equipment_" .. slot] or "(none)"
    love.graphics.print(string.format("%-8s %s", slot, tostring(val)), 70, y)
    y = y + 22
  end

  love.graphics.setColor(0.95, 0.85, 0.5)
  love.graphics.print(self.mode == "shop" and "For sale" or "Bag", w / 2, 120)
  local list = self:_list()
  y = 145
  for i, item in ipairs(list) do
    if i == self.selected then
      love.graphics.setColor(0.35, 0.3, 0.12)
      love.graphics.rectangle("fill", w / 2 - 10, y - 2, 320, 22, 3, 3)
    end
    love.graphics.setColor(1, 1, 0.9)
    local name, extra
    if self.mode == "shop" then
      name = item.name or item.id
      extra = tostring(item.price or 0) .. " G"
    else
      local def = item["def"] or item.def or {}
      name = (def.name or item.item_id) .. " x" .. tostring(item.quantity or 1)
      extra = def.slot or ""
    end
    love.graphics.print((i == self.selected and "> " or "  ") .. name .. "  " .. extra, w / 2, y)
    y = y + 24
  end
  if #list == 0 then
    love.graphics.setColor(0.6, 0.6, 0.7)
    love.graphics.print("(empty)", w / 2, 145)
  end

  love.graphics.setColor(0.7, 0.8, 0.75)
  love.graphics.print(self.status or "", 60, h - 90)
  love.graphics.print(
    "Enter: equip/buy  S: sell  U: unequip  Tab: shop  Esc: back",
    60,
    h - 65
  )
  love.graphics.setColor(1, 1, 1)
end

return Inventory
