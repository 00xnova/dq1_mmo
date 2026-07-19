local Auth = require("client.auth")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")

local Login = {
  mode = "login", -- login | register
  fields = {
    email = "hero@example.com",
    password = "password",
    username = "Hero",
  },
  focus = "email",
  order = { "email", "password", "username" },
  error = nil,
  status = nil,
}

function Login:enter()
  self.error = nil
  self.status = "Server: " .. Session.server_http
end

function Login:leave() end

function Login:update(dt) end

function Login:draw()
  love.graphics.clear(0.05, 0.05, 0.09)
  local w, h = love.graphics.getDimensions()
  local pw, ph = 420, self.mode == "register" and 360 or 300
  local px, py = (w - pw) / 2, (h - ph) / 2

  UI.panel(px, py, pw, ph)
  love.graphics.setColor(1, 0.92, 0.45)
  love.graphics.printf("DRAGON QUEST 1 MMO", px, py + 20, pw, "center")
  love.graphics.setColor(0.8, 0.8, 0.85)
  love.graphics.printf(self.mode == "login" and "Login" or "Register", px, py + 48, pw, "center")

  local fx = px + 40
  local fy = py + 90
  UI.field("Email", self.fields.email, fx, fy, pw - 80, 32, self.focus == "email")
  UI.field("Password", string.rep("*", #self.fields.password), fx, fy + 70, pw - 80, 32, self.focus == "password")
  if self.mode == "register" then
    UI.field("Username", self.fields.username, fx, fy + 140, pw - 80, 32, self.focus == "username")
  end

  local by = py + ph - 70
  local mx, my = love.mouse.getPosition()
  local b1 = { x = px + 40, y = by, w = 150, h = 36 }
  local b2 = { x = px + pw - 190, y = by, w = 150, h = 36 }
  UI.button(self.mode == "login" and "Login" or "Create", b1.x, b1.y, b1.w, b1.h, UI.hit(mx, my, b1.x, b1.y, b1.w, b1.h))
  UI.button(self.mode == "login" and "Register" or "Back", b2.x, b2.y, b2.w, b2.h, UI.hit(mx, my, b2.x, b2.y, b2.w, b2.h))

  if self.error then
    love.graphics.setColor(1, 0.35, 0.35)
    love.graphics.printf(tostring(self.error), px + 20, py + ph - 100, pw - 40, "center")
  elseif self.status then
    love.graphics.setColor(0.6, 0.85, 0.6)
    love.graphics.printf(self.status, px + 20, py + ph - 100, pw - 40, "center")
  end
  love.graphics.setColor(1, 1, 1, 1)
end

function Login:_submit()
  self.error = nil
  local ok, err
  if self.mode == "login" then
    ok, err = Auth.login(self.fields.email, self.fields.password)
  else
    ok, err = Auth.register(self.fields.email, self.fields.password, self.fields.username)
  end
  if not ok then
    self.error = tostring(err or "request failed")
    return
  end
  State.switch("character")
end

function Login:keypressed(key)
  if key == "tab" then
    local order = self.mode == "register" and self.order or { "email", "password" }
    local idx = 1
    for i, name in ipairs(order) do
      if name == self.focus then
        idx = i
        break
      end
    end
    self.focus = order[(idx % #order) + 1]
  elseif key == "return" or key == "kpenter" then
    self:_submit()
  elseif key == "backspace" then
    local v = self.fields[self.focus] or ""
    self.fields[self.focus] = v:sub(1, math.max(0, #v - 1))
  end
end

function Login:textinput(text)
  if not self.focus then
    return
  end
  local v = self.fields[self.focus] or ""
  if #v < 64 then
    self.fields[self.focus] = v .. text
  end
end

function Login:mousepressed(x, y, button)
  if button ~= 1 then
    return
  end
  local w, h = love.graphics.getDimensions()
  local pw, ph = 420, self.mode == "register" and 360 or 300
  local px, py = (w - pw) / 2, (h - ph) / 2
  local fx = px + 40
  local fy = py + 90
  if UI.hit(x, y, fx, fy, pw - 80, 32) then
    self.focus = "email"
  elseif UI.hit(x, y, fx, fy + 70, pw - 80, 32) then
    self.focus = "password"
  elseif self.mode == "register" and UI.hit(x, y, fx, fy + 140, pw - 80, 32) then
    self.focus = "username"
  end

  local by = py + ph - 70
  local b1 = { x = px + 40, y = by, w = 150, h = 36 }
  local b2 = { x = px + pw - 190, y = by, w = 150, h = 36 }
  if UI.hit(x, y, b1.x, b1.y, b1.w, b1.h) then
    self:_submit()
  elseif UI.hit(x, y, b2.x, b2.y, b2.w, b2.h) then
    self.mode = self.mode == "login" and "register" or "login"
    self.error = nil
  end
end

return Login
