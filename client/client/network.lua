--- Reliable WebSocket client: heartbeats, reconnect backoff, RTT, send queue.

local Session = require("client.session")
local Http = require("client.http")

package.path = love.filesystem.getSource() .. "/libs/?.lua;" .. package.path

local Network = {
  ws = nil,
  connected = false,
  authenticated = false,
  handlers = {},
  rtt = 0,
  _status = "disconnected",
  _pending_auth = nil,
  _inbox = {},
  _outbox = {},
  _url = nil,
  _character_id = nil,
  _reconnect_t = 0,
  _reconnect_attempt = 0,
  _auto_reconnect = true,
  _ping_t = 0,
  _last_pong_t = 0,
  _move_seq = 0,
}

local PING_INTERVAL = 5.0
local PONG_TIMEOUT = 20.0
local MAX_OUTBOX = 32
local MAX_RECONNECT_DELAY = 15.0

local function parse_ws_url(url)
  local host, port, path = url:match("^ws://([^:/]+):?(%d*)(/.*)$")
  if not host then
    return nil
  end
  if port == "" then
    port = "80"
  end
  return host, tonumber(port), path or "/"
end

local function now()
  return love.timer.getTime()
end

function Network.on(msg_type, fn)
  Network.handlers[msg_type] = fn
end

function Network.clear_handlers()
  Network.handlers = {}
end

function Network._dispatch(data)
  if type(data) ~= "table" then
    return
  end
  if data.type == "auth_ok" then
    Network.authenticated = true
    Network._reconnect_attempt = 0
    Network._last_pong_t = now()
  elseif data.type == "pong" then
    Network._last_pong_t = now()
    if data.t then
      local rtt = now() - tonumber(data.t)
      if rtt >= 0 and rtt < 10 then
        Network.rtt = Network.rtt * 0.7 + rtt * 0.3
      end
    end
  end
  local fn = Network.handlers[data.type]
  if fn then
    fn(data)
  end
  if Network.handlers["*"] then
    Network.handlers["*"](data)
  end
end

function Network._flush_outbox()
  if not Network.connected or not Network.ws then
    return
  end
  while #Network._outbox > 0 do
    local payload = table.remove(Network._outbox, 1)
    local ok = pcall(function()
      Network.ws:send(payload)
    end)
    if not ok then
      table.insert(Network._outbox, 1, payload)
      break
    end
  end
end

