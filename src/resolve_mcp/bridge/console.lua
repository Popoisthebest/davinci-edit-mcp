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
    local bridge_id=native.random_hex()
    local operations,writable
    if enable_edits == true then
        operations,writable=module('bridge').operations(runtime.resolve(),codec,key,{
            root=root,bridge_id=bridge_id,read=native.read,write=native.write,
            monotonic_seconds=native.monotonic_seconds,wait=bmd and bmd.wait,canonical_file=native.canonical_file,
            canonical_directory=native.canonical_directory,random_hex=native.random_hex,now=os.time})
    else operations=module('reads').new(runtime.resolve(),codec) end
    local core=module('core').new(crypto,codec,operations,key,bridge_id,writable)
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
    function session.run(seconds,context,startup_seconds)
        seconds=seconds or 180;context=context or 'Console'
        assert(type(seconds)=='number' and seconds%1==0 and seconds>=1 and seconds<=600,'Service limit is 1-600 seconds')
        assert(context=='Console' or context=='Utility','Invalid service context')
        assert(startup_seconds==nil or (type(startup_seconds)=='number' and startup_seconds%1==0
            and startup_seconds>=1 and startup_seconds<=600),'Startup limit is 1-600 seconds')
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
            if startup_seconds then
                status('WAITING_FOR_CLIENT')
                local until_ready=native.monotonic_seconds()+startup_seconds
                local nonce
                while not nonce and native.monotonic_seconds()<until_ready do
                    assert(native.read(root .. '\\session.key')==raw_key,'Session changed during startup')
                    local packet=native.read(root .. '\\start.txt')
                    if packet and #packet<=1024 then
                        local fields={}
                        for line in packet:gmatch('([^\n]*)\n') do fields[#fields+1]=line end
                        if #fields==5 and table.concat(fields,'\n')..'\n'==packet
                            and fields[1]=='RMC3' and fields[2]=='START' then
                            local body=table.concat(fields,'\n',1,4)..'\n'
                            local expiry=tonumber(fields[4])
                            if crypto.equal(crypto.hmac(key,body),fields[5]) and #fields[3]==32
                                and not fields[3]:find('[^0-9a-f]') and expiry and expiry%1==0
                                and expiry>=os.time() and expiry<=os.time()+600 then nonce=fields[3] end
                        end
                    end
                    if not nonce then bmd.wait(0.02) end
                end
                assert(nonce,'STARTUP_TIMEOUT: no authenticated client; no requests dispatched')
                local body=table.concat({'RMC3','READY',nonce,bridge_id},'\n')..'\n'
                native.write(root .. '\\ready.txt',body..crypto.hmac(key,body)..'\n')
            end
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
