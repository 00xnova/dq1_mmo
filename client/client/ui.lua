--- Shared Dragon Quest–style UI toolkit.

local UI = {
  fonts = {},
  theme = {
    bg_top = {0.07, 0.06, 0.14},
    bg_bot = {0.03, 0.04, 0.08},
    panel = {0.07, 0.08, 0.15, 0.96},
    panel_header = {0.12, 0.11, 0.22, 0.98},
    panel_inner = {0.04, 0.05, 0.10, 0.55},
    gold = {0.96, 0.84, 0.38},
    gold_bright = {1.0, 0.94, 0.55},
    gold_dim = {0.58, 0.48, 0.22},
    text = {0.96, 0.94, 0.90},
    muted = {0.62, 0.64, 0.72},
    danger = {1.0, 0.40, 0.40},
    ok = {0.48, 0.92, 0.58},
    accent = {0.45, 0.70, 1.0},
    hp = {0.88, 0.24, 0.30},
    hp_hi = {1.0, 0.42, 0.40},
    mp = {0.28, 0.50, 0.98},
    mp_hi = {0.48, 0.68, 1.0},
    btn = {0.14, 0.13, 0.24},
    btn_hover = {0.30, 0.26, 0.14},
    btn_press = {0.38, 0.32, 0.12},
    select = {0.30, 0.26, 0.12, 0.95},
    select_border = {0.96, 0.84, 0.38},
    local_p = {0.96, 0.86, 0.32},
    other_p = {0.42, 0.72, 1.0},
    shadow = {0, 0, 0, 0.45},
  },
  toasts = {},
  _t = 0,
  _stars = nil,
}

local function clamp01(x)
  return math.max(0, math.min(1, x))
end

function UI.init()
  UI.fonts.title = love.graphics.newFont(32)
  UI.fonts.large = love.graphics.newFont(22)
  UI.fonts.body = love.graphics.newFont(16)
  UI.fonts.small = love.graphics.newFont(13)
  UI.fonts.tiny = love.graphics.newFont(11)
  love.graphics.setFont(UI.fonts.body)
  UI._stars = {}
  for i = 1, 48 do
    UI._stars[i] = {
      x = love.math.random(),
      y = love.math.random() * 0.55,
      s = love.math.random() * 1.4 + 0.4,
      a = love.math.random() * 0.5 + 0.15,
      p = love.math.random() * math.pi * 2,
    }
  end
end

function UI.font(name)
  return UI.fonts[name] or UI.fonts.body
end

function UI.set_font(name)
  love.graphics.setFont(UI.font(name))
end

function UI.color(name, a)
  local c = UI.theme[name] or UI.theme.text
  love.graphics.setColor(c[1], c[2], c[3], a or c[4] or 1)
end

function UI.reset_color()
  love.graphics.setColor(1, 1, 1, 1)
end

function UI.mouse()
  return love.mouse.getPosition()
end

function UI.hit(mx, my, x, y, w, h)
  return mx >= x and mx <= x + w and my >= y and my <= y + h
end

--- Full-screen atmospheric background (starfield + vignette + floor glow).
function UI.draw_bg(opts)
  opts = opts or {}
  local w, h = love.graphics.getDimensions()
  local top = UI.theme.bg_top
  local bot = UI.theme.bg_bot
  -- vertical gradient via strips
  local strips = 24
  for i = 0, strips - 1 do
    local t = i / (strips - 1)
    love.graphics.setColor(
      top[1] + (bot[1] - top[1]) * t,
      top[2] + (bot[2] - top[2]) * t,
      top[3] + (bot[3] - top[3]) * t,
      1
    )
    love.graphics.rectangle("fill", 0, (h / strips) * i, w, h / strips + 1)
  end

  -- stars
  if UI._stars and not opts.plain then
    for _, s in ipairs(UI._stars) do
      local tw = 0.55 + 0.45 * math.sin(UI._t * 1.4 + s.p)
      love.graphics.setColor(0.9, 0.92, 1.0, s.a * tw)
      love.graphics.circle("fill", s.x * w, s.y * h, s.s)
    end
  end

  -- soft floor glow
  love.graphics.setColor(0.18, 0.14, 0.32, 0.22)
  love.graphics.ellipse("fill", w * 0.5, h * 0.92, w * 0.55, h * 0.18)

  -- vignette
  love.graphics.setColor(0, 0, 0, 0.28)
  love.graphics.rectangle("fill", 0, 0, w, 36)
  love.graphics.rectangle("fill", 0, h - 48, w, 48)
  love.graphics.setColor(0, 0, 0, 0.18)
  love.graphics.rectangle("fill", 0, 0, 28, h)
  love.graphics.rectangle("fill", w - 28, 0, 28, h)
