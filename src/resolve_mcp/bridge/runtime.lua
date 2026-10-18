-- Resolve may supply these globals while omitting the Lua package system.
local M = {}
-- Utility chunks can have their own environment (including __index lookup).
-- rawget(_G, ...) bypasses that environment and can miss host-provided globals.
local function library(name, methods)
    local libraries = {ffi=ffi,bit=bit}
    local value = libraries[name]
    assert(type(value) == 'table','Missing global library: ' .. name)
    for _,method in ipairs(methods) do
        assert(type(value[method]) == 'function','Missing global function: ' .. name .. '.' .. method)
    end
    return value
end
function M.ffi()
    local value = library('ffi',{'cdef','load','new','typeof','cast','string'})
    assert(value.os == 'Windows','Windows FFI is required for live file I/O')
    return value
end
function M.bit()
    return library('bit',{'band','bor','bxor','bnot','ror','rshift','tobit','tohex'})
end
function M.resolve()
    local value,host = resolve,bmd
    if not value and host and type(host.scriptapp) == 'function' then value = host.scriptapp('Resolve') end
    assert(value,'Resolve object unavailable in this execution context')
    return value
end
return M
