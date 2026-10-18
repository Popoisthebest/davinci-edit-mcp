-- ResolveMCP v0.2: read-only bridge for Resolve 21.1 Free (Windows).
-- Start ONLY from Workspace > Scripts > Utility > ResolveMCP.
-- Four fixed operations. Requests are loaded as Lua expressions.
-- SECURITY: even an empty setfenv cannot guarantee total safety against
-- malicious Lua expressions; protect the mailbox and improve transport.

local prefix = '[ResolveMCP] '
local function log(msg) print(prefix .. tostring(msg)) end
if not os or type(os.getenv) ~= 'function' or type(loadfile) ~= 'function'
   or type(setfenv) ~= 'function' or not bmd or type(bmd.wait) ~= 'function' then
    log('Missing required Lua functions')
    return
end

local R = rawget(_G, 'resolve')
if not R and bmd and type(bmd.scriptapp) == 'function' then
    local ok, result = pcall(function() return bmd.scriptapp('Resolve') end)
    if ok then R = result end
end
local F = rawget(_G, 'fusion') or rawget(_G, 'fu')
if not F and R then
    local ok, result = pcall(function() return R:Fusion() end)
    if ok then F = result end
end
if not R or not F then log('Resolve/Fusion object unavailable'); return end

local base = os.getenv('LOCALAPPDATA')
if not base or base == '' then log('LOCALAPPDATA unavailable'); return end
local request_path = base .. '\ResolveMCP\command_v2.lua'
local response_key = 'Global.ResolveMCPBridgeV2.Response'
local last_id = nil

local function hex(str)
    local out = {}
    str = tostring(str or '')
    for i = 1, #str do out[#out+1] = string.format('%02x', string.byte(str, i)) end
    return table.concat(out)
end

local function load_request()
    if type(bmd.fileexists) == 'function' and not bmd.fileexists(request_path) then
        return nil
    end
    local chunk = loadfile(request_path)
    if not chunk then return nil end
    setfenv(chunk, {})
    local ok, r = pcall(chunk)
    if not ok or type(r) ~= 'table' or type(r.id) ~= 'string'
        or #r.id ~= 32 or not r.id:match('^[0-9a-f]+$') then return nil end
    if type(r.op) ~= 'string' then return nil end
    return r
end

local function reply(id, status, kind, ...)
    local parts = { id, status, kind }
    local n = select('#', ...)
    for i = 1, n do parts[#parts+1] = tostring(select(i, ...)) end
    local payload = table.concat(parts, '|')
    local ok, err = pcall(function()
        F:SetPrefs(response_key, payload)
        F:SavePrefs()
    end)
    if not ok then log('Could not write response: ' .. tostring(err)) end
end

log('v0.2 STARTED: read-only bridge')
while true do
    local req = load_request()
    if req and req.id ~= last_id then
        last_id = req.id
        if req.op == 'stop' then
            reply(req.id, 'OK', 'STOPPED')
            log('STOPPED')
            break
        elseif req.op == 'ping' then
            local ok, version = pcall(function() return R:GetVersionString() end)
            if ok then reply(req.id, 'OK', 'PING', hex(version))
            else reply(req.id, 'ERROR', 'VERSION') end
        elseif req.op == 'current_project' then
            local ok, name, count = pcall(function()
                local project = R:GetProjectManager():GetCurrentProject()
                if not project then return nil, nil end
                return project:GetName(), project:GetTimelineCount()
            end)
            if not ok then reply(req.id, 'ERROR', 'PROJECT')
            elseif not name then reply(req.id, 'OK', 'PROJECT', 'NONE')
            else reply(req.id, 'OK', 'PROJECT', hex(name), tonumber(count) or 0) end
        elseif req.op == 'current_timeline' then
            local ok, name, videos, audios, start_frame, end_frame = pcall(function()
                local project = R:GetProjectManager():GetCurrentProject()
                if not project then return nil end
                local tl = project:GetCurrentTimeline()
                if not tl then return nil end
                return tl:GetName(), tl:GetTrackCount('video'), tl:GetTrackCount('audio'),
                       tl:GetStartFrame(), tl:GetEndFrame()
            end)
            if not ok then reply(req.id, 'ERROR', 'TIMELINE')
            elseif not name then reply(req.id, 'OK', 'TIMELINE', 'NONE')
            else reply(req.id, 'OK', 'TIMELINE', hex(name),
                       tonumber(videos) or 0, tonumber(audios) or 0,
                       tonumber(start_frame) or 0, tonumber(end_frame) or 0) end
        else
            reply(req.id, 'ERROR', 'NOT_ALLOWED')
        end
    end
    bmd.wait(0.25)
end
