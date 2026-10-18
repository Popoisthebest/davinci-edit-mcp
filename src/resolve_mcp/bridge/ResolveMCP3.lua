-- Trusted factory module. Install.ps1 embeds it with a fixed module registry.
local module = ...
local M = {}
function M.operations(resolve_object,codec)
    return module('reads').new(resolve_object,codec)
end
function M.run()
    local function log(message) print('[ResolveMCP v0.3] ' .. message) end
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
        stage = 'Resolve read handlers'
        local operations = M.operations(runtime.resolve(),codec)
        local bridge = module('core').new(crypto,codec,operations,key,native.random_hex())
        log('Started; read-only authenticated data channel')
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