end

--- Dim overlay for modal menus (combat/inventory over world).
function UI.dim(alpha)
  local w, h = love.graphics.getDimensions()
  love.graphics.setColor(0.02, 0.02, 0.06, alpha or 0.55)
  love.graphics.rectangle("fill", 0, 0, w, h)
end

--- Classic DQ window: shadow, fill, double gold frame, optional title bar.
function UI.panel(x, y, w, h, opts)
  opts = opts or {}
  local r = opts.radius or 6
  local title = opts.title
  local accent = opts.accent -- "danger" | "ok" | nil

  -- drop shadow
  love.graphics.setColor(0, 0, 0, 0.42)
  love.graphics.rectangle("fill", x + 4, y + 5, w, h, r, r)

  -- body
  UI.color("panel")
  love.graphics.rectangle("fill", x, y, w, h, r, r)

  -- subtle inner gradient strip at top
  love.graphics.setColor(1, 1, 1, 0.035)
  love.graphics.rectangle("fill", x + 2, y + 2, w - 4, math.min(28, h * 0.2), r - 1, r - 1)

  if title then
    local th = opts.title_h or 34
    love.graphics.setColor(UI.theme.panel_header[1], UI.theme.panel_header[2], UI.theme.panel_header[3], 0.98)
    love.graphics.rectangle("fill", x + 3, y + 3, w - 6, th, r - 1, r - 1)
    -- gold underline under header
    UI.color("gold_dim")
    love.graphics.setLineWidth(1)
    love.graphics.line(x + 10, y + 3 + th, x + w - 10, y + 3 + th)
    UI.set_font(opts.title_font or "body")
    UI.color("gold")
    local font = love.graphics.getFont()
    love.graphics.print(title, x + 14, y + 3 + (th - font:getHeight()) / 2)
    if opts.subtitle then
      UI.set_font("tiny")
      UI.color("muted")
      local sw = love.graphics.getFont():getWidth(opts.subtitle)
      love.graphics.print(opts.subtitle, x + w - 14 - sw, y + 3 + (th - love.graphics.getFont():getHeight()) / 2)
    end
  end

  -- double frame
  local border = accent == "danger" and "danger" or (accent == "ok" and "ok" or "gold")
  UI.color(border)
  love.graphics.setLineWidth(2)
  love.graphics.rectangle("line", x, y, w, h, r, r)
  UI.color(border == "gold" and "gold_dim" or border, 0.55)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x + 3, y + 3, w - 6, h - 6, math.max(1, r - 1), math.max(1, r - 1))

  -- corner ticks (DQ ornament)
  if not opts.no_ornament then
    UI.color("gold_bright", 0.85)
    local o = 8
    love.graphics.setLineWidth(2)
    love.graphics.line(x + o, y + 2, x + o + 10, y + 2)
    love.graphics.line(x + 2, y + o, x + 2, y + o + 10)
    love.graphics.line(x + w - o, y + 2, x + w - o - 10, y + 2)
    love.graphics.line(x + w - 2, y + o, x + w - 2, y + o + 10)
    love.graphics.line(x + o, y + h - 2, x + o + 10, y + h - 2)
    love.graphics.line(x + 2, y + h - o, x + 2, y + h - o - 10)
    love.graphics.line(x + w - o, y + h - 2, x + w - o - 10, y + h - 2)
    love.graphics.line(x + w - 2, y + h - o, x + w - 2, y + h - o - 10)
  end
  UI.reset_color()
