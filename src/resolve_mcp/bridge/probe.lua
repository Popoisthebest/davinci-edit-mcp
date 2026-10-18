-- One shot. No project setters, editing dispatcher, live mailbox or prefs access.
local module = ...
local M = {}
function M.run(parent,context)
    local report = {context=context,ok=true,complete=true,checks={},
        require_type=type(rawget(_G,'require')),package_type=type(rawget(_G,'package')),
        project_scope='read-only',editing_test='NOT_RUN'}
    local function emit(text) print('[ResolveMCP ReadOnlyProbe ' .. context .. '] ' .. text) end
    local function check(name,action)
        local ok,value = pcall(action)
        local entry = {name=name,status=ok and 'PASS' or 'FAIL'}
        if not ok then
            report.ok = false
            entry.detail = tostring(value):sub(1,240)
        elseif value == 'SKIP' then
            entry.status='SKIP'; report.complete=false
        end
        report.checks[#report.checks+1] = entry
        emit(entry.status .. ' ' .. name .. (entry.detail and ': ' .. entry.detail or ''))
        return ok
    end
    emit('require=' .. report.require_type .. ', package=' .. report.package_type)
    local native,crypto,codec,operations,directory
    local globals_ok = check('GLOBALS',function() module('runtime').ffi();module('runtime').bit() end)
    local modules_ok = globals_ok and check('MODULE_GRAPH',function()
        native,crypto,codec = module('native'),module('crypto'),module('codec')
        report.checks = codec.array(report.checks)
        module('reads');module('core');module('bridge')
        -- Registry may also contain edits in v0.4. Loading definitions does not
        -- construct its dispatcher or grant/perform any editing operation.
        local entry = module('bridge')
        if entry.load_modules then entry.load_modules() end
    end)
    if modules_ok then
        check('FFI_WIN32_CALL',function() assert(native.ffi_call_test()) end)
        check('HMAC_VECTOR',function()
            assert(crypto.hmac(string.rep(string.char(11),20),'Hi There') ==
                'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7','HMAC vector mismatch')
        end)
        check('WIN32_FILE_IO',function()
            directory = native.create_probe_directory(parent,context)
            local path = directory .. '\\진단_왕복.txt'
            assert(native.read(path) == nil,'Probe path must be new')
            native.write(path,'ResolveMCP 한글 file roundtrip 1')
            assert(native.read(path) == 'ResolveMCP 한글 file roundtrip 1','Initial read mismatch')
            native.write(path,'ResolveMCP 한글 file roundtrip 2')
            assert(native.read(path) == 'ResolveMCP 한글 file roundtrip 2','Atomic replacement mismatch')
        end)
        local api_ok = check('RESOLVE_CONTEXT',function()
            -- Deliberately use the read-only factory even in a v0.4 bundle.
            operations = module('reads').new(module('runtime').resolve(),codec)
        end)
        if api_ok then
            check('AUTHENTICATED_CHANNEL',function()
                local key = crypto.unhex(native.random_hex() .. native.random_hex())
                local id,instance = native.random_hex(),native.random_hex()
                local core = module('core').new(crypto,codec,operations,key,instance)
                local now = os.time()
                local body = table.concat({'RMC3',id,tostring(now+10),'-','ping',''},'\n') .. '\n'
                local request = body .. crypto.hmac(key,body) .. '\n'
                assert(core:process(request:gsub('ping','stop'),now) == nil,'Tampered request accepted')
                local request_path = directory and directory .. '\\authenticated-request.txt'
                if request_path then native.write(request_path,request);request=native.read(request_path) end
                local response = assert(core:process(request,now),'Missing signed reply')
                local reply_body,mac = response:match('^(.*\n)([0-9a-f]+)\n$')
                assert(reply_body and crypto.equal(crypto.hmac(key,reply_body),mac),'Invalid response HMAC')
                assert(response:find('\nOK\n',1,true),'Read-only ping failed')
                assert(core:process(request,now) == response,'Duplicate request result changed')
                if directory then native.write(directory .. '\\authenticated-response.txt',response) end
            end)
            for _,name in ipairs({'ping','current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items'}) do
                check('QUERY_' .. name,function()
                    local data = operations[name]()
                    assert(type(data) == 'table','Invalid query result')
                    codec.encode(data) -- Prove serialization without logging private metadata.
                    if name == 'ping' then report.resolve_version=data.resolve_version end
                    if data.project_open == false or data.timeline_open == false then return 'SKIP' end
                end)
            end
        end
    end
    report.result = not report.ok and 'FAIL' or (report.complete and 'PASS' or 'PARTIAL')
    if directory then
        check('REPORT_FILE',function() native.write(directory .. '\\result.json',codec.encode(report)) end)
        report.result = not report.ok and 'FAIL' or (report.complete and 'PASS' or 'PARTIAL')
        emit('Artifacts: ' .. directory)
    end
    emit('RESULT=' .. report.result .. '; actual clip editing NOT_RUN')
    return report
end
return M
