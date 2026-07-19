local State = {
  current = nil,
  name = nil,
  stack = {},
  states = {},
}

function State.register(states)
  State.states = states
end

function State.switch(name, ...)
  if State.current and State.current.leave then
    State.current:leave()
  end
  local s = State.states[name]
  assert(s, "unknown state: " .. tostring(name))
  State.name = name
  State.current = s
  if s.enter then
    s:enter(...)
  end
end

function State.update(dt)
  if State.current and State.current.update then
    State.current:update(dt)
  end
end

function State.draw()
  if State.current and State.current.draw then
    State.current:draw()
  end
end

function State.keypressed(key, scancode, isrepeat)
  if State.current and State.current.keypressed then
    State.current:keypressed(key, scancode, isrepeat)
  end
end

function State.textinput(text)
  if State.current and State.current.textinput then
    State.current:textinput(text)
  end
end

function State.mousepressed(x, y, button)
  if State.current and State.current.mousepressed then
    State.current:mousepressed(x, y, button)
  end
end

return State
