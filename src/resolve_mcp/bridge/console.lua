-- Manual Console service: at most one authenticated request per step, no wait
-- loop, timer, Utility dispatcher or write handlers. State stays in this closure.
local module = ...
local M = {}
function M.new(root)
    local runtime=module('runtime')
    runtime.ffi();runtime.bit()
    assert(os and type(os.time) == 'function','Console requires os.time')
    local native,crypto,codec=module('native'),module('crypto'),module('codec')
    local raw_key=native.read(root .. '\\session.key')
    assert(raw_key and #raw_key == 64,'Prepare the dedicated Console mailbox first')
    local operations=module('reads').new(runtime.resolve(),codec)
    local core=module('core').new(crypto,codec,operations,crypto.unhex(raw_key),native.random_hex())
    local closed=false
    local session={mode='manual-read-only'}
    function session.step()
        if closed then return false,'CLOSED' end
        -- Acquire/release within one invocation; do not assume Console calls
        -- always run on the same OS thread. Shares the Utility bridge mutex.
        local release=native.acquire(crypto.sha256(root))
        if not release then return false,'BUSY' end
        local stage='session validation'
        local ok,accepted,state=pcall(function()
            if native.read(root .. '\\session.key') ~= raw_key then
                closed=true;return false,'SESSION_CHANGED'
            end
            stage='request read'
            local packet=native.read(root .. '\\request.txt')
            if not packet then return false,'IDLE' end
            stage='authenticated read dispatch'
            local reply=core:process(packet,os.time())
            if not reply then return false,'REJECTED' end
            stage='response write'
            native.write(root .. '\\response.txt',reply)
            if core.stopped then closed=true end
            return true,'REPLIED'
        end)
        release()
        if not ok then error('Console step failed at ' .. stage .. '; no automatic retry',0) end
        return accepted,state
    end
    function session.close() closed=true;return true end
    return session
end
return M
