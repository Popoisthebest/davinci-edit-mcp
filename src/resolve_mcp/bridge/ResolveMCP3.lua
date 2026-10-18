-- Install this file beside the trusted modules with scripts/Install.ps1.
-- Run from Workspace > Scripts > Utility > ResolveMCP3. No fusion:Execute loop.
local function log(message) print('[ResolveMCP v0.3] ' .. message) end
local ok = pcall(function()
    assert(debug and debug.getinfo and bmd and type(bmd.wait) == 'function', 'Required host functions unavailable')
    local source = debug.getinfo(1,'S').source
    assert(source:sub(1,1) == '@', 'Start the installed script from the Utility menu')
    local directory = source:sub(2):match('^(.*[/\\])')
    assert(directory, 'Script directory unavailable')
    local native = dofile(directory .. 'native.lua')
    local crypto = dofile(directory .. 'crypto.lua')
    local codec = dofile(directory .. 'codec.lua')
    local reads = dofile(directory .. 'reads.lua')
    local core = dofile(directory .. 'core.lua')
    local root = native.root()
    local release = native.acquire(crypto.sha256(root))
    if not release then log('Another bridge already owns this mailbox'); return end
    local ran = pcall(function()
        local raw_key = native.read(root .. '\\session.key')
        assert(raw_key and #raw_key == 64, 'Initialize the Python mailbox first')
        local key = crypto.unhex(raw_key)
        local resolve_object = rawget(_G,'resolve')
        if not resolve_object and type(bmd.scriptapp) == 'function' then resolve_object = bmd.scriptapp('Resolve') end
        assert(resolve_object, 'Resolve object unavailable')
        local operations = reads.new(resolve_object,codec)
        local bridge = core.new(crypto,codec,operations,key,native.random_hex())
        log('Started; read-only, authenticated data channel')
        local last_request, last_reply
        while not bridge.stopped do
            if native.read(root .. '\\session.key') ~= raw_key then log('Session changed; restart required'); break end
            local packet = native.read(root .. '\\request.txt')
            if packet and packet ~= last_request then
                local reply = bridge:process(packet,os.time())
                if reply then native.write(root .. '\\response.txt',reply) end
                last_request, last_reply = packet, reply
            end
            bmd.wait(0.02)
        end
    end)
    release()
    if not ran then log('Stopped after an error. Check LuaJIT/FFI, mailbox ACL and API capabilities; no automatic retry') end
end)
if not ok then log('Cannot start. Windows LuaJIT/FFI and trusted installed modules are required; no loadfile fallback') end
