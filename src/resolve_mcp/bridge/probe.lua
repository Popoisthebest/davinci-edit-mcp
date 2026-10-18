-- One shot: read-only Resolve getters, separate diagnostic files, no approvals.
local module = ...
local M = {}
function M.run(parent,context)
    assert(context == 'Console' or context == 'Utility' or context == 'CI','Invalid probe context')
    local report = {probe_format=2,probe_id=parent:match('ResolveMCPProbe_([0-9a-f]+)$') or 'unprepared',
        context=context,ok=true,complete=true,checks={},result='RUNNING',
        context_origin='prepared entrypoint label; UI execution must be confirmed by user',
        require_type=type(require),package_type=type(package),
        ffi_type=type(ffi),bit_type=type(bit),
        debug_type=type(debug),io_type=type(io),
        project_scope='read-only',editing_test='NOT_RUN'}
    local native,crypto,codec,operations,directory
    local function emit(text)
        local output = print
        if type(output) == 'function' then pcall(output,'[ResolveMCP ReadOnlyProbe ' .. context .. '] ' .. text) end
    end
    local function result(final)
        if not final then return 'RUNNING' end
        return not report.ok and 'FAIL' or (report.complete and 'PASS' or 'PARTIAL')
    end
    local function persist(stage,final)
        report.last_stage,report.result = stage,result(final)
        if not native or not codec then return end
        local saved = false
        if directory then
            local ok,err = pcall(function() native.write(directory .. '\\result.json',codec.encode(report)) end)
            saved = ok
            if not ok then
                report.ok=false;report.result=result(final)
                report.result_write_error=tostring(err):sub(1,240)
                emit('RESULT_WRITE_FAILED: ' .. report.result_write_error)
            end
        end
        local receipt = {probe_format=2,probe_id=report.probe_id,context=context,
            status=final and 'FINISHED' or 'RUNNING',last_stage=stage,result=report.result,
            ffi_type=report.ffi_type,bit_type=report.bit_type,
            result_file_written=saved,artifact_directory=directory,
            result_write_error=report.result_write_error,entry_error=report.entry_error}
        local ok,err = pcall(function() native.write(parent .. '\\' .. context .. '-launch.json',codec.encode(receipt)) end)
        if not ok then
            report.ok=false;report.result=result(final)
            emit('RECEIPT_WRITE_FAILED: ' .. tostring(err):sub(1,240))
        end
    end
    local function check(name,action)
        persist(name,false)
        local ok,value = pcall(action)
        local entry = {name=name,status=ok and 'PASS' or 'FAIL'}
        if not ok then
            report.ok=false;entry.detail=tostring(value):sub(1,240)
        elseif value == 'SKIP' then
            entry.status='SKIP';report.complete=false
        elseif type(value) == 'table' then
            entry.normalization=value -- type counts only, never project names
        end
        report.checks[#report.checks+1]=entry
        emit(entry.status .. ' ' .. name .. (entry.detail and ': ' .. entry.detail or ''))
        persist(name .. '_DONE',false)
        return ok
    end
    -- This is reached before global bit/HMAC/module-graph checks. The file
    -- adapter uses global FFI and checked paths, but does not depend on bit.
    emit('ENTRY probe_format=2; ffi=' .. report.ffi_type .. '; bit=' .. report.bit_type)
    local codec_ok,value = pcall(module,'codec')
    if codec_ok then codec=value;report.checks=codec.array(report.checks) end
    local native_ok,adapter = pcall(module,'native')
    if native_ok then
        native=adapter
        persist('ENTRY',false)
        local made,path = pcall(native.create_probe_directory,parent,context)
        if made then directory=path else report.ok=false;report.entry_error=tostring(path):sub(1,240) end
        persist('ENTRY_READY',false)
    else
        report.entry_error=tostring(adapter):sub(1,240)
        report.ok=false
        emit('NO_FILE_WRITER: ' .. report.entry_error)
    end
    local globals_ok=check('GLOBALS',function() module('runtime').ffi();module('runtime').bit() end)
    local modules_ok=globals_ok and check('MODULE_GRAPH',function()
        assert(native,report.entry_error or 'File adapter unavailable')
        crypto,codec=module('crypto'),module('codec')
        module('reads');module('core')
        local entry=module('bridge')
        if entry.load_modules then entry.load_modules() end -- definitions only
    end)
    if modules_ok then
        check('BRIDGE_HOST_FUNCTIONS',function()
            assert(bmd and type(bmd.wait) == 'function','bmd.wait unavailable in this context')
            assert(os and type(os.time) == 'function','os.time unavailable in this context')
        end)
        check('FFI_WIN32_CALL',function() assert(native.ffi_call_test()) end)
        check('HMAC_VECTOR',function()
            assert(crypto.hmac(string.rep(string.char(11),20),'Hi There') ==
                'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7','HMAC vector mismatch')
        end)
        check('WIN32_FILE_IO',function()
            assert(directory,'Diagnostic directory unavailable; inspect launch receipt')
            local path=directory .. '\\진단_왕복.txt'
            assert(native.read(path) == nil,'Probe path must be new')
            native.write(path,'ResolveMCP 한글 file roundtrip 1')
            assert(native.read(path) == 'ResolveMCP 한글 file roundtrip 1','Initial read mismatch')
            native.write(path,'ResolveMCP 한글 file roundtrip 2')
            assert(native.read(path) == 'ResolveMCP 한글 file roundtrip 2','Atomic replacement mismatch')
        end)
        local api_ok=check('RESOLVE_CONTEXT',function()
            operations=module('reads').new(module('runtime').resolve(),codec)
        end)
        if api_ok then
            check('AUTHENTICATED_CHANNEL',function()
                local key=crypto.unhex(native.random_hex() .. native.random_hex())
                local id,instance=native.random_hex(),native.random_hex()
                local core=module('core').new(crypto,codec,operations,key,instance)
                local now=os.time()
                local body=table.concat({'RMC3',id,tostring(now+10),'-','ping',''},'\n') .. '\n'
                local packet=body .. crypto.hmac(key,body) .. '\n'
                assert(core:process(packet:gsub('ping','stop'),now) == nil,'Tampered request accepted')
                if directory then native.write(directory .. '\\authenticated-request.txt',packet);packet=native.read(directory .. '\\authenticated-request.txt') end
                local response=assert(core:process(packet,now),'Missing signed reply')
                local reply_body,mac=response:match('^(.*\n)([0-9a-f]+)\n$')
                assert(reply_body and crypto.equal(crypto.hmac(key,reply_body),mac),'Invalid response HMAC')
                assert(response:find('\nOK\n',1,true),'Read-only ping failed')
                assert(core:process(packet,now) == response,'Duplicate request result changed')
                if directory then native.write(directory .. '\\authenticated-response.txt',response) end
            end)
            for _,name in ipairs({'ping','current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items'}) do
                check('QUERY_' .. name,function()
                    local data=operations[name]()
                    assert(type(data) == 'table','Invalid query result')
                    codec.encode(data)
                    if name == 'ping' then report.resolve_version=data.resolve_version end
                    if data.project_open == false or data.timeline_open == false then return 'SKIP' end
                    if name == 'projects' then return data.normalization end
                end)
            end
        end
    end
    persist('FINISHED',true)
    if directory then emit('Artifacts: ' .. directory) end
    emit('RESULT=' .. report.result .. '; actual clip editing NOT_RUN')
    return report
end
return M
