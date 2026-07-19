local Network = require("client.network")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")
local World = require("client.world")

local Inventory = {
  mode = "bag", -- bag | shop
  items = {},
  shop = {},
  selected = 1,
  status = "",
  character = nil,
}

local SLOTS = { "weapon", "armor", "shield", "helmet" }
local SLOT_LABEL = {
  weapon = "Weapon",
  armor = "Armor",
  shield = "Shield",
  helmet = "Helmet",
}

function Inventory:enter()
  self.mode = "bag"
  self.selected = 1
  self.status = "Loading…"
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
    local gold = tostring((self.character and self.character.gold) or "0")
    if data.sold and data.sold.gold_gained then
      local gained = tonumber(data.sold.gold_gained) or 0
      local name = data.sold.item_name or data.sold.item_id or "item"
      self.status = string.format("Sold %s +%d G · total %s G", tostring(name), gained, gold)
      UI.toast(self.status, "ok")
    elseif data.bought and data.bought.gold_spent then
      local spent = tonumber(data.bought.gold_spent) or 0
      local name = data.bought.item_name or data.bought.item_id or "item"
      self.status = string.format("Bought %s −%d G · total %s G", tostring(name), spent, gold)
      UI.toast(self.status, "ok")
    elseif data.message then
      self.status = tostring(data.message)
      UI.toast(self.status, "ok")
    else
      self.status = "Gold: " .. gold
    end
    if self.selected > math.max(1, #self.items) then
      self.selected = 1
    end
  end)
  Network.on("shop_list", function(data)
    self.shop = data.items or {}
    self.mode = "shop"
    self.selected = 1
    self.status = "Town shop — Enter buy · prices show sell-back"
  end)
  Network.on("error", function(data)
    local r = tostring(data.reason or "error")
    -- Mirror overworld inn/shop path: show how much gold is needed
    if data.cost and r == "not enough gold" then
      r = string.format("not enough gold (need %s G)", tostring(data.cost))
    end
    self.status = r
    UI.toast(r, "danger")
  end)
  Network.on("item_used", function(data)
    local line = data.message or ("Used " .. tostring(data.name or data.item_id or "item"))
    self.status = line
    UI.toast(line, "ok")
    if data.teleported and data.x and data.y then
      if Session.character then
        Session.character.world_x = data.x
        Session.character.world_y = data.y
      end
      if self.character then
        self.character.world_x = data.x
        self.character.world_y = data.y
      end
    end
    if data.current_hp and Session.character then
      Session.character.current_hp = data.current_hp
    end
    if self.character and data.current_hp then
      self.character.current_hp = data.current_hp
    end
  end)
  Network.on("spell_cast", function(data)
    if data.character then
      self.character = data.character
      Session.character = data.character
    end
    if data.teleported and data.x and data.y and Session.character then
      Session.character.world_x = data.x
      Session.character.world_y = data.y
    end
    self.status = data.message or "Spell cast"
    UI.toast(self.status, "ok")
  end)
  Network.on("rest_ok", function(data)
    if data.character then
      self.character = data.character
      Session.character = data.character
    end
    self.status = data.message or "Rested at the inn"
    UI.toast(self.status, "ok")
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
      -- Town only (tile code 2) — server also enforces this
      local c = self.character or Session.character or {}
      local x = math.floor(tonumber(c.world_x or c.x) or 2)
      local y = math.floor(tonumber(c.world_y or c.y) or 2)
      local row = World.map and World.map[y + 1]
      local tile = row and row[x + 1]
      if tile ~= 2 then
        self.status = "Shop only in town"
        UI.toast(self.status, "danger")
        return
      end
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
      local effect = def and def.effect
      if slot == "consumable" or effect then
        Network.send({ type = "use_item", item = item.item_id })
      elseif slot and slot ~= "consumable" then
        Network.send({ type = "equip", slot = slot, item = item.item_id })
      else
        self.status = "Can't use or equip that"
      end
    end
  elseif key == "u" and self.mode == "bag" then
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
  elseif key == "r" then
    Network.send({ type = "rest" })
  end
end

function Inventory:draw()
  UI.draw_bg()
  local w, h = love.graphics.getDimensions()
  local margin = 28
  UI.panel(margin, 20, w - margin * 2, h - 40, {
    title = self.mode == "shop" and "TOWN SHOP" or "INVENTORY",
    subtitle = self.mode == "shop" and "Tab → bag" or "Tab → shop",
    title_h = 36,
  })

  local c = self.character or {}
  local b = c.bonuses or {}
  local left_x = margin + 24
  local top = 72

  -- Hero summary card
  UI.panel(left_x, top, 280, 100, { no_ornament = true, radius = 5 })
  UI.set_font("body")
  UI.color("gold")
  love.graphics.print(tostring(c.name or "Hero"), left_x + 16, top + 14)
  UI.set_font("small")
  UI.color("text")
  love.graphics.print(string.format("Lv %d", tonumber(c.level or 1)), left_x + 16, top + 40)
  UI.color("gold")
  love.graphics.print(tostring(c.gold or "0") .. " G", left_x + 100, top + 40)
  UI.color("muted")
  love.graphics.print(
    string.format("ATK %s   DEF %s", tostring(b.attack_power or "—"), tostring(b.defense_power or "—")),
    left_x + 16,
    top + 66
  )

  -- Equipment panel
  UI.panel(left_x, top + 116, 280, 220, {
    title = "Equipment",
    title_h = 28,
    no_ornament = true,
  })
  local ey = top + 156
  for _, slot in ipairs(SLOTS) do
    local val = c["equipment_" .. slot]
    local label = SLOT_LABEL[slot] or slot
    UI.list_row(
      left_x + 12,
      ey,
      256,
      36,
      false,
      label,
      val and tostring(val) or "— empty —",
      { font = "small", right_color = val and "gold" or "muted" }
    )
    ey = ey + 42
  end

  -- Bag / shop list
  local rx = left_x + 300
  local rw = w - margin * 2 - 348
  UI.panel(rx, top, rw, h - top - 100, {
    title = self.mode == "shop" and "For sale" or "Bag",
    subtitle = self.status or "",
    title_h = 28,
    no_ornament = true,
  })

  local list = self:_list()
  local y = top + 48
  for i, item in ipairs(list) do
    if y + 40 > h - 110 then
      break
    end
    local name, extra, sub
    if self.mode == "shop" then
      name = item.name or item.id
      local buy = tonumber(item.price) or 0
      local sell = tonumber(item.sell_price)
      if sell == nil and buy > 0 then
        sell = math.max(1, math.floor(buy / 2))
      end
      if sell and sell > 0 then
        extra = string.format("%d G · sell %d", buy, sell)
      else
        extra = tostring(buy) .. " G"
      end
      sub = item.slot or item.kind or ""
    else
      local def = item["def"] or item.def or {}
      name = def.name or item.item_id or "?"
      local qty = tostring(item.quantity or 1)
      local sell = tonumber(item.sell_price) or tonumber(def.sell_price)
      if sell == nil then
        local p = tonumber(def.price) or 0
        if p > 0 then
          sell = math.max(1, math.floor(p / 2))
        end
      end
      if sell and sell > 0 then
        extra = "×" .. qty .. " · sell " .. tostring(sell) .. " G"
      else
        extra = "×" .. qty
      end
      sub = def.slot or ""
      if item.is_equipped or item.equipped then
        sub = (sub ~= "" and sub .. " · " or "") .. "equipped"
      end
    end
    UI.list_row(rx + 12, y, rw - 24, 40, i == self.selected, name, extra, { sub = sub, font = "body" })
    y = y + 46
  end
  if #list == 0 then
    UI.set_font("body")
    UI.color("muted")
    love.graphics.print(self.mode == "shop" and "Shop unavailable (town only)." or "Bag is empty.", rx + 24, top + 60)
  end

  UI.hint_bar(
    margin + 16,
    h - 68,
    w - margin * 2 - 32,
    36,
    "Enter equip/use/buy   ·   R inn rest   ·   S sell   ·   U unequip   ·   Tab shop   ·   Esc"
  )
  UI.reset_color()
end

return Inventory
