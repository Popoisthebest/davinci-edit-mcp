-- Independent, ASCII-only Utility entry diagnostic. No Resolve project queries,
-- approvals, mailbox, preferences, shell, package system or runtime code loader.
local function fixed_registry()
-- FIXED_REGISTRY
end

local function diagnose(parent)
    local report = {probe_format=3,probe_kind='utility-entry',context='Utility',
        probe_id=parent:match('ResolveMCPProbe_([0-9a-f]+)$'),
        status='RUNNING',last_stage='ENTRY',result='RUNNING',checks={},
        project_scope='no project access',editing_test='NOT_RUN',
        context_origin='prepared label; actual menu execution confirmed by user',
        environment={lua_version=_VERSION,symbols={}},output_channels={}}
    local globals = {ffi=ffi,bit=bit,bmd=bmd,fusion=fusion,fu=fu,resolve=resolve,
        print=print,require=require,package=package,io=io,debug=debug,jit=jit}
    local names = {'ffi','bit','bmd','fusion','fu','resolve','print','require','package','io','debug','jit'}
    for _,name in ipairs(names) do
        local raw = type(_G) == 'table' and type(rawget) == 'function' and rawget(_G,name) or nil
        report.environment.symbols[name] = {resolved=type(globals[name]),raw_global=type(raw)}
    end
    if type(jit) == 'table' and type(jit.version) == 'string' then
        report.environment.jit_version=jit.version:sub(1,80)
    end
    local function emit(text)
        if type(print) == 'function' then
            local ok=pcall(print,'[ResolveMCP UtilityEntry v3] ' .. text)
            report.output_channels.print=ok
        end
    end
    local function notify(message)
        -- A file cannot diagnose the absence of its own writer. Use a host UI
        -- independently of FFI; never write Fusion preferences as a fallback.
        local shown=false
        local ok=pcall(function()
            local host=fusion or fu
            if not host and resolve then host=resolve:Fusion() end
            if not host and bmd and type(bmd.scriptapp) == 'function' then host=bmd.scriptapp('Fusion') end
            if host and type(host.AskUser) == 'function' then
                host:AskUser('ResolveMCP Utility entry v3',{
                    {'Diagnostic','Text',Name='Diagnostic',ReadOnly=true,Lines=12,Default=message}})
                shown=true;report.output_channels.ask_user=true
            end
        end)
        if ok and shown then return true end
        -- Windows UI is an optional second output channel, never a file writer.
        local ui_ok=pcall(function()
            assert(type(ffi) == 'table' and ffi.os == 'Windows')
            ffi.cdef[[int __stdcall MessageBoxW(void*,const wchar_t*,const wchar_t*,unsigned int);]]
            local function wide_ascii(text)
                local buffer=ffi.new('wchar_t[?]',#text+1)
                for i=1,#text do local byte=text:byte(i);buffer[i-1]=byte < 128 and byte or 63 end
                return buffer
            end
            assert(ffi.load('user32').MessageBoxW(nil,wide_ascii(message),
                wide_ascii('ResolveMCP Utility entry v3'),0) ~= 0)
        end)
        report.output_channels.user32=ui_ok
        return ui_ok
    end
    local summary='Utility chunk ENTRY reached. No project access.\nLua: ' .. tostring(_VERSION) ..
        '\nffi resolved/raw _G: ' .. report.environment.symbols.ffi.resolved .. '/' .. report.environment.symbols.ffi.raw_global ..
        '\nbit resolved/raw _G: ' .. report.environment.symbols.bit.resolved .. '/' .. report.environment.symbols.bit.raw_global
    emit(summary)
    local entry_shown=notify(summary)
    local module,native,codec
    local function persist()
        native.write(parent .. '\\Utility-launch.json',codec.encode(report))
    end
    local function step(name,action)
        report.last_stage=name;emit('BEGIN ' .. name)
        local value=action()
        report.checks[#report.checks+1]={name=name,status='PASS'}
        emit('PASS ' .. name)
        return value
    end
    local ok,err=pcall(function()
        module=step('FIXED_REGISTRY',fixed_registry)
        local runtime=step('RUNTIME_MODULE',function() return module('runtime') end)
        local f=step('FFI_GLOBALS',runtime.ffi)
        step('FFI_TYPEOF_NEW',function() assert(f.typeof('int') and f.new('int[1]',42)[0] == 42) end)
        step('FFI_CDEF',function() f.cdef[[unsigned long GetCurrentProcessId(void);]] end)
        local kernel=step('FFI_KERNEL32_LOAD',function() return f.load('kernel32') end)
        step('FFI_CALL',function() assert(kernel.GetCurrentProcessId() > 0) end)
        step('FFI_ADVAPI32_LOAD',function() f.load('advapi32') end)
        codec=step('CODEC_MODULE',function() return module('codec') end)
        report.checks=codec.array(report.checks)
        native=step('NATIVE_MODULE',function() return module('native') end)
        -- Uses the existing Win32 path/reparse guards and atomic file adapter.
        -- A dedicated owner/SYSTEM directory is prepared by Python first.
        step('RECEIPT_WRITE',persist)
    end)
    report.status='FINISHED';report.result=ok and 'PASS' or 'FAIL'
    if not ok then
        report.entry_error=tostring(err):sub(1,500)
        report.checks[#report.checks+1]={name=report.last_stage,status='FAIL',detail=report.entry_error}
    else report.last_stage='FINISHED' end
    if native and codec then
        local saved,write_error=pcall(persist)
        if not saved then
            report.result='FAIL';report.result_write_error=tostring(write_error):sub(1,500)
            emit('RECEIPT_WRITE_FAILED: ' .. report.result_write_error)
        end
    end
    local message='RESULT=' .. report.result .. '; last_stage=' .. report.last_stage ..
        '\n' .. summary .. '\n' .. (report.entry_error or report.result_write_error or
        'Startup and guarded file write succeeded. Full queries and editing were NOT_RUN.')
    emit(message)
    local final_shown=notify(message)
    -- Do not quietly return if neither file output nor a visible UI is usable.
    -- Raising a host error also makes a no-FFI/no-UI failure explicit.
    if report.result == 'FAIL' and not final_shown then error(message,0) end
    report.entry_ui_shown=entry_shown
    return report
end