end

function UI.button(label, x, y, w, h, hover, opts)
  opts = opts or {}
  local r = 5
  local primary = opts.primary
  -- shadow
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", x + 2, y + 3, w, h, r, r)

  if hover then
    UI.color("btn_hover")
  elseif primary then
    love.graphics.setColor(0.22, 0.18, 0.08, 1)
  else
    UI.color("btn")
  end
  love.graphics.rectangle("fill", x, y, w, h, r, r)

  -- top sheen
  love.graphics.setColor(1, 1, 1, hover and 0.08 or 0.04)
  love.graphics.rectangle("fill", x + 2, y + 2, w - 4, h * 0.4, r - 1, r - 1)

  UI.color(hover and "gold_bright" or (primary and "gold" or "gold_dim"))
  love.graphics.setLineWidth(hover and 2.5 or 2)
  love.graphics.rectangle("line", x, y, w, h, r, r)

  UI.set_font(opts.font or "body")
  UI.color(hover and "gold_bright" or "text")
  local font = love.graphics.getFont()
  love.graphics.print(label, x + (w - font:getWidth(label)) / 2, y + (h - font:getHeight()) / 2)
  UI.reset_color()
end

function UI.field(label, value, x, y, w, h, focused)
  UI.set_font("small")
  UI.color(focused and "gold_bright" or "gold")
  love.graphics.print(label, x, y - 18)

  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", x + 2, y + 2, w, h, 4, 4)

  if focused then
    love.graphics.setColor(0.14, 0.13, 0.22, 1)
  else
    love.graphics.setColor(0.05, 0.06, 0.11, 1)
  end
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)

  UI.color(focused and "gold" or "gold_dim")
  love.graphics.setLineWidth(focused and 2.5 or 1)
  love.graphics.rectangle("line", x, y, w, h, 4, 4)

  UI.set_font("body")
  UI.color("text")
  local display = value or ""
  if focused and (math.floor(UI._t * 2.2) % 2 == 0) then
    display = display .. "▌"
  end
  local font = love.graphics.getFont()
  love.graphics.print(display, x + 12, y + (h - font:getHeight()) / 2)
  UI.reset_color()
end

--- HP/MP bar with gloss and low-HP pulse.
function UI.bar(x, y, w, h, ratio, fill_name, label, opts)
  opts = opts or {}
  ratio = clamp01(ratio or 0)
  local r = 3

  love.graphics.setColor(0.05, 0.05, 0.08, 0.95)
  love.graphics.rectangle("fill", x, y, w, h, r, r)

  local fill = fill_name or "hp"
  local hi = fill == "mp" and "mp_hi" or "hp_hi"
  if ratio > 0 then
    local fw = math.max(2, w * ratio)
    local pulse = 1
    if fill == "hp" and ratio < 0.25 then
      pulse = 0.75 + 0.25 * math.sin(UI._t * 6)
    end
    local c = UI.theme[fill] or UI.theme.hp
    local ch = UI.theme[hi] or c
    love.graphics.setColor(c[1] * pulse, c[2] * pulse, c[3] * pulse, 1)
    love.graphics.rectangle("fill", x, y, fw, h, r, r)
    -- gloss
    love.graphics.setColor(ch[1], ch[2], ch[3], 0.35)
    love.graphics.rectangle("fill", x, y, fw, math.max(2, h * 0.4), r, r)
  end

  UI.color("gold_dim", 0.9)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", x, y, w, h, r, r)

  if label then
    UI.set_font("tiny")
    -- shadow text for readability
    love.graphics.setColor(0, 0, 0, 0.75)
    local font = love.graphics.getFont()
    local ty = y + (h - font:getHeight()) / 2
    love.graphics.print(label, x + 5, ty + 1)
    UI.color("text")
    love.graphics.print(label, x + 4, ty)
  end
  UI.reset_color()
