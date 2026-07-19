local Auth = require("client.auth")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Character = {
  list = {},
  selected = 1,
  creating = false,
  new_name = "Solo",
  error = nil,
  status = "Loading...",
}

function Character:enter()
  self.error = nil
  self.creating = false
  self:_reload()
end

function Character:_reload()
  local list, err = Auth.list_characters()
  if not list then
    self.error = tostring(err or "failed")
    self.list = {}
    self.status = nil
    return
  end
  self.list = list
  self.selected = 1
  self.status = #list == 0 and "No characters — create one" or (#list .. " character(s)")
end

function Character:leave() end

function Character:update(dt) end

function Character:draw()
  love.graphics.clear(0.05, 0.05, 0.09)
  local w, h = love.graphics.getDimensions()
  local pw, ph = 480, 420
  local px, py = (w - pw) / 2, (h - ph) / 2
  UI.panel(px, py, pw, ph)

  love.graphics.setColor(1, 0.92, 0.45)
  love.graphics.printf("Select Character", px, py + 18, pw, "center")
  love.graphics.setColor(0.7, 0.75, 0.8)
  love.graphics.printf("Logged in as " .. tostring(Session.username), px, py + 46, pw, "center")

  if self.creating then
    UI.field("Name", self.new_name, px + 40, py + 120, pw - 80, 32, true)
  else
    for i, c in ipairs(self.list) do
      local y = py + 90 + (i - 1) * 48
      local selected = i == self.selected
      love.graphics.setColor(selected and 0.3 or 0.12, selected and 0.28 or 0.12, selected and 0.12 or 0.18, 1)
      love.graphics.rectangle("fill", px + 40, y, pw - 80, 40, 4, 4)
      love.graphics.setColor(1, 1, 0.9)
      love.graphics.print(
        string.format("%s  —  Lv %d  HP %d/%d", c.name, c.level, c.current_hp, c.max_hp),
        px + 55,
        y + 10
      )
    end
  end

  local mx, my = love.mouse.getPosition()
  local by = py + ph - 70
  if self.creating then
    UI.button("Create", px + 40, by, 150, 36, UI.hit(mx, my, px + 40, by, 150, 36))
    UI.button("Cancel", px + pw - 190, by, 150, 36, UI.hit(mx, my, px + pw - 190, by, 150, 36))
  else
    UI.button("Enter World", px + 40, by, 150, 36, UI.hit(mx, my, px + 40, by, 150, 36))
    UI.button("New Hero", px + pw - 190, by, 150, 36, UI.hit(mx, my, px + pw - 190, by, 150, 36))
  end

  if self.error then
    love.graphics.setColor(1, 0.35, 0.35)
    love.graphics.printf(tostring(self.error), px + 20, py + ph - 110, pw - 40, "center")
  elseif self.status then
    love.graphics.setColor(0.6, 0.85, 0.6)
    love.graphics.printf(self.status, px + 20, py + ph - 110, pw - 40, "center")
  end
  love.graphics.setColor(1, 1, 1)
end

function Character:_enter_world()
  local c = self.list[self.selected]
  if not c then
    self.error = "Select or create a character"
    return
  end
  Session.character = c
  State.switch("overworld")
end

function Character:_create()
  local c, err = Auth.create_character(self.new_name)
  if not c then
    self.error = err
    if type(self.error) == "table" then
      self.error = "create failed"
    end
    return
  end
  self.creating = false
  self:_reload()
  for i, ch in ipairs(self.list) do
    if ch.id == c.id then
      self.selected = i
      break
    end
  end
end

function Character:keypressed(key)
  if self.creating then
    if key == "backspace" then
      self.new_name = self.new_name:sub(1, math.max(0, #self.new_name - 1))
    elseif key == "return" then
      self:_create()
    elseif key == "escape" then
      self.creating = false
    end
    return
  end
  if key == "up" then
    self.selected = math.max(1, self.selected - 1)
  elseif key == "down" then
    self.selected = math.min(#self.list, self.selected + 1)
  elseif key == "return" then
    self:_enter_world()
  elseif key == "n" then
    self.creating = true
    self.error = nil
  end
end

function Character:textinput(text)
  if self.creating and #self.new_name < 16 then
    self.new_name = self.new_name .. text
  end
end

function Character:mousepressed(x, y, button)
  if button ~= 1 then
    return
  end
  local w, h = love.graphics.getDimensions()
  local pw, ph = 480, 420
  local px, py = (w - pw) / 2, (h - ph) / 2
  local by = py + ph - 70

  if not self.creating then
    for i = 1, #self.list do
      local ly = py + 90 + (i - 1) * 48
      if UI.hit(x, y, px + 40, ly, pw - 80, 40) then
        self.selected = i
      end
    end
  end

  if self.creating then
    if UI.hit(x, y, px + 40, by, 150, 36) then
      self:_create()
    elseif UI.hit(x, y, px + pw - 190, by, 150, 36) then
      self.creating = false
    end
  else
    if UI.hit(x, y, px + 40, by, 150, 36) then
      self:_enter_world()
    elseif UI.hit(x, y, px + pw - 190, by, 150, 36) then
      self.creating = true
      self.error = nil
    end
  end
end

return Character
