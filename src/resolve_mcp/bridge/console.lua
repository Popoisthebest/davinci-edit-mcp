-- Console/Utility service: one authenticated request per step; an explicitly
-- started bounded loop is optional. Reads are default; edits require v0.4 and
-- the existing per-operation signed approval and fresh-project guards.
local module = ...
local M = {}
function M.new(root,enable_edits)
    local runtime=module('runtime')
    runtime.ffi();runtime.bit()
    assert(os and type(os.time) == 'function','Console requires os.time')
    local native,crypto,codec=module('native'),module('crypto'),module('codec')
    local raw_key=native.read(root .. '\\session.key')
    assert(raw_key and #raw_key == 64,'Prepare the dedicated Console mailbox first')
    local key=crypto.unhex(raw_key)
    local operations,writable
    if enable_edits == true then
        operations,writable=module('bridge').operations(runtime.resolve(),codec,key,{
            root=root,read=native.read,canonical_file=native.canonical_file,
            canonical_directory=native.canonical_directory,random_hex=native.random_hex,now=os.time})
    else operations=module('reads').new(runtime.resolve(),codec) end
    local core=module('core').new(crypto,codec,operations,key,native.random_hex(),writable)
    local closed=false
    local owns_loop=false
    local last_served
    local session={mode=enable_edits == true and 'test-editing' or 'manual-read-only'}
    function session.step(skip_unchanged)
        if closed then return false,'CLOSED' end
        -- Acquire/release within one invocation; do not assume Console calls
        -- always run on the same OS thread. Shares the Utility bridge mutex.
        local release=owns_loop and function() end or native.acquire(crypto.sha256(root))
        if not release then return false,'BUSY' end
        local stage='session validation'
        local ok,accepted,state=pcall(function()
            if native.read(root .. '\\session.key') ~= raw_key then
                closed=true;return false,'SESSION_CHANGED'
            end
            stage='request read'
            local packet=native.read(root .. '\\request.txt')
            if not packet then return false,'IDLE' end
            if skip_unchanged and packet == last_served then return false,'IDLE' end
            stage='authenticated read dispatch'
            local reply=core:process(packet,os.time())
            if not reply then return false,'REJECTED' end
            stage='response write'
            native.write(root .. '\\response.txt',reply)
            last_served=packet
            if core.stopped then closed=true end
            return true,'REPLIED'
        end)
        release()
        if not ok then error('Console step failed at ' .. stage .. '; no automatic retry',0) end
        return accepted,state
    end
    -- Explicit bounded host service. Nothing runs automatically on new().
    -- Utility and Console share this dispatcher and the same mailbox mutex.
    function session.run(seconds,context)
        seconds=seconds or 180;context=context or 'Console'
        assert(type(seconds)=='number' and seconds%1==0 and seconds>=1 and seconds<=600,'Service limit is 1-600 seconds')
        assert(context=='Console' or context=='Utility','Invalid service context')
        assert(not closed and not owns_loop,'Service is closed or already running')
        assert(bmd and type(bmd.wait)=='function','Host bmd.wait unavailable; manual step remains usable')
        local release=native.acquire(crypto.sha256(root))
        assert(release,'Another service owns this mailbox')
        owns_loop=true
        local function status(state)
            native.write(root .. '\\service.json',codec.encode({state=state,context=context,
                mode=session.mode,limit_seconds=seconds,context_origin='launcher label',time=os.time()}))
        end
        local ok,err=pcall(function()
            local deadline=native.monotonic_seconds()+seconds
            status('RUNNING')
            while not closed and native.monotonic_seconds()<deadline do
                local _,state=session.step(true)
                if state=='SESSION_CHANGED' then error('Session changed; service closed') end
                if not closed then bmd.wait(0.02) end
            end
            status(closed and 'STOPPED' or 'LIMIT_REACHED')
        end)
        closed=true;owns_loop=false
        if not ok then pcall(status,'FAILED') end
        release()
        if not ok then error('Automatic service stopped: ' .. tostring(err),0) end
        return true
    end
    function session.close() closed=true;return true end
    return session
end
return M