end

function UI.title(text, x, y, w)
  UI.set_font("title")
  -- soft glow
  love.graphics.setColor(0.9, 0.7, 0.2, 0.18)
  if w then
    love.graphics.printf(text, x - 1, y + 1, w, "center")
    love.graphics.printf(text, x + 1, y + 1, w, "center")
  end
  UI.color("gold_bright")
  if w then
    love.graphics.printf(text, x, y, w, "center")
  else
    love.graphics.print(text, x, y)
  end
  -- underline ornament
  if w then
    local font = love.graphics.getFont()
    local tw = font:getWidth(text)
    local cx = x + w / 2
    UI.color("gold_dim")
    love.graphics.setLineWidth(1)
    love.graphics.line(cx - tw / 2 - 8, y + font:getHeight() + 4, cx + tw / 2 + 8, y + font:getHeight() + 4)
  end
  UI.reset_color()
end

function UI.subtitle(text, x, y, w)
  UI.set_font("small")
  UI.color("muted")
  if w then
    love.graphics.printf(text, x, y, w, "center")
  else
    love.graphics.print(text, x, y)
  end
  UI.reset_color()
end

function UI.text(text, x, y, style)
  style = style or "body"
  UI.set_font(style == "muted" and "small" or style)
  if style == "muted" then
    UI.color("muted")
  elseif style == "danger" then
    UI.color("danger")
  elseif style == "ok" then
    UI.color("ok")
  elseif style == "gold" then
    UI.color("gold")
  else
    UI.color("text")
  end
  love.graphics.print(text, x, y)
  UI.reset_color()
end

--- Selectable list row (menus, inventory, heroes).
function UI.list_row(x, y, w, h, selected, left, right, opts)
  opts = opts or {}
  local r = 4
  if selected then
    love.graphics.setColor(UI.theme.select[1], UI.theme.select[2], UI.theme.select[3], UI.theme.select[4] or 0.95)
    love.graphics.rectangle("fill", x, y, w, h, r, r)
    UI.color("gold")
    love.graphics.setLineWidth(2)
    love.graphics.rectangle("line", x, y, w, h, r, r)
    -- cursor arrow
    UI.set_font("body")
    UI.color("gold_bright")
    love.graphics.print("▶", x + 8, y + (h - love.graphics.getFont():getHeight()) / 2)
  else
    love.graphics.setColor(0.08, 0.09, 0.14, 0.55)
    love.graphics.rectangle("fill", x, y, w, h, r, r)
    UI.color("gold_dim", 0.35)
    love.graphics.setLineWidth(1)
    love.graphics.rectangle("line", x, y, w, h, r, r)
  end

  local pad = selected and 28 or 14
  UI.set_font(opts.font or "body")
  UI.color(selected and "text" or "muted")
  local font = love.graphics.getFont()
  love.graphics.print(left or "", x + pad, y + (h - font:getHeight()) / 2 - (opts.sub and 6 or 0))
  if opts.sub then
    UI.set_font("tiny")
    UI.color("muted")
    love.graphics.print(opts.sub, x + pad, y + h / 2 + 2)
  end
  if right then
    UI.set_font(opts.right_font or "small")
    UI.color(opts.right_color or (selected and "gold" or "muted"))
    local rf = love.graphics.getFont()
    love.graphics.print(right, x + w - 12 - rf:getWidth(right), y + (h - rf:getHeight()) / 2)
  end
  UI.reset_color()
end

--- Bottom keyboard hint strip.
function UI.hint_bar(x, y, w, h, text)
  UI.panel(x, y, w, h, { radius = 4, no_ornament = true })
  UI.set_font("small")
  UI.color("muted")
  local font = love.graphics.getFont()
  love.graphics.print(text, x + 14, y + (h - font:getHeight()) / 2)
  UI.reset_color()
end

