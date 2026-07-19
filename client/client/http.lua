--- HTTP helper: prefers luasocket, falls back to curl.
--- Includes a small recursive JSON decoder (no external deps).

local Http = {}

function Http.encode_json(val)
  local t = type(val)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return val and "true" or "false"
  elseif t == "number" then
    if val ~= val or val == math.huge or val == -math.huge then
      return "null"
    end
    return string.format("%.14g", val)
  elseif t == "string" then
    return '"'
      .. val
        :gsub("\\", "\\\\")
        :gsub('"', '\\"')
        :gsub("\n", "\\n")
        :gsub("\r", "\\r")
        :gsub("\t", "\\t")
      .. '"'
  elseif t == "table" then
    local n = #val
    local is_array = n > 0
    if is_array then
      local parts = {}
      for i = 1, n do
        parts[i] = Http.encode_json(val[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, v in pairs(val) do
      if type(k) == "string" or type(k) == "number" then
        parts[#parts + 1] = Http.encode_json(tostring(k)) .. ":" .. Http.encode_json(v)
      end
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ",") .. "}"
  end
  error("cannot encode type " .. t)
end

-- --- JSON decode -----------------------------------------------------------

local function skip_ws(s, i)
  local _, j = s:find("^[ \t\r\n]*", i)
  return (j or i - 1) + 1
end

local function parse_string(s, i)
  i = i + 1
  local out = {}
  while i <= #s do
    local c = s:sub(i, i)
    if c == '"' then
      return table.concat(out), i + 1
    end
    if c == "\\" then
      local n = s:sub(i + 1, i + 1)
      local map = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
      if n == "u" then
        local hex = s:sub(i + 2, i + 5)
        local code = tonumber(hex, 16) or 63
        if code < 128 then
          out[#out + 1] = string.char(code)
        else
          out[#out + 1] = "?"
        end
        i = i + 6
      else
        out[#out + 1] = map[n] or n
        i = i + 2
      end
    else
      out[#out + 1] = c
      i = i + 1
    end
  end
  return nil, i, "unterminated string"
end

local parse_value

local function parse_array(s, i)
  i = i + 1
  local arr = {}
  i = skip_ws(s, i)
  if s:sub(i, i) == "]" then
    return arr, i + 1
  end
  while true do
    local v
    v, i = parse_value(s, i)
    if v == nil and i == nil then
      return nil, nil, "bad array"
    end
    arr[#arr + 1] = v
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == "]" then
      return arr, i + 1
    end
    if c ~= "," then
      return nil, nil, "expected comma in array"
    end
    i = skip_ws(s, i + 1)
  end
end

local function parse_object(s, i)
  i = i + 1
  local obj = {}
  i = skip_ws(s, i)
  if s:sub(i, i) == "}" then
    return obj, i + 1
  end
  while true do
    if s:sub(i, i) ~= '"' then
      return nil, nil, "expected string key"
    end
    local key
    key, i = parse_string(s, i)
    i = skip_ws(s, i)
    if s:sub(i, i) ~= ":" then
      return nil, nil, "expected colon"
    end
    i = skip_ws(s, i + 1)
    local val
    val, i = parse_value(s, i)
    obj[key] = val
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == "}" then
      return obj, i + 1
    end
    if c ~= "," then
      return nil, nil, "expected comma in object"
    end
    i = skip_ws(s, i + 1)
  end
end

parse_value = function(s, i)
  i = skip_ws(s, i)
  local c = s:sub(i, i)
  if c == '"' then
    return parse_string(s, i)
  end
  if c == "{" then
    return parse_object(s, i)
  end
  if c == "[" then
    return parse_array(s, i)
  end
  if s:sub(i, i + 3) == "true" then
    return true, i + 4
  end
  if s:sub(i, i + 4) == "false" then
    return false, i + 5
  end
  if s:sub(i, i + 3) == "null" then
    return nil, i + 4
  end
  local num, j = s:match("^(-?%d+%.?%d*[eE]?[+-]?%d*)()", i)
  if num then
    return tonumber(num), j
  end
  return nil, nil, "unexpected token at " .. tostring(i)
end

function Http.decode_json(str)
  if type(str) ~= "string" or str == "" then
    return nil, "empty"
  end
  local ok_ext, json = pcall(require, "dkjson")
  if ok_ext and json.decode then
    local val, pos, err = json.decode(str)
    if err then
      return nil, err
    end
    return val
  end
  local val, i, err = parse_value(str, 1)
  if err then
    return nil, err
  end
  return val
end

function Http.format_error(detail)
  if detail == nil then
    return "request failed"
  end
  if type(detail) == "string" then
    return detail
  end
  if type(detail) == "table" then
    if detail.msg then
      return tostring(detail.msg)
    end
    if detail[1] then
      local parts = {}
      for _, e in ipairs(detail) do
        if type(e) == "table" then
          parts[#parts + 1] = tostring(e.msg or e.detail or e.type or "error")
        else
          parts[#parts + 1] = tostring(e)
        end
      end
      return table.concat(parts, "; ")
    end
  end
  return tostring(detail)
end

-- --- HTTP -----------------------------------------------------------------

local function request_socket(method, url, body, headers)
  local ok_http, http = pcall(require, "socket.http")
  local ok_ltn12, ltn12 = pcall(require, "ltn12")
  if not ok_http or not ok_ltn12 then
    return nil, "no_socket"
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
  local _, code, res_headers = http.request(req)
  if not code then
    return nil, "request failed"
  end
  return {
    status = code,
    body = table.concat(chunks),
    headers = res_headers,
  }
end

local function shell_quote(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function request_curl(method, url, body, headers)
  headers = headers or {}
  local cmd = { "curl", "-sS", "-X", method, url, "-w", "\n%{http_code}" }
  for k, v in pairs(headers) do
    cmd[#cmd + 1] = "-H"
    cmd[#cmd + 1] = k .. ": " .. v
  end
  if body then
    cmd[#cmd + 1] = "-H"
    cmd[#cmd + 1] = "Content-Type: application/json"
    cmd[#cmd + 1] = "--data-binary"
    cmd[#cmd + 1] = body
  end
  local parts = {}
  for i = 1, #cmd do
    parts[i] = shell_quote(cmd[i])
  end
  local handle = io.popen(table.concat(parts, " ") .. " 2>/dev/null")
  if not handle then
    return nil, "curl failed"
  end
  local out = handle:read("*a") or ""
  handle:close()
  local body_out, code = out:match("^(.*)\n(%d+)%s*$")
  if not code then
    return nil, "bad curl response"
  end
  return {
    status = tonumber(code),
    body = body_out or "",
    headers = {},
  }
end

function Http.request(method, url, body, headers)
  local res, err = request_socket(method, url, body, headers)
  if res then
    return res
  end
  if err == "no_socket" then
    return request_curl(method, url, body, headers)
  end
  local res2, err2 = request_curl(method, url, body, headers)
  if res2 then
    return res2
  end
  return nil, err or err2 or "http failed"
end

function Http.get(url, headers)
  return Http.request("GET", url, nil, headers)
end

function Http.post_json(url, data, headers)
  headers = headers or {}
  headers["Content-Type"] = "application/json"
  return Http.request("POST", url, Http.encode_json(data), headers)
end

return Http
