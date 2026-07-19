local State = require("client.state")

local states = {
  login = require("states.login"),
  character = require("states.character"),
  overworld = require("states.overworld"),
}

function love.load()
  love.graphics.setDefaultFilter("nearest", "nearest")
  love.keyboard.setKeyRepeat(true)

  local font = love.graphics.newFont(16)
  love.graphics.setFont(font)

  State.register(states)
  State.switch("login")
end

function love.update(dt)
  State.update(dt)
end

function love.draw()
  State.draw()
end

function love.keypressed(key, scancode, isrepeat)
  State.keypressed(key, scancode, isrepeat)
end

function love.textinput(text)
  State.textinput(text)
end

function love.mousepressed(x, y, button)
  State.mousepressed(x, y, button)
end
