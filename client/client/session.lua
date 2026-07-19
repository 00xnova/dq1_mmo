--- Shared session data between states.
local Session = {
  token = nil,
  user_id = nil,
  username = nil,
  character = nil,
  server_http = "http://127.0.0.1:8000",
  server_ws = "ws://127.0.0.1:8000/ws",
}

function Session.clear()
  Session.token = nil
  Session.user_id = nil
  Session.username = nil
  Session.character = nil
end

return Session