--- Badge chip (zone, status).
function UI.badge(x, y, w, h, text, color_name)
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.rectangle("fill", x + 2, y + 2, w, h, 4, 4)
  love.graphics.setColor(0.08, 0.08, 0.14, 0.95)
  love.graphics.rectangle("fill", x, y, w, h, 4, 4)
  UI.color(color_name or "gold")
  love.graphics.setLineWidth(1.5)
  love.graphics.rectangle("line", x, y, w, h, 4, 4)
  UI.set_font("small")
  local font = love.graphics.getFont()
  love.graphics.print(text, x + (w - font:getWidth(text)) / 2, y + (h - font:getHeight()) / 2)
  UI.reset_color()
end

function UI.toast(message, kind, ttl)
  UI.toasts[#UI.toasts + 1] = {
    msg = tostring(message),
    kind = kind or "info",
    ttl = ttl or 3.5,
    age = 0,
  }
  while #UI.toasts > 6 do
    table.remove(UI.toasts, 1)
  end
end

function UI.update(dt)
  UI._t = (UI._t or 0) + (dt or 0)
  local i = 1
  while i <= #UI.toasts do
    local t = UI.toasts[i]
    t.age = t.age + dt
    if t.age >= t.ttl then
      table.remove(UI.toasts, i)
    else
      i = i + 1
    end
  end
end

function UI.draw_toasts()
  local w = love.graphics.getDimensions()
  local y = 16
  for i = #UI.toasts, 1, -1 do
    local t = UI.toasts[i]
    local alpha = 1
    if t.age < 0.15 then
      alpha = t.age / 0.15
    elseif t.age > t.ttl - 0.5 then
      alpha = (t.ttl - t.age) / 0.5
    end
    UI.set_font("small")
    local font = love.graphics.getFont()
    local tw = font:getWidth(t.msg) + 28
    local th = font:getHeight() + 14
    local x = w - tw - 16
    love.graphics.setColor(0, 0, 0, 0.4 * alpha)
    love.graphics.rectangle("fill", x + 2, y + 3, tw, th, 6, 6)
    love.graphics.setColor(0.06, 0.07, 0.12, 0.92 * alpha)
    love.graphics.rectangle("fill", x, y, tw, th, 6, 6)
    local border
    if t.kind == "join" or t.kind == "ok" then
      border = {0.4, 0.9, 0.55}
    elseif t.kind == "leave" or t.kind == "danger" then
      border = {1, 0.4, 0.4}
    else
      border = {0.95, 0.82, 0.4}
    end
    love.graphics.setColor(border[1], border[2], border[3], alpha)
    love.graphics.setLineWidth(1.5)
    love.graphics.rectangle("line", x, y, tw, th, 6, 6)
    love.graphics.setColor(1, 1, 1, alpha)
    love.graphics.print(t.msg, x + 14, y + 7)
    y = y + th + 8
  end
  UI.reset_color()
end

