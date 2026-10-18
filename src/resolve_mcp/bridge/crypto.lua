-- Original implementation: SHA-256/HMAC using LuaJIT bit operations.
local module = ...
local bit = module('runtime').bit()
local band, bxor, bnot, ror, rshift = bit.band, bit.bxor, bit.bnot, bit.ror, bit.rshift
local M = {}
local K = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
}
function M.hex(s)
    return (s:gsub('.', function(c) return string.format('%02x', string.byte(c)) end))
end
function M.unhex(s)
    assert(type(s) == 'string' and #s % 2 == 0 and not s:find('[^0-9a-f]'), 'Invalid hex')
    return (s:gsub('..', function(pair) return string.char(tonumber(pair, 16)) end))
end
function M.equal(a, b)
    if #a ~= #b then return false end
    local difference = 0
    for i = 1, #a do difference = bit.bor(difference, bxor(a:byte(i), b:byte(i))) end
    return difference == 0
end
function M.sha256(data)
    local size = #data * 8
    assert(size < 4294967296, 'SHA input too large')
    data = data .. '\128' .. string.rep('\0', (55 - #data) % 64)
        .. '\0\0\0\0' .. string.char(band(rshift(size,24),255),band(rshift(size,16),255),band(rshift(size,8),255),band(size,255))
    local h = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}
    for offset = 1, #data, 64 do
        local w = {}
        for i = 0, 15 do
            local a,b,c,d = data:byte(offset+i*4, offset+i*4+3)
            w[i] = bit.tobit(a*16777216 + b*65536 + c*256 + d)
        end
        for i = 16, 63 do
            local x,y = w[i-15],w[i-2]
            w[i] = bit.tobit(w[i-16] + bxor(ror(x,7),ror(x,18),rshift(x,3))
                + w[i-7] + bxor(ror(y,17),ror(y,19),rshift(y,10)))
        end
        local a,b,c,d,e,f,g,z = unpack(h)
        for i = 0, 63 do
            local t1 = bit.tobit(z + bxor(ror(e,6),ror(e,11),ror(e,25))
                + bxor(band(e,f),band(bnot(e),g)) + K[i+1] + w[i])
            local t2 = bit.tobit(bxor(ror(a,2),ror(a,13),ror(a,22))
                + bxor(band(a,b),band(a,c),band(b,c)))
            z,g,f,e,d,c,b,a = g,f,e,bit.tobit(d+t1),c,b,a,bit.tobit(t1+t2)
        end
        local values = {a,b,c,d,e,f,g,z}
        for i = 1, 8 do h[i] = bit.tobit(h[i] + values[i]) end
    end
    local output = {}
    for i = 1,8 do output[i] = bit.tohex(h[i]) end
    return table.concat(output)
end
function M.hmac(key, data)
    if #key > 64 then key = M.unhex(M.sha256(key)) end
    key = key .. string.rep('\0', 64 - #key)
    local inner, outer = {}, {}
    for i = 1,64 do
        inner[i],outer[i] = string.char(bxor(key:byte(i),54)),string.char(bxor(key:byte(i),92))
    end
    return M.sha256(table.concat(outer) .. M.unhex(M.sha256(table.concat(inner) .. data)))
end
return M
