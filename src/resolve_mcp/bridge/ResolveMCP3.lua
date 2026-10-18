-- Trusted factory module. Install.ps1 embeds it with a fixed module registry.
local module = ...
local M = {}
function M.load_modules()
    return module('edits') -- definitions only; no approval/dispatcher or mutation
end
function M.operations(resolve_object,codec,key,adapter)
    local crypto = module('crypto')
    local operations,invoke = module('reads').new(resolve_object,codec)
    local writable = module('edits').new(resolve_object,codec,crypto,key,adapter,invoke)
    for name,operation in pairs(writable) do operations[name] = operation end
    local original_ping = operations.ping
    operations.ping = function()
        local result = original_ping()
        result.writes_enabled = nil -- tool exposure remains a per-client setting
        result.version,result.writes_require_local_approval,result.writes_default_disabled = '0.4.0',true,true
        return result
    end
    return operations,writable
end
function M.run()
    local function log(message) print('[ResolveMCP v0.4] ' .. message) end
    local release
    local stage = 'global libraries'
    local ok = pcall(function()
        local runtime = module('runtime')
        runtime.ffi(); runtime.bit()
        assert(bmd and type(bmd.wait) == 'function','Host wait unavailable')
        local native,crypto,codec = module('native'),module('crypto'),module('codec')
        local root = native.root()
        stage = 'mailbox mutex'
        release = native.acquire(crypto.sha256(root))
        if not release then log('Another bridge already owns this mailbox'); return end
        stage = 'session key'
        local raw_key = native.read(root .. '\\session.key')
        assert(raw_key and #raw_key == 64,'Initialize the Python mailbox first')
        local key = crypto.unhex(raw_key)
        local bridge_id = native.random_hex()
        stage = 'Resolve read handlers'
        local operations,writable = M.operations(runtime.resolve(),codec,key,{
            root=root,bridge_id=bridge_id,read=native.read,canonical_file=native.canonical_file,
            canonical_directory=native.canonical_directory,random_hex=native.random_hex,now=os.time,
        })
        local bridge = module('core').new(crypto,codec,operations,key,bridge_id,writable)
        log('Started; authenticated data channel, edits require local test-project approval')
        stage = 'mailbox polling'
        local last_request
        while not bridge.stopped do
            if native.read(root .. '\\session.key') ~= raw_key then log('Session changed; restart required'); break end
            local packet = native.read(root .. '\\request.txt')
            if packet and packet ~= last_request then
                local reply = bridge:process(packet,os.time())
                if reply then native.write(root .. '\\response.txt',reply) end
                last_request = packet
            end
            bmd.wait(0.02)
        end
    end)
    if release then release() end
    if not ok then log('Stopped at ' .. stage .. '; run the separate read-only probe for details') end
    return ok
end
return M