function UI.player_list(x, y, w, h, local_p, others, title, opts)
  opts = opts or {}
  -- mode "nearby" shows coords; "roster" shows zone/idle (no radar coords)
  local mode = opts.mode or "nearby"
  UI.panel(x, y, w, h, { title = title or "Adventurers", title_h = 30, no_ornament = true })
  local row = y + 42
  UI.set_font("small")
  if local_p then
    love.graphics.setColor(0.28, 0.24, 0.12, 0.9)
    love.graphics.rectangle("fill", x + 8, row - 2, w - 16, 24, 3, 3)
    UI.color("local_p")
    love.graphics.circle("fill", x + 20, row + 10, 5)
    UI.color("text")
    love.graphics.print(
      string.format("%s  Lv%d  (you)", local_p.name or "You", local_p.level or 1),
      x + 32,
      row + 4
    )
    row = row + 28
  end

  local count = 0
  local function draw_peer(p)
    count = count + 1
    if row + 24 > y + h - 12 then
      UI.color("muted")
      love.graphics.print("…", x + 32, row)
      return false
    end
    if p.in_combat then
      UI.color("danger")
    elseif p.idle then
      UI.color("muted")
    else
      UI.color("other_p")
    end
    love.graphics.circle("fill", x + 20, row + 10, 5)
    UI.color("text")
    local tags = ""
    if p.in_combat then
      tags = tags .. " ⚔"
    end
    if p.idle then
      tags = tags .. " zzz"
    end
    local loc = ""
    if mode == "roster" then
      if p.zone then
        loc = " [" .. tostring(p.zone) .. "]"
      end
    else
      if p.x ~= nil and p.y ~= nil then
        loc = string.format(" (%d,%d)", math.floor((p.x or 0) + 0.01), math.floor((p.y or 0) + 0.01))
      elseif p.zone then
        loc = " [" .. tostring(p.zone) .. "]"
      end
    end
    love.graphics.print(
      string.format("%s  Lv%d%s%s", p.name or "?", p.level or 1, loc, tags),
      x + 32,
      row + 4
    )
    row = row + 26
    return true
  end

  -- others may be map (nearby World.players) or array (roster)
  if type(others) == "table" then
    if others[1] ~= nil then
      for i = 1, #others do
        if not draw_peer(others[i]) then
          break
        end
      end
    else
      for _, p in pairs(others) do
        if not draw_peer(p) then
          break
        end
      end
    end
  end
  if count == 0 then
    UI.color("muted")
    local empty = mode == "roster" and "No one else online" or "No other adventurers nearby"
    love.graphics.print(empty, x + 20, row + 4)
  end
  UI.reset_color()
end

--- Character status sheet (DQ-style stats summary).
function UI.stats_sheet(x, y, w, h, char, opts)
  opts = opts or {}
  local c = char or {}
  UI.panel(x, y, w, h, {
    title = opts.title or "Status",
    subtitle = c.name or "Hero",
    title_h = 32,
    no_ornament = true,
  })
  local row = y + 44
  local lx = x + 16
  UI.set_font("small")

  local function line(label, value, color)
    UI.color("muted")
    love.graphics.print(label, lx, row)
    UI.color(color or "text")
    love.graphics.print(tostring(value), lx + 100, row)
    row = row + 20
  end

  line("Level", c.level or 1, "gold")
  local xp = c.experience or c.xp or 0
  local prog = c.xp_progress
  if type(prog) == "table" and prog.xp_to_next then
    if prog.max_level then
      line("EXP", tostring(xp) .. " (MAX)", "gold")
    else
      line(
        "EXP",
        string.format("%s  (+%s to next)", tostring(xp), tostring(prog.xp_to_next))
      )
    end
  else
    line("EXP", xp)
  end
  line("Gold", tostring(c.gold or "0") .. " G", "gold")
  local zone = opts.zone or c.zone
  if zone then
    line("Zone", tostring(zone):upper(), "accent")
  end
  local px, py = opts.x, opts.y
  if px ~= nil and py ~= nil then
    line("Pos", string.format("%d, %d", tonumber(px) or 0, tonumber(py) or 0), "muted")
  end
  local repel = opts.repel or c.repel
  local radiant = opts.radiant or c.radiant
  if repel and tonumber(repel) and tonumber(repel) > 0 then
    line("Repel", tostring(repel) .. " steps", "ok")
  end
  if radiant and tonumber(radiant) and tonumber(radiant) > 0 then
    line("Light", tostring(radiant) .. " steps", "accent")
  end
  row = row + 4
  local hp = tonumber(c.current_hp) or 0
  local mhp = math.max(1, tonumber(c.max_hp) or 1)
  local mp = tonumber(c.current_mp) or 0
  local mmp = math.max(0, tonumber(c.max_mp) or 0)
  UI.bar(lx, row, w - 32, 14, hp / mhp, "hp", string.format("HP  %d / %d", hp, mhp))
  row = row + 22
  if mmp > 0 then
    UI.bar(lx, row, w - 32, 12, mp / mmp, "mp", string.format("MP  %d / %d", mp, mmp))
    row = row + 20
  end
  row = row + 4
  line("Strength", c.strength or "-")
  line("Agility", c.agility or "-")
  local bon = c.bonuses or {}
  if bon.attack_power or bon.defense_power then
    line("ATK bonus", bon.attack_power or 0, "accent")
    line("DEF bonus", bon.defense_power or 0, "accent")
  end
  row = row + 4
  line("Weapon", c.equipment_weapon or "(none)")
  line("Armor", c.equipment_armor or "(none)")
  line("Shield", c.equipment_shield or "(none)")
  line("Helmet", c.equipment_helmet or "(none)")
  row = row + 6
  UI.color("muted")
  love.graphics.print("Field spells", lx, row)
  row = row + 18
  UI.color("text")
  local fs = c.field_spells or {}
  local ftxt = "(none)"
  if type(fs) == "table" and #fs > 0 then
    ftxt = table.concat(fs, ", ")
  end
  love.graphics.printf(ftxt, lx, row, w - 32, "left")
  row = row + 28
  UI.color("muted")
  love.graphics.print("Battle spells", lx, row)
  row = row + 18
  UI.color("text")
  local bs = c.known_spells or {}
  local btxt = "(none)"
  if type(bs) == "table" and #bs > 0 then
    btxt = table.concat(bs, ", ")
  end
  love.graphics.printf(btxt, lx, row, w - 32, "left")
  UI.reset_color()
