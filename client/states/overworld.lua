local Network = require("client.network")
local Renderer = require("client.renderer")
local Session = require("client.session")
local State = require("client.state")
local UI = require("client.ui")
local World = require("client.world")

local EMOTES = { "wave", "bow", "cheer", "dance", "laugh", "point", "think", "cry", "sit" }

local Overworld = {
  status = "",
  move_cooldown = 0,
  zone = "town",
  locked = false,
  net_info = "",
  online = 0,
  roster = {},
  repel = 0,
  radiant = 0,
  show_list = true,
  show_stats = false,
  chat_log = {},
  chat_draft = "",
  chat_open = false,
  chat_channel = "global", -- global | nearby
  show_chat = true,
  _emote_i = 0,
}

local MOVE_COOLDOWN = 0.12
local MAX_PENDING = 3

local function zone_name(x, y)
  local row = World.map and World.map[y + 1]
  if not row then
    return "?"
  end
  local t = row[x + 1]
  if t == 2 then
    return "town"
  end
  if t == 0 then
    return "field"
  end
  if t == 4 then
    return "dungeon"
  end
  if t == 3 then
    return "water"
  end
  return "wall"
end

local function zone_color(z)
  if z == "town" then
    return "gold"
  end
  if z == "dungeon" then
    return "accent"
  end
  if z == "field" then
    return "ok"
  end
  return "muted"
end

