local Http = require("client.http")
local Session = require("client.session")

local Auth = {}

local function auth_header()
  return { Authorization = "Bearer " .. (Session.token or "") }
end

function Auth.register(email, password, username)
  local res, err = Http.post_json(Session.server_http .. "/auth/register", {
    email = email,
    password = password,
    username = username,
  })
  if not res then
    return nil, err
  end
  local data = Http.decode_json(res.body)
  if res.status ~= 201 then
    return nil, (data and data.detail) or ("register failed: " .. tostring(res.status))
  end
  Session.token = data.access_token
  Session.user_id = data.user_id
  Session.username = data.username
  return data
end

function Auth.login(email, password)
  local res, err = Http.post_json(Session.server_http .. "/auth/login", {
    email = email,
    password = password,
  })
  if not res then
    return nil, err
  end
  local data = Http.decode_json(res.body)
  if res.status ~= 200 then
    return nil, (data and data.detail) or ("login failed: " .. tostring(res.status))
  end
  Session.token = data.access_token
  Session.user_id = data.user_id
  Session.username = data.username
  return data
end

function Auth.list_characters()
  local res, err = Http.get(Session.server_http .. "/auth/characters", auth_header())
  if not res then
    return nil, err
  end
  local data = Http.decode_json(res.body)
  if res.status ~= 200 then
    return nil, (data and data.detail) or "list characters failed"
  end
  return data
end

function Auth.create_character(name)
  local res, err = Http.post_json(
    Session.server_http .. "/auth/characters",
    { name = name },
    auth_header()
  )
  if not res then
    return nil, err
  end
  local data = Http.decode_json(res.body)
  if res.status ~= 201 then
    return nil, (data and data.detail) or "create character failed"
  end
  return data
end

return Auth
