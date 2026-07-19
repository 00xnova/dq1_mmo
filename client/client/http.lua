--- Minimal HTTP helper using love.thread + luasocket when available,
--- with a fallback blocking socket path for Love2D.

local Http = {}

local function parse_url(url)
  local scheme, host, port, path = url:match("^(https?)://([^:/]+):?(%d*)(/.*)$")
  if not scheme then
    return nil, "bad url"
  end
  if port == "" then
    port = scheme == "https" and "443" or "80"
  end
  return {
    scheme = scheme,
    host = host,
    port = tonumber(port),
    path = path or "/",
  }
end

function Http.request(method, url, body, headers)
  local ok_http, http = pcall(require, "socket.http")
  local ok_ltn12, ltn12 = pcall(require, "ltn12")
  if not ok_http or not ok_ltn12 then
    return nil, "luasocket not available (install love with luasocket or use curl fallback)"
  end

  headers = headers or {}
  local chunks = {}
  local req = {
    url = url,
    method = method,
    headers = headers,
    sink = ltn12.sink.table(chunks),
  }
  if body then
    req.source = ltn12.source.string(body)
    headers["Content-Length"] = tostring(#body)
    headers["Content-Type"] = headers["Content-Type"] or "application/json"
  end

  local result, code, res_headers = http.request(req)
  if not result then
    return nil, tostring(code)
  end
  local text = table.concat(chunks)
  return {
    status = code,
    body = text,
    headers = res_headers,
  }
end

function Http.get(url, headers)
  return Http.request("GET", url, nil, headers)
end

function Http.post_json(url, data, headers)
  headers = headers or {}
  headers["Content-Type"] = "application/json"
  local payload = Http.encode_json(data)
  return Http.request("POST", url, payload, headers)
end

-- Tiny JSON encoder/decoder for simple tables (no nested arrays of mixed types needed heavily)
function Http.encode_json(val)
  local t = type(val)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return val and "true" or "false"
  elseif t == "number" then
    return tostring(val)
  elseif t == "string" then
    return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r') .. '"'
  elseif t == "table" then
    local is_array = #val > 0
    if is_array then
      local parts = {}
      for i = 1, #val do
        parts[i] = Http.encode_json(val[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local parts = {}
      for k, v in pairs(val) do
        parts[#parts + 1] = Http.encode_json(tostring(k)) .. ":" .. Http.encode_json(v)
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
  error("cannot encode type " .. t)
end

function Http.decode_json(str)
  local ok, json = pcall(require, "json")
  if ok and json.decode then
    return json.decode(str)
  end
  -- Fallback: use load-based decoder for simple responses
  local ok2, dkjson = pcall(require, "dkjson")
  if ok2 then
    return dkjson.decode(str)
  end
  -- Last resort minimal decoder via love.filesystem isn't available; use pattern-ish
  local fn, err = load("return " .. Http._json_to_lua(str))
  if not fn then
    return nil, err
  end
  return fn()
end

function Http._json_to_lua(s)
  -- Convert JSON to Lua table syntax (simple subset)
  s = s:gsub("null", "nil")
  s = s:gsub(":%s*true", ": true")
  s = s:gsub(":%s*false", ": false")
  -- quote keys already quoted; convert "key": to ["key"]=
  s = s:gsub('"([^"]+)"%s*:', '["%1"] =')
  s = s:gsub("%[", "{")
  s = s:gsub("%]", "}")
  return s
end

return Http
