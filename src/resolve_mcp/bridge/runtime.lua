-- Resolve may supply these globals while omitting the Lua package system.
local M = {}
local function library(name, methods)
    local value = rawget(_G,name)
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
    local value = rawget(_G,'resolve')
    local host = rawget(_G,'bmd')
    if not value and host and type(host.scriptapp) == 'function' then value = host.scriptapp('Resolve') end
    assert(value,'Resolve object unavailable in this execution context')
    return value
end
return M