end

function UI.chat_log(x, y, w, h, lines, draft, composing, channel)
  local ch = channel or "global"
  UI.panel(x, y, w, h, {
    title = ch == "nearby" and "Nearby chat" or "Chat",
    subtitle = "T global · Y nearby · /w · /z zone",
    title_h = 28,
    no_ornament = true,
  })
  local row = y + 38
  UI.set_font("tiny")
  local start = math.max(1, #lines - 5)
  for i = start, #lines do
    local line = lines[i]
    if line then
      local tag = ""
      if line.channel == "whisper" then
        tag = "[w] "
        UI.color("gold_bright")
      elseif line.channel == "nearby" then
        tag = "[near] "
        UI.color("ok")
      elseif line.channel == "zone" then
        tag = "[zone] "
        UI.color("gold")
      elseif line.channel == "system" or line.system then
        tag = "[*] "
        UI.color("gold_bright")
      elseif line.kind == "emote" then
        tag = "* "
        UI.color("gold")
      else
        UI.color("accent")
      end
      local who = line.name or "?"
      if line.channel == "whisper" and line.to then
        who = who .. " → " .. tostring(line.to)
      end
      local prefix = tag .. who .. ": "
      love.graphics.print(prefix, x + 12, row)
      local fw = love.graphics.getFont():getWidth(prefix)
      UI.color("text")
      love.graphics.print(line.text or "", x + 12 + fw, row)
      row = row + 15
    end
  end
  local input_y = y + h - 32
  love.graphics.setColor(0.04, 0.05, 0.09, 0.98)
  love.graphics.rectangle("fill", x + 8, input_y, w - 16, 24, 3, 3)
  UI.color(composing and "gold" or "gold_dim")
  love.graphics.setLineWidth(composing and 2 or 1)
  love.graphics.rectangle("line", x + 8, input_y, w - 16, 24, 3, 3)
  UI.set_font("small")
  UI.color(composing and "text" or "muted")
  local display = draft or ""
  if composing and (math.floor(UI._t * 2.2) % 2 == 0) then
    display = display .. "▌"
  elseif not composing and display == "" then
    display = "Press T to speak…"
  end
  love.graphics.print(display, x + 14, input_y + 5)
  UI.reset_color()
end

function UI.minimap(x, y, size, world)
  if not world or not world.map then
    return
  end
  local mw = world.width
  local mh = world.height
  local tw = size / mw
  local th = size / mh
  UI.panel(x - 6, y - 6, size + 12, size + 28, { title = "Map", title_h = 22, no_ornament = true, title_font = "tiny" })
  local map_y = y + 20
  for j = 1, mh do
    for i = 1, mw do
      local tile = world.map[j][i]
      if tile == 1 then
        love.graphics.setColor(0.18, 0.16, 0.26)
      elseif tile == 2 then
        love.graphics.setColor(0.52, 0.44, 0.30)
      elseif tile == 3 then
        love.graphics.setColor(0.14, 0.32, 0.58)
      elseif tile == 4 then
        love.graphics.setColor(0.30, 0.20, 0.38)
      else
        love.graphics.setColor(0.16, 0.42, 0.22)
      end
      love.graphics.rectangle("fill", x + (i - 1) * tw, map_y + (j - 1) * th, tw + 0.5, th + 0.5)
    end
  end
  for _, p in pairs(world.players or {}) do
    if p.in_combat then
      UI.color("danger")
    else
      UI.color("other_p")
    end
    love.graphics.circle("fill", x + (p.x + 0.5) * tw, map_y + (p.y + 0.5) * th, math.max(2, tw * 0.4))
  end
  if world.local_player then
    local lp = world.local_player
    UI.color("local_p")
    love.graphics.circle("fill", x + (lp.x + 0.5) * tw, map_y + (lp.y + 0.5) * th, math.max(2.5, tw * 0.45))
  end
  UI.reset_color()
end

--- Procedural enemy figure when Assets.enemy(id) has no PNG.
function UI.draw_enemy_figure(cx, cy, name, pulse)
  pulse = pulse or 1
  local bob = math.sin(UI._t * 2.2) * 4
  local y = cy + bob
  -- shadow
  love.graphics.setColor(0, 0, 0, 0.4)
  love.graphics.ellipse("fill", cx, cy + 48, 42, 12)
  -- body
  love.graphics.setColor(0.72 * pulse, 0.22, 0.32, 1)
  love.graphics.circle("fill", cx, y, 46)
  love.graphics.setColor(0.95, 0.35, 0.4, 0.35)
  love.graphics.circle("fill", cx - 12, y - 14, 16)
  -- outline
  love.graphics.setColor(0.15, 0.05, 0.08, 1)
  love.graphics.setLineWidth(3)
  love.graphics.circle("line", cx, y, 46)
  -- eyes
  love.graphics.setColor(1, 0.95, 0.85, 1)
  love.graphics.circle("fill", cx - 14, y - 6, 7)
  love.graphics.circle("fill", cx + 14, y - 6, 7)
  love.graphics.setColor(0.1, 0.05, 0.08, 1)
  love.graphics.circle("fill", cx - 12, y - 5, 3)
  love.graphics.circle("fill", cx + 16, y - 5, 3)
  -- name plate
  if name then
    UI.set_font("body")
    local font = love.graphics.getFont()
    local tw = font:getWidth(name) + 20
    local nx, ny = cx - tw / 2, y - 78
    love.graphics.setColor(0.05, 0.04, 0.08, 0.85)
    love.graphics.rectangle("fill", nx, ny, tw, 26, 4, 4)
    UI.color("danger")
    love.graphics.setLineWidth(1.5)
    love.graphics.rectangle("line", nx, ny, tw, 26, 4, 4)
    UI.color("text")
    love.graphics.print(name, nx + 10, ny + 5)
  end
  UI.reset_color()
end

--- Hero figure for combat (simple knight silhouette).
function UI.draw_hero_figure(cx, cy)
  local bob = math.sin(UI._t * 2.5 + 1) * 3
  local y = cy + bob
  love.graphics.setColor(0, 0, 0, 0.35)
  love.graphics.ellipse("fill", cx, cy + 40, 28, 9)
  -- body
  UI.color("local_p")
  love.graphics.circle("fill", cx, y - 8, 22)
  love.graphics.rectangle("fill", cx - 12, y + 8, 24, 28, 3, 3)
  love.graphics.setColor(0.1, 0.08, 0.05, 1)
  love.graphics.setLineWidth(2)
  love.graphics.circle("line", cx, y - 8, 22)
  UI.reset_color()
end

return UI