local function bind_handlers(self)
  Network.clear_handlers()

  Network.on("auth_ok", function(data)
    self.status = "Connected"
    self.locked = false
    -- Clean multipresence after reconnect (avoid ghost remotes)
    World.players = {}
    World.pending = {}
    self.roster = {}
    if data.session_id then
      Session.session_id = data.session_id
    end
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.character then
      Session.character = data.character
      World.set_local(data.character)
    end
    if data.map then
      World.set_map(data.map)
    end
    if World.local_player then
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
    if data.welcome and tostring(data.welcome) ~= "" then
      UI.toast(tostring(data.welcome), "ok")
    else
      UI.toast("Entered the world", "ok")
    end
    -- Presence snapshot follows as world_state; ask again if reconnect was messy
    Network.send({ type = "sync" })
  end)

  Network.on("combat_resume", function(data)
    self.locked = true
    World.pending = {}
    UI.toast("Battle resumed!", "danger")
    State.switch("combat", data)
  end)

  Network.on("auth_fail", function(data)
    self.status = "Auth failed: " .. tostring(data.reason)
    UI.toast("Auth failed", "danger")
  end)

  Network.on("world_state", function(data)
    if data.map then
      World.set_map(data.map)
    end
    World.set_players(data.players)
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.repel ~= nil then
      self.repel = tonumber(data.repel) or 0
    end
    if data.radiant ~= nil then
      self.radiant = tonumber(data.radiant) or 0
    end
    if data.you and World.local_player and World.pending_count() == 0 then
      World.local_player.x = math.floor(data.you.x)
      World.local_player.y = math.floor(data.you.y)
      World.server_x = World.local_player.x
      World.server_y = World.local_player.y
      self.zone = zone_name(World.local_player.x, World.local_player.y)
    end
    -- Soft-reconnect hygiene toast (mute list / whisper partner / buffs)
    if type(data.restored) == "table" then
      local bits = {}
      if data.restored.ignores then
        bits[#bits + 1] = "mute list"
      end
      if data.restored.last_whisper then
        bits[#bits + 1] = "last whisper"
      end
      if data.restored.repel or data.restored.radiant then
        bits[#bits + 1] = "buffs"
      end
      if #bits > 0 then
        UI.toast("Restored: " .. table.concat(bits, ", "), "info")
      end
    end
  end)

  Network.on("who", function(data)
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.players then
      World.set_players(data.players)
    end
    if data.you and data.you.repel ~= nil then
      self.repel = tonumber(data.you.repel) or 0
    end
    if data.you and data.you.radiant ~= nil then
      self.radiant = tonumber(data.you.radiant) or 0
    end
    if data.radiant ~= nil then
      self.radiant = tonumber(data.radiant) or 0
    end
    self.roster = data.roster or self.roster
    self.zones = data.zones or self.zones
    local n = 0
    for _ in pairs(World.players) do
      n = n + 1
    end
    local roster_n = type(self.roster) == "table" and #self.roster or (self.online or 0)
    local extra = ""
    if (self.repel or 0) > 0 then
      extra = string.format(" · repel %d", self.repel)
    end
    local z = self.zones
    local zone_bit = ""
    if type(z) == "table" then
      zone_bit = string.format(
        " · town %d · field %d · dung %d",
        tonumber(z.town) or 0,
        tonumber(z.field) or 0,
        tonumber(z.dungeon) or 0
      )
    end
    UI.toast(string.format("Online %d · nearby %d%s%s", roster_n, n, zone_bit, extra), "info")
  end)

  Network.on("near", function(data)
    if data.players then
      World.set_players(data.players)
    end
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.zone then
      self.zone = data.zone
    end
    local n = tonumber(data.nearby_count)
    if not n then
      n = type(data.players) == "table" and #data.players or 0
    end
    local names = {}
    for _, p in ipairs(data.players or {}) do
      if p.name then
        names[#names + 1] = tostring(p.name)
      end
    end
    local bit = (#names > 0) and (" · " .. table.concat(names, ", ")) or " · none"
    local zbit = data.zone and (" [" .. tostring(data.zone) .. "]") or ""
    UI.toast(string.format("Nearby %d%s%s", n, zbit, bit), "info")
  end)

  Network.on("zone", function(data)
    if data.zone then
      self.zone = data.zone
    end
    if data.zones then
      self.zones = data.zones
    end
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.x ~= nil then
      self.status_x = tonumber(data.x)
    end
    if data.y ~= nil then
      self.status_y = tonumber(data.y)
    end
    local z = data.zones or {}
    local msg = data.message or ("Zone: " .. tostring(data.zone or "?"))
    local pop = string.format(
      " · town %d · field %d · dung %d · online %d",
      tonumber(z.town) or 0,
      tonumber(z.field) or 0,
      tonumber(z.dungeon) or 0,
      tonumber(data.online) or self.online or 0
    )
    if data.x ~= nil and data.y ~= nil then
      pop = pop .. string.format(" · (%d,%d)", tonumber(data.x) or 0, tonumber(data.y) or 0)
    end
    -- Same-zone roster (names only — no other players' coordinates)
    local here = data.players
    if type(here) == "table" and #here > 0 then
      local names = {}
      for i = 1, math.min(#here, 8) do
        local p = here[i]
        names[#names + 1] = tostring(p.name or "?")
      end
      local extra = (#here > 8) and (" +" .. tostring(#here - 8)) or ""
      pop = pop .. " · here: " .. table.concat(names, ", ") .. extra
    end
    UI.toast(tostring(msg) .. pop, "info")
  end)

  Network.on("counts", function(data)
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.zones then
      self.zones = data.zones
    end
    local line = data.message
    if not line or line == "" then
      local z = data.zones or {}
      line = string.format(
        "Online %d · nearby %d · town %d · field %d · dung %d",
        tonumber(data.online) or self.online or 0,
        tonumber(data.nearby_count) or 0,
        tonumber(z.town) or 0,
        tonumber(z.field) or 0,
        tonumber(z.dungeon) or 0
      )
    end
    UI.toast(tostring(line), "info")
  end)

  Network.on("online", function(data)
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    if data.roster then
      self.roster = data.roster
    end
    if data.zones then
      self.zones = data.zones
    end
  end)

  Network.on("status", function(data)
    if data.character then
      Session.character = Session.character or {}
      for k, v in pairs(data.character) do
        Session.character[k] = v
      end
    end
    if data.you then
      if data.you.repel ~= nil then
        self.repel = tonumber(data.you.repel) or 0
      end
      if data.you.radiant ~= nil then
        self.radiant = tonumber(data.you.radiant) or 0
      end
      if data.you.zone then
        self.zone = data.you.zone
      end
      -- Self coords for meetup / navigation (own position only)
      if data.you.x ~= nil then
        self.status_x = tonumber(data.you.x)
      end
      if data.you.y ~= nil then
        self.status_y = tonumber(data.you.y)
      end
    end
    if data.online ~= nil then
      self.online = tonumber(data.online) or self.online
    end
    self.show_stats = true
  end)

  Network.on("find", function(data)
    local players = data.players or {}
    local n = #players
    if n == 0 then
      UI.toast("No online match for " .. tostring(data.query or "?"), "info")
      return
    end
    local names = {}
    for i = 1, math.min(n, 6) do
      local p = players[i]
      local bit = string.format("%s Lv%d", tostring(p.name or "?"), tonumber(p.level) or 1)
      if p.zone then
        bit = bit .. " [" .. tostring(p.zone) .. "]"
      end
      names[#names + 1] = bit
    end
    local more = n > 6 and (" +" .. tostring(n - 6)) or ""
    UI.toast(string.format("Find (%d): %s%s", n, table.concat(names, ", "), more), "info")
  end)

  Network.on("help", function(data)
    local cmds = data.commands or {}
    local bits = {}
    for i = 1, math.min(#cmds, 8) do
      local c = cmds[i]
      bits[#bits + 1] = tostring(c.hint or c.cmd or "?")
    end
    UI.toast(table.concat(bits, " · "), "info")
    if data.version then
      self.net_info = "v" .. tostring(data.version)
    end
  end)

  Network.on("version", function(data)
    local ver = tostring(data.version or "?")
    local on = tonumber(data.online) or 0
    local up = tonumber(data.uptime) or 0
    self.net_info = "v" .. ver
    UI.toast(string.format("Server v%s · %d online · up %ds", ver, on, up), "info")
  end)

  Network.on("time", function(data)
    local hms = tostring(data.uptime_hms or ((data.uptime or 0) .. "s"))
    local ver = data.version and (" · v" .. tostring(data.version)) or ""
    UI.toast(string.format("Server uptime %s%s", hms, ver), "info")
  end)

  Network.on("motd", function(data)
    local t = tostring(data.text or data.message or "…")
    UI.toast(t, "info")
    if data.version then
      self.net_info = "v" .. tostring(data.version)
    end
  end)

  Network.on("afk", function(data)
    if data.afk then
      UI.toast(tostring(data.message or "You are now AFK."), "info")
    else
      UI.toast(tostring(data.message or "Welcome back."), "info")
    end
  end)

  Network.on("quit", function(data)
    UI.toast(tostring(data.message or "Farewell, hero."), "info")
    -- Graceful leave: close after short toast
    if Network.disconnect then
      Network.disconnect()
    end
  end)

  Network.on("gold", function(data)
    UI.toast(tostring(data.message or ("Gold: " .. tostring(data.gold or "?"))), "info")
  end)

  Network.on("vitals", function(data)
    UI.toast(tostring(data.message or "Vitals updated"), "info")
  end)

  Network.on("xp", function(data)
    UI.toast(tostring(data.message or "XP updated"), "info")
  end)

  Network.on("buffs", function(data)
    UI.toast(tostring(data.message or "No active buffs."), "info")
    if data.repel ~= nil then
      self.repel = tonumber(data.repel) or 0
    end
    if data.radiant ~= nil then
      self.radiant = tonumber(data.radiant) or 0
    end
  end)

  Network.on("controls", function(data)
    UI.toast(tostring(data.message or "Controls updated"), "info")
  end)

  Network.on("played", function(data)
    UI.toast(tostring(data.message or "Session time updated"), "info")
  end)

  Network.on("stuck", function(data)
    UI.toast(tostring(data.message or "Returned to town."), "info")
    if data.x and data.y and World.local_player then
      World.local_player.x = tonumber(data.x) or World.local_player.x
      World.local_player.y = tonumber(data.y) or World.local_player.y
      World.server_x = World.local_player.x
      World.server_y = World.local_player.y
    end
  end)

  Network.on("emotes", function(data)
    UI.toast(tostring(data.message or "Emotes updated"), "info")
  end)

  Network.on("lastwhisper", function(data)
    UI.toast(tostring(data.message or "No one to reply to yet."), "info")
  end)

  Network.on("spells", function(data)
    UI.toast(tostring(data.message or "Spells updated"), "info")
  end)

  Network.on("ignore", function(data)
    local act = data.action or "?"
    if act == "list" then
      local list = data.ignores or {}
      local n = #list
      if n == 0 then
        UI.toast("Ignore list empty", "info")
        return
      end
      local names = {}
      for i = 1, math.min(n, 6) do
        names[#names + 1] = tostring(list[i].name or list[i].id or "?")
      end
      local more = n > 6 and (" +" .. tostring(n - 6)) or ""
      UI.toast(string.format("Ignoring %d: %s%s", n, table.concat(names, ", "), more), "info")
      return
    end
    local pname = (data.player and data.player.name) or data.player_id or "?"
    if act == "ignore" then
      UI.toast("Ignoring " .. tostring(pname), "info")
    elseif act == "unignore" then
      UI.toast("Unignored " .. tostring(pname), "info")
    end
  end)

  Network.on("move_ok", function(data)
    World.apply_move_ok(data)
    if World.local_player then
      local prev = self.zone
      -- Prefer server zone (authoritative); fall back to local tile map
      if data.zone and data.zone ~= "" then
        self.zone = tostring(data.zone)
      else
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
      -- Soft notice when entering a different area type
      if data.ok ~= false and prev and self.zone and prev ~= self.zone then
        if self.zone == "dungeon" then
          UI.toast("Entered the dungeon", "accent")
        elseif self.zone == "town" and prev ~= "town" then
          UI.toast("Back in town", "gold")
        elseif self.zone == "field" and prev == "dungeon" then
          UI.toast("Out of the dungeon", "ok")
        end
      end
    end
    if data.ok == false and data.reason and data.reason ~= "rate_limit" and data.reason ~= "in combat" then
      self.status = "Move: " .. tostring(data.reason)
    end
  end)

  Network.on("player_moved", function(data)
    World.update_player(data.player_id, data.x, data.y, {
      name = data.name,
      level = data.level,
      in_combat = data.in_combat,
      idle = data.idle,
      zone = data.zone,
    })
  end)

  Network.on("player_joined", function(data)
    local id = data.player_id
    local existing = World.players[id]
    World.players[id] = {
      id = id,
      name = data.name or (existing and existing.name) or ("P" .. tostring(id)),
      x = math.floor(data.x or 0),
      y = math.floor(data.y or 0),
      tx = math.floor(data.x or 0),
      ty = math.floor(data.y or 0),
      level = data.level or (existing and existing.level) or 1,
      in_combat = data.in_combat and true or false,
      idle = data.idle and true or false,
      afk = data.afk and true or false,
      zone = data.zone or (existing and existing.zone),
    }
    if not existing then
      local zbit = data.zone and (" [" .. tostring(data.zone) .. "]") or ""
      UI.toast((data.name or "Hero") .. " appeared nearby" .. zbit, "join")
    end
  end)

  Network.on("player_left", function(data)
    local p = World.players[data.player_id]
    local name = data.name or (p and p.name) or ("#" .. tostring(data.player_id))
    World.remove_player(data.player_id)
    if data.reason == "out_of_range" then
      -- quiet — walking out of range is normal
    elseif data.reason == "idle" then
      UI.toast(name .. " went idle", "leave")
    else
      UI.toast(name .. " left the area", "leave")
    end
  end)

  Network.on("player_update", function(data)
    World.update_player(data.player_id, data.x, data.y, {
      name = data.name,
      level = data.level,
      in_combat = data.in_combat,
      idle = data.idle,
      afk = data.afk,
    })
    -- Keep online roster combat/idle/AFK flags fresh without a full /who
    if type(self.roster) == "table" and data.player_id then
      for _, r in ipairs(self.roster) do
        if r.id == data.player_id or r.name == data.name then
          if data.in_combat ~= nil then
            r.in_combat = data.in_combat
          end
          if data.idle ~= nil then
            r.idle = data.idle
          end
          if data.afk ~= nil then
            r.afk = data.afk
          end
          if data.level ~= nil then
            r.level = data.level
          end
          break
        end
      end
    end
  end)

  Network.on("chat", function(data)
    self.chat_log[#self.chat_log + 1] = {
      name = data.name or "?",
      text = data.text or "",
      player_id = data.player_id,
      channel = data.channel or "global",
      to = data.to,
    }
    while #self.chat_log > 40 do
      table.remove(self.chat_log, 1)
    end
    if data.channel == "whisper" then
      -- Own echo vs incoming: don't claim "Whisper from yourself"
      local me = World.local_player and World.local_player.name
      local is_self = data.name and me and data.name == me
      if not is_self and data.name and data.name ~= "System" then
        self.last_whisper_from = data.name
        UI.toast("Whisper from " .. tostring(data.name), "info")
      elseif is_self then
        local tip = data.target_afk and " (they are AFK)" or ""
        UI.toast("Whisper to " .. tostring(data.to or "?") .. tip, "info")
      end
    end
  end)

  Network.on("look", function(data)
    local p = data.player or data
    if not p or not p.name then
      return
    end
    local loc = ""
    if p.nearby and p.x and p.y then
      loc = string.format(" @ (%d,%d)", math.floor(p.x + 0.01), math.floor(p.y + 0.01))
    elseif p.nearby == false then
      loc = " (far)"
    end
    if p.zone and p.zone ~= "" then
      loc = loc .. " [" .. tostring(p.zone) .. "]"
    end
    local combat = p.in_combat and " ⚔" or ""
    local idle = (p.afk or p.idle) and " (AFK)" or ""
    UI.toast(
      string.format("%s  Lv%d%s%s%s", tostring(p.name), tonumber(p.level) or 1, combat, idle, loc),
      "info"
    )
  end)

  Network.on("emote", function(data)
    local who = data.name or "?"
    local em = data.emote or "wave"
    local line = who .. " " .. em .. "s"
    if em == "wave" then
      line = who .. " waves"
    elseif em == "bow" then
      line = who .. " bows"
    elseif em == "cheer" then
      line = who .. " cheers"
    elseif em == "dance" then
      line = who .. " dances"
    elseif em == "cry" then
      line = who .. " cries"
    elseif em == "laugh" then
      line = who .. " laughs"
    elseif em == "point" then
      line = who .. " points"
    elseif em == "sit" then
      line = who .. " sits"
    elseif em == "think" then
      line = who .. " thinks"
    end
    self.chat_log[#self.chat_log + 1] = {
      name = who,
      text = line,
      player_id = data.player_id,
      kind = "emote",
      channel = "nearby",
    }
    while #self.chat_log > 40 do
      table.remove(self.chat_log, 1)
    end
    UI.toast(line, "join")
  end)

  Network.on("item_used", function(data)
    if data.current_hp and Session.character then
      Session.character.current_hp = data.current_hp
    end
    if data.teleported and data.x and data.y then
      if Session.character then
        Session.character.world_x = data.x
        Session.character.world_y = data.y
      end
      if World.local_player then
        World.local_player.x = math.floor(data.x)
        World.local_player.y = math.floor(data.y)
        World.server_x = World.local_player.x
        World.server_y = World.local_player.y
        World.pending = {}
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
    end
    if data.repel_steps then
      self.repel = tonumber(data.repel_steps) or 0
    end
    if data.radiant_steps then
      self.radiant = tonumber(data.radiant_steps) or 0
    end
    if data.message then
      UI.toast(data.message, "ok")
    end
  end)

  Network.on("spell_cast", function(data)
    if data.character then
      Session.character = data.character
    else
      if data.current_hp and Session.character then
        Session.character.current_hp = data.current_hp
      end
      if data.current_mp and Session.character then
        Session.character.current_mp = data.current_mp
      end
    end
    if data.teleported and data.x and data.y then
      if Session.character then
        Session.character.world_x = data.x
        Session.character.world_y = data.y
      end
      if World.local_player then
        World.local_player.x = math.floor(data.x)
        World.local_player.y = math.floor(data.y)
        World.server_x = World.local_player.x
        World.server_y = World.local_player.y
        World.pending = {}
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
    end
    if data.repel_steps then
      self.repel = tonumber(data.repel_steps) or 0
    end
    if data.radiant_steps then
      self.radiant = tonumber(data.radiant_steps) or 0
    end
    if data.message then
      UI.toast(data.message, "ok")
    end
  end)

  Network.on("inventory_update", function(data)
    if data.sold and data.sold.gold_gained then
      local g = tonumber(data.sold.gold_gained) or 0
      local n = data.sold.item_name or data.sold.item_id or "item"
      UI.toast(string.format("Sold %s +%d G", tostring(n), g), "ok")
    elseif data.equipped then
      UI.toast(tostring(data.message or ("Equipped " .. tostring(data.equipped.item_id or "?"))), "ok")
    elseif data.unequipped then
      UI.toast(tostring(data.message or ("Unequipped " .. tostring(data.unequipped.slot or "?"))), "ok")
    elseif data.message then
      UI.toast(tostring(data.message), "ok")
    end
    if data.character then
      Session.character = data.character
    end
    if data.items and Session.character then
      Session.character.inventory = data.items
    end
  end)

  Network.on("rest_ok", function(data)
    if data.character then
      Session.character = data.character
    end
    if data.current_hp and Session.character then
      Session.character.current_hp = data.current_hp
      Session.character.current_mp = data.current_mp or Session.character.current_mp
      if data.gold then
        Session.character.gold = data.gold
      end
    end
    if data.preview then
      -- Quote only — second R within a few seconds completes the rest
      local msg = data.message or "Inn quote"
      if data.full then
        self._inn_quote_ready = false
        UI.toast(msg, "info")
      elseif data.can_afford == false then
        self._inn_quote_ready = false
        local need = data.cost and (" (need " .. tostring(data.cost) .. " G)") or ""
        UI.toast(msg .. need, "danger")
      else
        self._inn_quote_ready = true
        self._inn_quote_t = love.timer.getTime()
        UI.toast(msg .. " — press R again to stay", "info")
      end
    elseif data.message then
      self._inn_quote_ready = false
      UI.toast(data.message, "ok")
    end
  end)

  Network.on("combat_start", function(data)
    self.locked = true
    World.pending = {}
    local en = data.enemy and data.enemy.name or "monster"
    UI.toast("Encounter: " .. en .. "!", "danger")
    State.switch("combat", data)
  end)

  Network.on("error", function(data)
    if data.reason == "blocked" or data.reason == "invalid step" then
      if data.x and data.y then
        World.apply_move_ok({ ok = false, x = data.x, y = data.y, seq = data.seq })
        if World.local_player then
          self.zone = zone_name(World.local_player.x, World.local_player.y)
        end
      end
      return
    end
    if data.reason == "in combat" or data.reason == "rate_limit" or data.reason == "chat_rate_limit" then
      return
    end
    if data.reason == "empty chat" then
      return
    end
    local r = tostring(data.reason or "error")
    if data.cost and r == "not enough gold" then
      r = string.format("not enough gold (need %s G)", tostring(data.cost))
    elseif r == "stack full" then
      r = "stack full — sell or discard (I then D)"
    elseif r == "inventory full" then
      r = "bag full — sell or discard (I then D)"
    end
    self.status = "Error: " .. r
    UI.toast(r, "danger")
  end)

  Network.on("pong", function() end)
end

function Overworld:enter()
  self.locked = false
  self.move_cooldown = 0.15
  bind_handlers(self)

  if Network.connected and Network.authenticated then
    if Session.character then
      if World.pending_count() == 0 and World.local_player == nil then
        World.set_local(Session.character)
      elseif World.local_player and Session.character then
        World.local_player.name = Session.character.name
        World.local_player.level = Session.character.level or World.local_player.level
        World.local_player.id = Session.character.id
        -- Apply teleports / inn exits done while in another state (e.g. inventory wings)
        local sx = math.floor(Session.character.world_x or Session.character.x or World.local_player.x)
        local sy = math.floor(Session.character.world_y or Session.character.y or World.local_player.y)
        if World.pending_count() == 0 and (World.local_player.x ~= sx or World.local_player.y ~= sy) then
          World.local_player.x = sx
          World.local_player.y = sy
          World.server_x = sx
          World.server_y = sy
        end
      elseif Session.character and not World.local_player then
        World.set_local(Session.character)
      end
      if World.local_player then
        self.zone = zone_name(World.local_player.x, World.local_player.y)
      end
    end
    self.status = "Connected"
    Network.sync()
    return
  end

  World.reset()
  if Session.character then
    World.set_local(Session.character)
    self.zone = zone_name(World.local_player.x, World.local_player.y)
  end
  self.status = "Connecting..."

  local ok, err = Network.connect(Session.server_ws)
  if ok then
    Network.auth(Session.character.id)
    self.status = "Authenticating..."
  else
    self.status = tostring(err) .. " (local preview)"
  end
end

function Overworld:leave() end

function Overworld:update(dt)
  Network.update(dt)
  World.tick_remote(dt)

  local rtt_ms = math.floor((Network.rtt or 0) * 1000)
  local others = 0
  for _ in pairs(World.players) do
    others = others + 1
  end
  local buffs = ""
  if (self.repel or 0) > 0 then
    buffs = buffs .. string.format(" · repel %d", self.repel)
  end
  if (self.radiant or 0) > 0 then
    buffs = buffs .. string.format(" · light %d", self.radiant)
  end
  if buffs ~= "" then
    self.net_info = string.format(
      "%s · %dms · %d near · %d on%s",
      Network.link_status(),
      rtt_ms,
      others,
      self.online or 0,
      buffs
    )
  else
    self.net_info = string.format(
      "%s · %dms · %d nearby · %d online",
      Network.link_status(),
      rtt_ms,
      others,
      self.online or 0
    )
  end

  if self.locked or self.chat_open then
    return
  end
  if not Network.connected or not Network.authenticated then
    return
  end

  self.move_cooldown = math.max(0, self.move_cooldown - dt)
  if self.move_cooldown > 0 or not World.local_player then
    return
  end
  if World.pending_count() >= MAX_PENDING then
    return
  end

  local dx, dy = 0, 0
  if love.keyboard.isDown("left") or love.keyboard.isDown("a") then
    dx = -1
  elseif love.keyboard.isDown("right") or love.keyboard.isDown("d") then
    dx = 1
  elseif love.keyboard.isDown("up") or love.keyboard.isDown("w") then
    dy = -1
  elseif love.keyboard.isDown("down") or love.keyboard.isDown("s") then
    dy = 1
  end

  if dx ~= 0 or dy ~= 0 then
    local nx = World.local_player.x + dx
    local ny = World.local_player.y + dy
    if World.is_walkable(nx, ny) then
      local seq = Network.move(nx, ny)
      World.predict_move(seq, nx, ny)
      self.zone = zone_name(nx, ny)
      self.move_cooldown = MOVE_COOLDOWN
    end
  end
end

function Overworld:draw()
  -- Soft backdrop behind the map
  love.graphics.clear(0.04, 0.05, 0.09)
  love.graphics.setColor(0.06, 0.07, 0.12)
  love.graphics.rectangle("fill", 0, 0, love.graphics.getDimensions())
  Renderer.draw_overworld()

  local w, h = love.graphics.getDimensions()
  local c = Session.character or {}
  local p = World.local_player

  -- Top-left HUD
  UI.panel(12, 12, 300, 128, {
    title = "DQ1 MMO",
    subtitle = self.net_info,
    title_h = 30,
    no_ornament = true,
  })

  if p then
    UI.set_font("body")
    UI.color("text")
    love.graphics.print(
      string.format("%s   Lv %d", p.name or "?", (c.level or p.level or 1)),
      26,
      52
    )
    local hp = tonumber(c.current_hp) or 0
    local mhp = math.max(1, tonumber(c.max_hp) or 1)
    local mp = tonumber(c.current_mp) or 0
    local mmp = math.max(0, tonumber(c.max_mp) or 0)
    UI.bar(26, 78, 180, 14, hp / mhp, "hp", string.format("HP  %d / %d", hp, mhp))
    if mmp > 0 then
      UI.bar(26, 100, 180, 12, mp / mmp, "mp", string.format("MP  %d / %d", mp, mmp))
    end
    UI.set_font("small")
    UI.color("gold")
    love.graphics.print(tostring(c.gold or "0") .. " G", 220, 80)
  end

  -- Zone badge
  local zc = zone_color(self.zone)
  UI.badge(12, 150, 150, 28, "ZONE  " .. string.upper(self.zone or "?"), zc)
  if p then
    UI.set_font("tiny")
    UI.color("muted")
    love.graphics.print(string.format("(%d, %d)", math.floor(p.x + 0.01), math.floor(p.y + 0.01)), 170, 158)
  end

  -- Minimap (taller panel for title)
  UI.minimap(w - 148, 12, 120, World)

  -- Player list: nearby (coords) + online roster (zone / idle, no radar)
  if self.show_list then
    UI.player_list(w - 260, 170, 248, 150, World.local_player, World.players, "Nearby")
    if type(self.roster) == "table" and #self.roster > 0 then
      UI.player_list(
        w - 260,
        330,
        248,
        160,
        nil,
        self.roster,
        "Online",
        { mode = "roster" }
      )
    end
  end

  -- Character status sheet (F)
  if self.show_stats and Session.character then
    local sx = self.status_x
    local sy = self.status_y
    if (sx == nil or sy == nil) and World.local_player then
      sx = World.local_player.x
      sy = World.local_player.y
    end
    UI.stats_sheet(
      math.floor(w / 2 - 160),
      80,
      320,
      math.min(460, h - 120),
      Session.character,
      { zone = self.zone, x = sx, y = sy, repel = self.repel, radiant = self.radiant }
    )
  end

  -- Chat panel
  if self.show_chat then
    UI.chat_log(
      12,
      h - 210,
      math.min(440, w - 290),
      150,
      self.chat_log,
      self.chat_draft,
      self.chat_open,
      self.chat_channel
    )
  end

  UI.hint_bar(
    12,
    h - 48,
    w - 24,
    36,
    "WASD · T/Y chat · E emote · F stats · L look · R inn · H/M magic · O who · /zone · /find · Esc"
  )

  if self.status and self.status ~= "Connected" then
    UI.set_font("small")
    UI.color("ok")
    love.graphics.print(self.status, 14, 188)
  end
  UI.reset_color()
end

function Overworld:keypressed(key)
  if self.chat_open then
    if key == "escape" then
      self.chat_open = false
      self.chat_draft = ""
      return
    elseif key == "return" or key == "kpenter" then
      local text = (self.chat_draft or ""):match("^%s*(.-)%s*$")
      if text and text ~= "" then
        -- /w Name message · /tell Name message · /z message (zone)
        local wname, wmsg = text:match("^[/%!]w%s+(%S+)%s+(.+)$")
        if not wname then
          wname, wmsg = text:match("^[/%!]tell%s+(%S+)%s+(.+)$")
        end
        local zmsg = text:match("^[/%!]z%s+(.+)$")
        if not zmsg then
          zmsg = text:match("^[/%!]zone%s+(.+)$")
        end
        if not zmsg then
          zmsg = text:match("^[/%!]yell%s+(.+)$")
        end
        if not zmsg then
          zmsg = text:match("^[/%!]shout%s+(.+)$")
        end
        local wants_status = text:match("^[/%!]status%s*$")
          or text:match("^[/%!]me%s*$")
          or text:match("^[/%!]whoami%s*$")
          or text:match("^[/%!]stats%s*$")
          or text:match("^[/%!]sheet%s*$")
        local wants_version = text:match("^[/%!]version%s*$")
          or text:match("^[/%!]ver%s*$")
          or text:match("^[/%!]about%s*$")
          or text:match("^[/%!]server%s*$")
          or text:match("^[/%!]info%s*$")
        local wants_time = text:match("^[/%!]time%s*$")
          or text:match("^[/%!]uptime%s*$")
          or text:match("^[/%!]clock%s*$")
        local wants_motd = text:match("^[/%!]motd%s*$")
          or text:match("^[/%!]rules%s*$")
        local wants_afk = text:match("^[/%!]afk%s*$")
          or text:match("^[/%!]away%s*$")
        local wants_back = text:match("^[/%!]back%s*$")
          or text:match("^[/%!]afk%s+back%s*$")
        local wants_quit = text:match("^[/%!]quit%s*$")
          or text:match("^[/%!]logout%s*$")
          or text:match("^[/%!]exit%s*$")
        local wants_gold = text:match("^[/%!]gold%s*$")
          or text:match("^[/%!]money%s*$")
          or text:match("^[/%!]wallet%s*$")
        local wants_hp = text:match("^[/%!]hp%s*$")
          or text:match("^[/%!]mp%s*$")
          or text:match("^[/%!]vitals%s*$")
          or text:match("^[/%!]life%s*$")
        local wants_xp = text:match("^[/%!]xp%s*$")
          or text:match("^[/%!]exp%s*$")
          or text:match("^[/%!]level%s*$")
          or text:match("^[/%!]experience%s*$")
        local wants_spells = text:match("^[/%!]spells%s*$")
          or text:match("^[/%!]magic%s*$")
        local wants_bag = text:match("^[/%!]bag%s*$")
          or text:match("^[/%!]inv%s*$")
          or text:match("^[/%!]items%s*$")
          or text:match("^[/%!]inventory%s*$")
        local wants_last = text:match("^[/%!]last%s*$")
          or text:match("^[/%!]lastwhisper%s*$")
          or text:match("^[/%!]last_whisper%s*$")
          or text:match("^[/%!]reply_to%s*$")
        local wants_buffs = text:match("^[/%!]buffs%s*$")
          or text:match("^[/%!]effects%s*$")
          or text:match("^[/%!]debuffs%s*$")
        local wants_played = text:match("^[/%!]played%s*$")
          or text:match("^[/%!]session%s*$")
          or text:match("^[/%!]online_time%s*$")
        local wants_keys = text:match("^[/%!]keys%s*$")
          or text:match("^[/%!]controls%s*$")
          or text:match("^[/%!]keybinds%s*$")
        local wants_blocklist = text:match("^[/%!]blocklist%s*$")
          or text:match("^[/%!]blocks%s*$")
        local inspect_name = text:match("^[/%!]inspect%s+(%S+)$")
          or text:match("^[/%!]look%s+(%S+)$")
          or text:match("^[/%!]examine%s+(%S+)$")
          or text:match("^[/%!]profile%s+(%S+)$")
          or text:match("^[/%!]whereis%s+(%S+)$")
          or text:match("^[/%!]where_is%s+(%S+)$")
        local unequip_slot = text:match("^[/%!]unequip%s+(%S+)$")
          or text:match("^[/%!]takeoff%s+(%S+)$")
          or text:match("^[/%!]remove%s+(%S+)$")
        local block_name = text:match("^[/%!]block%s+(%S+)$")
        local unblock_name = text:match("^[/%!]unblock%s+(%S+)$")
        local wants_who = text:match("^[/%!]who%s*$")
          or text:match("^[/%!]players%s*$")
          or text:match("^[/%!]online%s*$")
        local wants_near = text:match("^[/%!]near%s*$")
          or text:match("^[/%!]here%s*$")
          or text:match("^[/%!]nearby%s*$")
        local wants_zone = text:match("^[/%!]zone%s*$")
          or text:match("^[/%!]where%s*$")
          or text:match("^[/%!]area%s*$")
          or text:match("^[/%!]whereami%s*$")
          or text:match("^[/%!]coords%s*$")
          or text:match("^[/%!]pos%s*$")
          or text:match("^[/%!]position%s*$")
          or text:match("^[/%!]mapinfo%s*$")
        local wants_counts = text:match("^[/%!]counts%s*$")
          or text:match("^[/%!]census%s*$")
          or text:match("^[/%!]population%s*$")
        local wants_inn = text:match("^[/%!]inn%s*$") or text:match("^[/%!]rest%s*$")
        local wants_ignores = text:match("^[/%!]ignores%s*$") or text:match("^[/%!]ignorelist%s*$")
        local find_q = text:match("^[/%!]find%s+(.+)$") or text:match("^[/%!]search%s+(.+)$")
        -- supports: /find Name · /find Name zone:field · /find zone:town
        local wants_help = text:match("^[/%!]help%s*$") or text:match("^[/%!]commands%s*$") or text:match("^%?%s*$")
        local ign_name = text:match("^[/%!]ignore%s+(%S+)$") or text:match("^[/%!]mute%s+(%S+)$")
        local unign_name = text:match("^[/%!]unignore%s+(%S+)$") or text:match("^[/%!]unmute%s+(%S+)$")
        local reply_msg = text:match("^[/%!]r%s+(.+)$") or text:match("^[/%!]reply%s+(.+)$")
        -- /say msg · /s msg → nearby; /g msg · /global msg → global
        local say_msg = text:match("^[/%!]say%s+(.+)$") or text:match("^[/%!]s%s+(.+)$")
        local global_msg = text:match("^[/%!]g%s+(.+)$") or text:match("^[/%!]global%s+(.+)$")
        local emote_cmd = text:match("^[/%!]emote%s+(%S+)$") or text:match("^[/%!]e%s+(%S+)$")
        local wants_emote_list = text:match("^[/%!]emote%s*$")
          or text:match("^[/%!]emotes%s*$")
          or text:match("^[/%!]e%s*$")
        local wants_stuck = text:match("^[/%!]stuck%s*$")
          or text:match("^[/%!]unstuck%s*$")
          or text:match("^[/%!]home%s*$")
        local wants_roll = text:match("^[/%!]roll%s*$")
          or text:match("^[/%!]dice%s*$")
          or text:match("^[/%!]d100%s*$")
        local roll_sides = text:match("^[/%!]roll%s+(%d+)%s*$")
          or text:match("^[/%!]dice%s+(%d+)%s*$")
          or text:match("^[/%!]d(%d+)%s*$")
        if wname and wmsg then
          Network.whisper(wname, wmsg)
          self.last_whisper_from = wname
        elseif reply_msg and reply_msg ~= "" then
          -- Prefer server-side last-peer (reliable after reconnect); client name as fallback
          if Network.reply then
            Network.reply(reply_msg)
          elseif self.last_whisper_from then
            Network.whisper(self.last_whisper_from, reply_msg)
          else
            UI.toast("No one to reply to", "danger")
          end
        elseif say_msg and say_msg ~= "" then
          Network.say(say_msg)
        elseif global_msg and global_msg ~= "" then
          Network.chat(global_msg, "global")
        elseif emote_cmd and emote_cmd ~= "" then
          if emote_cmd:lower() == "list" or emote_cmd:lower() == "help" then
            Network.send({ type = "emotes" })
          else
            Network.emote(emote_cmd:lower())
            UI.toast("Emote: " .. emote_cmd:lower(), "info")
          end
        elseif wants_emote_list then
          Network.send({ type = "emotes" })
        elseif wants_stuck then
          Network.send({ type = "stuck" })
        elseif wants_roll or roll_sides then
          local payload = { type = "roll" }
          if roll_sides then
            payload.sides = tonumber(roll_sides)
          end
          Network.send(payload)
        elseif zmsg and zmsg ~= "" then
          Network.chat(zmsg, "zone")
        elseif wants_status then
          Network.request_status()
        elseif wants_version then
          Network.send({ type = "version" })
        elseif wants_time then
          Network.send({ type = "time" })
        elseif wants_motd then
          Network.send({ type = "motd" })
        elseif wants_gold then
          Network.send({ type = "gold" })
        elseif wants_hp then
          Network.send({ type = "hp" })
        elseif wants_xp then
          Network.send({ type = "xp" })
        elseif wants_spells then
          Network.send({ type = "spells" })
        elseif wants_bag then
          Network.send({ type = "inventory" })
        elseif wants_last then
          Network.send({ type = "lastwhisper" })
        elseif wants_buffs then
          Network.send({ type = "buffs" })
        elseif wants_played then
          Network.send({ type = "played" })
        elseif wants_keys then
          Network.send({ type = "keys" })
        elseif wants_blocklist then
          Network.send({ type = "blocklist" })
        elseif inspect_name and inspect_name ~= "" then
          Network.send({ type = "inspect", name = inspect_name })
        elseif unequip_slot and unequip_slot ~= "" then
          Network.send({ type = "unequip", slot = unequip_slot:lower() })
        elseif wants_back then
          Network.send({ type = "back" })
        elseif wants_afk then
          Network.send({ type = "afk" })
        elseif wants_quit then
          Network.send({ type = "quit" })
        elseif block_name and block_name ~= "" then
          Network.send({ type = "block", name = block_name })
        elseif unblock_name and unblock_name ~= "" then
          Network.send({ type = "unblock", name = unblock_name })
        elseif wants_who then
          Network.who()
        elseif wants_near then
          if Network.near then
            Network.near()
          else
            Network.send({ type = "near" })
          end
        elseif wants_zone then
          if Network.zone_info then
            Network.zone_info()
          else
            Network.send({ type = "zone" })
          end
        elseif wants_counts then
          Network.send({ type = "counts" })
        elseif wants_inn then
          if self.zone == "town" then
            Network.send({ type = "rest", preview = true })
          else
            UI.toast("The inn is in town", "danger")
          end
        elseif wants_ignores then
          Network.ignores()
        elseif find_q and find_q ~= "" then
          Network.find(find_q)
        elseif ign_name and ign_name ~= "" then
          Network.ignore(ign_name)
        elseif unign_name and unign_name ~= "" then
          Network.unignore(unign_name)
        elseif wants_help then
          Network.send({ type = "help" })
        elseif self.chat_channel == "nearby" then
          Network.say(text)
        else
          Network.chat(text, "global")
        end
      end
      self.chat_draft = ""
      self.chat_open = false
      return
    elseif key == "backspace" then
      local d = self.chat_draft or ""
      self.chat_draft = d:sub(1, math.max(0, #d - 1))
      return
    end
    return
  end

  if key == "escape" then
    Network.disconnect()
    love.event.quit()
  elseif key == "t" and not self.locked then
    self.chat_channel = "global"
    self.chat_open = true
    self.chat_draft = ""
    self.show_chat = true
  elseif key == "y" and not self.locked then
    self.chat_channel = "nearby"
    self.chat_open = true
    self.chat_draft = ""
    self.show_chat = true
    UI.toast("Nearby chat", "info")
  elseif key == "e" and not self.locked then
    self._emote_i = (self._emote_i % #EMOTES) + 1
    local em = EMOTES[self._emote_i]
    Network.emote(em)
    UI.toast("Emote: " .. em, "info")
  elseif key == "f" and not self.locked then
    if self.show_stats then
      self.show_stats = false
    else
      -- Refresh from server (hp/mp/gold/spells/zone/buffs)
      Network.request_status()
      UI.toast("Status (F to close)", "info")
    end
  elseif key == "r" and not self.locked then
    if self.zone == "town" then
      -- First R: quote cost; second R within 4s: actually rest
      local now = love.timer.getTime()
      if self._inn_quote_ready and self._inn_quote_t and (now - self._inn_quote_t) < 4.0 then
        self._inn_quote_ready = false
        Network.send({ type = "rest" })
      else
        Network.send({ type = "rest", preview = true })
      end
    else
      self._inn_quote_ready = false
      UI.toast("The inn is in town", "danger")
    end
  elseif key == "h" and not self.locked then
    -- Field HEAL / HEALMORE if known (prefer healmore)
    local lists = {
      Session.character and Session.character.field_spells,
      Session.character and Session.character.known_spells,
    }
    local spell = nil
    for _, list in ipairs(lists) do
      if type(list) == "table" then
        for _, s in ipairs(list) do
          if s == "heal" then
            spell = spell or "heal"
          elseif s == "healmore" then
            spell = "healmore"
          end
        end
      end
    end
    if spell then
      Network.send({ type = "use_spell", spell = spell })
    else
      UI.toast("You don't know Heal yet", "danger")
    end
  elseif key == "m" and not self.locked then
    -- Cycle common field spells: heal, return, repel
    local order = { "heal", "healmore", "return", "repel", "outside", "radiant" }
    local fs = Session.character and (Session.character.field_spells or Session.character.known_spells) or {}
    local have = {}
    if type(fs) == "table" then
      for _, s in ipairs(fs) do
        have[s] = true
      end
    end
    self._field_spell_i = (self._field_spell_i or 0) + 1
    local picks = {}
    for _, s in ipairs(order) do
      if have[s] then
        picks[#picks + 1] = s
      end
    end
    if #picks == 0 then
      UI.toast("No field spells yet", "danger")
    else
      if self._field_spell_i > #picks then
        self._field_spell_i = 1
      end
      local sid = picks[self._field_spell_i]
      Network.send({ type = "use_spell", spell = sid })
    end
  elseif key == "b" and not self.locked then
    Network.send({ type = "debug_encounter", enemy = "slime" })
  elseif key == "i" and not self.locked then
    State.switch("inventory")
  elseif key == "p" or key == "tab" then
    self.show_list = not self.show_list
    UI.toast(self.show_list and "Player list on" or "Player list off", "info")
    if self.show_list then
      Network.send({ type = "who" })
    end
  elseif key == "o" and not self.locked then
    Network.send({ type = "who" })
  elseif key == "l" and not self.locked then
    -- Examine first nearby peer, else first roster entry, else yourself
    local target = nil
    for _, p in pairs(World.players or {}) do
      if p and p.name then
        target = p.name
        break
      end
    end
    if not target and type(self.roster) == "table" then
      for _, p in ipairs(self.roster) do
        if p and p.name and (not World.local_player or p.name ~= World.local_player.name) then
          target = p.name
          break
        end
      end
    end
    if target then
      Network.look(target)
    else
      -- Bare look → self (server accepts empty name as self)
      Network.send({ type = "look" })
    end
  elseif key == "k" and not self.locked then
    local fs = Session.character and Session.character.field_spells or {}
    local bs = Session.character and Session.character.known_spells or {}
    local flist, blist = {}, {}
    if type(fs) == "table" then
      for _, s in ipairs(fs) do
        flist[#flist + 1] = s
      end
    end
    if type(bs) == "table" then
      for _, s in ipairs(bs) do
        blist[#blist + 1] = s
      end
    end
    local msg = "Field: "
    if #flist > 0 then
      msg = msg .. table.concat(flist, ", ")
    else
      msg = msg .. "(none)"
    end
    msg = msg .. "  ·  Battle: "
    if #blist > 0 then
      msg = msg .. table.concat(blist, ", ")
    else
      msg = msg .. "(none)"
    end
    UI.toast(msg, "info")
  elseif key == "c" and not self.locked then
    self.show_chat = not self.show_chat
  elseif key == "?" and not self.locked then
    Network.send({ type = "help" })
  elseif key == "/" and not self.locked then
    self.chat_channel = "global"
    self.chat_open = true
    self.chat_draft = "/"
    self.show_chat = true
  end
end

function Overworld:textinput(text)
  if self.chat_open then
    if #(self.chat_draft or "") < 200 then
      self.chat_draft = (self.chat_draft or "") .. text
    end
  end
end

return Overworld
