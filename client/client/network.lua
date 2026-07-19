--- WebSocket client using vendored love2d-lua-websocket (flaribbit).

local Session = require("client.session")
local Http = require("client.http")

package.path = love.filesystem.getSource() .. "/libs/?.lua;" .. package.path

local Network = {
  ws = nil,
  connected = false,
  authenticated = false,
  handlers = {},
  _status = "disconnected",
  _pending_auth = nil,
  _inbox = {},
  _url = nil,
  _character_id = nil,
  _reconnect_t = 0,
  _auto_reconnect = true,
}

local function parse_ws_url(url)
  -- ws://host:port/path
  local host, port, path = url:match("^ws://([^:/]+):?(%d*)(/.*)$")
  if not host then
    return nil
  end
  if port == "" then
    port = "80"
  end
  return host, tonumber(port), path or "/"
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
  end
  local fn = Network.handlers[data.type]
  if fn then
    fn(data)
  end
  if Network.handlers["*"] then
    Network.handlers["*"](data)
  end
end

function Network.connect(url)
  url = url or Session.server_ws
  Network._url = url
  Network._auto_reconnect = true
  if Network.ws then
    Network._auto_reconnect = false
    Network.disconnect()
    Network._auto_reconnect = true
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
    if Network._pending_auth then
      Network.send(Network._pending_auth)
      Network._pending_auth = nil
    end
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

  function client:onclose(code, reason)
    Network.connected = false
    Network.authenticated = false
    Network._status = "closed"
    Network.ws = nil
    if Network._auto_reconnect then
      Network._reconnect_t = 1.5
      Network._status = "reconnecting"
    end
    if Network.handlers._close then
      Network.handlers._close(code, reason)
    end
  end

  Network.ws = client
  return true
end

function Network.send(message)
  local payload = message
  if type(message) == "table" then
    payload = Http.encode_json(message)
  end
  if not Network.ws then
    return false
  end
  if not Network.connected then
    -- queue auth until open
    if type(message) == "table" and message.type == "auth" then
      Network._pending_auth = message
      return true
    end
    return false
  end
  Network.ws:send(payload)
  return true
end

function Network.auth(character_id)
  Network._character_id = character_id
  return Network.send({
    type = "auth",
    token = Session.token,
    character_id = character_id,
  })
end

function Network.update(dt)
  if Network._reconnect_t and Network._reconnect_t > 0 and not Network.ws then
    Network._reconnect_t = Network._reconnect_t - (dt or 0)
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

function Network.status()
  return Network._status
end

return Network
