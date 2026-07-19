--- WebSocket client wrapper.
--- Prefers `websocket` library (love2d-lua-websocket). Falls back to polling stub.

local Session = require("client.session")
local Http = require("client.http")

local Network = {
  ws = nil,
  connected = false,
  authenticated = false,
  handlers = {},
  queue = {},
  _status = "disconnected",
  _use_stub = false,
}

local function try_require_ws()
  local ok, mod = pcall(require, "websocket")
  if ok then
    return mod
  end
  ok, mod = pcall(require, "libs.websocket")
  if ok then
    return mod
  end
  return nil
end

function Network.on(msg_type, fn)
  Network.handlers[msg_type] = fn
end

function Network.clear_handlers()
  Network.handlers = {}
end

function Network._dispatch(data)
  local t = data.type
  local fn = Network.handlers[t]
  if fn then
    fn(data)
  end
  if Network.handlers["*"] then
    Network.handlers["*"](data)
  end
end

function Network.connect(url)
  url = url or Session.server_ws
  Network._status = "connecting"
  local ws_lib = try_require_ws()
  if not ws_lib then
    -- Fallback: mark connected for HTTP-only auth testing; game WS needs library
    Network._use_stub = true
    Network.connected = false
    Network._status = "no_websocket_lib"
    return false, "websocket library not found — place love2d-lua-websocket in client/libs"
  end

  local socket = ws_lib.new and ws_lib.new(url) or ws_lib.client and ws_lib.client()
  if ws_lib.client then
    socket = ws_lib.client()
    socket:connect(url)
  end
  Network.ws = socket
  Network.connected = true
  Network._status = "connected"
  return true
end

function Network.send(message)
  if type(message) == "table" then
    message = Http.encode_json(message)
  end
  if Network._use_stub or not Network.ws then
    Network.queue[#Network.queue + 1] = message
    return false
  end
  if Network.ws.send then
    Network.ws:send(message)
    return true
  end
  return false
end

function Network.auth(character_id)
  return Network.send({
    type = "auth",
    token = Session.token,
    character_id = character_id,
  })
end

function Network.update(dt)
  if not Network.ws then
    return
  end
  -- library-specific pump
  if Network.ws.update then
    Network.ws:update()
  end
  if Network.ws.get_message then
    while true do
      local msg = Network.ws:get_message()
      if not msg then
        break
      end
      local data = Http.decode_json(msg)
      if data then
        if data.type == "auth_ok" then
          Network.authenticated = true
        end
        Network._dispatch(data)
      end
    end
  end
end

function Network.disconnect()
  if Network.ws and Network.ws.close then
    Network.ws:close()
  end
  Network.ws = nil
  Network.connected = false
  Network.authenticated = false
  Network._status = "disconnected"
end

function Network.status()
  return Network._status
end

return Network