function Network.connect(url)
  url = url or Session.server_ws
  Network._url = url
  Network._auto_reconnect = true

  if Network.ws then
    local keep = Network._auto_reconnect
    Network._auto_reconnect = false
    Network.disconnect()
    Network._auto_reconnect = keep
  end

  Network._status = "connecting"
  Network.authenticated = false
  Network.connected = false

  local ok, ws_mod = pcall(require, "websocket")
  if not ok then
    Network._status = "no_websocket_lib"
    return false, "websocket library missing"
  end

  local host, port, path = parse_ws_url(url)
  if not host then
    Network._status = "bad_url"
    return false, "invalid websocket url"
  end

  local client = ws_mod.new(host, port, path)

  function client:onopen()
    Network.connected = true
    Network._status = "connected"
    Network._last_pong_t = now()
    Network._ping_t = 0
    if Network._pending_auth then
      Network._raw_send(Http.encode_json(Network._pending_auth))
      Network._pending_auth = nil
    end
    Network._flush_outbox()
  end

  function client:onmessage(message)
    local data = Http.decode_json(message)
    if data then
      Network._inbox[#Network._inbox + 1] = data
    end
  end

  function client:onerror(err)
    Network._status = "error: " .. tostring(err)
    Network.connected = false
  end

  function client:onclose(_code, _reason)
    Network.connected = false
    Network.authenticated = false
    Network.ws = nil
    if Network._auto_reconnect then
      Network._reconnect_attempt = Network._reconnect_attempt + 1
      local delay = math.min(MAX_RECONNECT_DELAY, 1.0 * (2 ^ math.min(Network._reconnect_attempt - 1, 4)))
      -- jitter
      delay = delay * (0.75 + math.random() * 0.5)
      Network._reconnect_t = delay
      Network._status = string.format("reconnecting (%.1fs)", delay)
    else
      Network._status = "closed"
    end
    if Network.handlers._close then
      Network.handlers._close()
    end
  end

  Network.ws = client
  return true
end

function Network._raw_send(payload)
  if not Network.ws or not Network.connected then
    if #Network._outbox < MAX_OUTBOX then
      Network._outbox[#Network._outbox + 1] = payload
    end
    return false
  end
  local ok = pcall(function()
    Network.ws:send(payload)
  end)
  if not ok then
    if #Network._outbox < MAX_OUTBOX then
      Network._outbox[#Network._outbox + 1] = payload
    end
    return false
  end
  return true
end

function Network.send(message)
  if type(message) == "table" and message.type == "auth" then
    if not Network.connected then
      Network._pending_auth = message
      return true
    end
  end
  local payload = message
  if type(message) == "table" then
    payload = Http.encode_json(message)
  end
  if not Network.ws then
    if type(message) == "table" and message.type == "auth" then
      Network._pending_auth = message
      return true
    end
    return false
  end
  if not Network.connected then
    if type(message) == "table" and message.type == "auth" then
      Network._pending_auth = message
      return true
    end
    -- queue non-auth only after we have been authenticated before
    if Network._character_id and #Network._outbox < MAX_OUTBOX then
      Network._outbox[#Network._outbox + 1] = payload
      return true
    end
    return false
  end
  return Network._raw_send(payload)
end

function Network.auth(character_id)
  Network._character_id = character_id
  Network._move_seq = 0
  return Network.send({
    type = "auth",
    token = Session.token,
    character_id = character_id,
  })
end

function Network.next_move_seq()
  Network._move_seq = Network._move_seq + 1
  return Network._move_seq
end

function Network.move(x, y)
  local seq = Network.next_move_seq()
  Network.send({ type = "move", x = x, y = y, seq = seq })
  return seq
end

function Network.sync()
  return Network.send({ type = "sync" })
end

function Network.chat(text, channel)
  return Network.send({ type = "chat", text = text, channel = channel or "global" })
end

function Network.say(text)
  return Network.send({ type = "say", text = text, channel = "nearby" })
end

function Network.whisper(to_name, text)
  return Network.send({ type = "whisper", to = to_name, text = text })
end

--- Server-tracked reply to last whisper peer (survives reconnect soft grace).
function Network.reply(text)
  return Network.send({ type = "reply", text = text })
end

function Network.emote(emote, to_name)
  local payload = { type = "emote", emote = emote or "wave" }
  if to_name and tostring(to_name) ~= "" then
    payload.to = tostring(to_name)
  end
  return Network.send(payload)
end

--- Meetup invite (not a party): private notice with inviter zone.
function Network.invite(to_name)
  if to_name == nil or tostring(to_name) == "" then
    return Network.send({ type = "invite", to = "@last" })
  end
  return Network.send({ type = "invite", to = tostring(to_name) })
end

function Network.busy(reason)
  if reason and tostring(reason) ~= "" then
    return Network.send({ type = "busy", text = tostring(reason) })
  end
  return Network.send({ type = "busy" })
end

function Network.lastemote()
  return Network.send({ type = "lastemote" })
end

function Network.look(name_or_id)
  if name_or_id == nil or name_or_id == "" then
    -- bare look → server examines self
    return Network.send({ type = "look" })
  end
  if type(name_or_id) == "number" then
    return Network.send({ type = "look", player_id = name_or_id })
  end
  return Network.send({ type = "look", name = tostring(name_or_id) })
end

--- Request self status sheet from server (HP/MP/gear/zone/buffs).
--- NOTE: do not name this `status` — that is reserved for link_status().
function Network.request_status()
  return Network.send({ type = "status" })
end

function Network.find(query, zone)
  local payload = { type = "find", q = tostring(query or "") }
  if zone and zone ~= "" then
    payload.zone = tostring(zone)
  end
  return Network.send(payload)
end

function Network.who()
  return Network.send({ type = "who" })
end

function Network.near()
  return Network.send({ type = "near" })
end

function Network.zone_info()
  return Network.send({ type = "zone" })
end

function Network.ignore(name)
  return Network.send({ type = "ignore", name = tostring(name or "") })
end

function Network.unignore(name)
  return Network.send({ type = "unignore", name = tostring(name or "") })
end

function Network.ignores()
  return Network.send({ type = "ignores" })
end

function Network.ping(with_presence)
  local payload = { type = "ping", t = now() }
  if with_presence then
    payload.sync = true
  end
  return Network.send(payload)
end

function Network.update(dt)
  dt = dt or 0

  -- reconnect
  if Network._reconnect_t and Network._reconnect_t > 0 and not Network.ws then
    Network._reconnect_t = Network._reconnect_t - dt
    if Network._reconnect_t <= 0 then
      local ok = Network.connect(Network._url or Session.server_ws)
      if ok and Network._character_id and Session.token then
        Network.auth(Network._character_id)
      end
    end
  end

  if Network.ws and Network.ws.update then
    Network.ws:update()
  end

  -- heartbeat
  if Network.connected and Network.authenticated then
    Network._ping_t = (Network._ping_t or 0) + dt
    if Network._ping_t >= PING_INTERVAL then
      Network._ping_t = 0
      Network.ping(false)
    end
    if Network._last_pong_t > 0 and (now() - Network._last_pong_t) > PONG_TIMEOUT then
      Network._status = "stale — reconnecting"
      if Network.ws and Network.ws.close then
        pcall(function()
          Network.ws:close()
        end)
      end
      Network.ws = nil
      Network.connected = false
      Network.authenticated = false
      Network._reconnect_t = 0.5
    end
  end

  if #Network._inbox > 0 then
    local batch = Network._inbox
    Network._inbox = {}
    for i = 1, #batch do
      Network._dispatch(batch[i])
    end
  end
end

function Network.disconnect()
  Network._auto_reconnect = false
  Network._reconnect_t = 0
  Network._reconnect_attempt = 0
  Network._outbox = {}
  if Network.ws and Network.ws.close then
    pcall(function()
      Network.ws:close()
    end)
  end
  Network.ws = nil
  Network.connected = false
  Network.authenticated = false
  Network._pending_auth = nil
  Network._inbox = {}
  Network._status = "disconnected"
end

--- Connection / link state string for HUD (not the character status sheet).
function Network.link_status()
  return Network._status
end

-- Back-compat alias used by older call sites for link state only.
function Network.status()
  return Network.link_status()
end

return Network
