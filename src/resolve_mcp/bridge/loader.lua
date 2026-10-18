-- Factories are embedded by the trusted build step, never read from requests.
return function(factories)
    local cache, loading = {}, {}
    local function module(name)
        assert(type(name) == 'string' and type(factories[name]) == 'function','Module is not in the fixed registry')
        if cache[name] then return cache[name] end
        assert(not loading[name],'Cyclic internal module dependency')
        loading[name] = true
        local ok,result = pcall(factories[name],module)
        loading[name] = nil
        assert(ok,result)
        assert(type(result) == 'table','Internal module must return a table')
        cache[name] = result
        return result
    end
    return module
end
