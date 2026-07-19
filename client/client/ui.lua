local UI = {}

function UI.panel(x, y, w, h)
  love.graphics.setColor(0.08, 0.08, 0.14, 0.92)
  love.graphics.rectangle("fill", x, y, w, h, 6, 6)
  love.graphics.setColor(0.75, 0.7, 0.35, 1)
  love.graphics.setLineWidth(2)
  love.graphics.rectangle("line", x, y, w, h, 6, 6)
  love.graphics.setColor(1, 1, 1, 1)
end

function UI.button(label, x, y, w, h, hover)
  if hover then
    love.graphics.setColor(0.35, 0.3, 0.15, 1)
  else
    love.graphics.setColor(0.18, 0.16, 0.28, 1)
  end
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)
  love.graphics.setColor(0.85, 0.8, 0.4, 1)
  love.graphics.rectangle("line", x, y, w, h, 4, 4)
  love.graphics.setColor(1, 1, 0.9, 1)
  local font = love.graphics.getFont()
  local tw = font:getWidth(label)
  local th = font:getHeight()
  love.graphics.print(label, x + (w - tw) / 2, y + (h - th) / 2)
  love.graphics.setColor(1, 1, 1, 1)
end

function UI.hit(mx, my, x, y, w, h)
  return mx >= x and mx <= x + w and my >= y and my <= y + h
end

function UI.field(label, value, x, y, w, h, focused)
  love.graphics.setColor(0.9, 0.85, 0.6, 1)
  love.graphics.print(label, x, y - 20)
  if focused then
    love.graphics.setColor(0.12, 0.14, 0.22, 1)
  else
    love.graphics.setColor(0.06, 0.06, 0.1, 1)
  end
  love.graphics.rectangle("fill", x, y, w, h, 3, 3)
  love.graphics.setColor(focused and 1 or 0.55, focused and 0.9 or 0.5, 0.3, 1)
  love.graphics.rectangle("line", x, y, w, h, 3, 3)
  love.graphics.setColor(1, 1, 1, 1)
  local display = value or ""
  if focused and (math.floor(love.timer.getTime() * 2) % 2 == 0) then
    display = display .. "|"
  end
  love.graphics.print(display, x + 8, y + (h - love.graphics.getFont():getHeight()) / 2)
end

return UI
