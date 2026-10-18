-- Data-only scalar arguments and JSON responses. No dynamic evaluation.
local M = {}
local array_mt = {}
function M.array(t) return setmetatable(t or {}, array_mt) end
function M.encode(value, depth)
    depth = depth or 0
    assert(depth <= 20, 'Response nesting limit exceeded')
    local kind = type(value)
    if kind == 'string' then
        return '"' .. value:gsub('[%z\1-\31\\"]', function(c)
            if c == '"' then return '\\"' end
            if c == '\\' then return '\\\\' end
            return string.format('\\u%04x', c:byte())
        end) .. '"'
    elseif kind == 'number' then
        assert(value == value and math.abs(value) < math.huge, 'Non-finite value')
        return tostring(value)
    elseif kind == 'boolean' then return tostring(value)
    elseif kind == 'nil' then return 'null'
    elseif kind == 'table' then
        local output, count = {}, 0
        if getmetatable(value) == array_mt then
            assert(#value <= 1000, 'Result limit exceeded')
            for i, child in ipairs(value) do output[i] = M.encode(child, depth + 1) end
            return '[' .. table.concat(output, ',') .. ']'
        end
        for key,child in pairs(value) do
            count = count + 1
            assert(type(key) == 'string' and count <= 1000, 'Invalid response object')
            output[count] = M.encode(key) .. ':' .. M.encode(child, depth + 1)
        end
        table.sort(output)
        return '{' .. table.concat(output, ',') .. '}'
    end
    error('Unsupported response value')
end
function M.params(raw, crypto)
    local text = crypto.unhex(raw)
    assert(#text <= 131072, 'Parameter limit exceeded')
    local result, count, rebuilt = {}, 0, {}
    for record in text:gmatch('([^\n]*)\n') do
        count = count + 1
        assert(count <= 16, 'Too many parameters')
        local name,kind,value = record:match('^([a-z_]+):([sib]):([0-9a-f%-]*)$')
        assert(name and #name <= 40 and result[name] == nil, 'Invalid parameter')
        if kind == 's' then
            assert(#value <= 65536, 'String limit exceeded')
            result[name] = crypto.unhex(value)
            assert(not result[name]:find('%z'), 'NUL is forbidden')
        elseif kind == 'i' then
            assert(value:match('^%-?%d+$'), 'Invalid integer')
            local number = tonumber(value)
            assert(number and math.abs(number) < 9007199254740992 and number % 1 == 0, 'Integer limit exceeded')
            result[name] = number
        else
            assert(value == '0' or value == '1', 'Invalid boolean')
            result[name] = value == '1'
        end
        rebuilt[#rebuilt+1] = record .. '\n'
    end
    assert(table.concat(rebuilt) == text, 'Invalid trailing data')
    return result
end
return M
