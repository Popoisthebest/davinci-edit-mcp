-- Pure protocol/dispatch core; adapters own OS I/O and locking.
local M = {}
function M.new(crypto, codec, operations, key, bridge_id)
    assert(#key == 32 and #bridge_id == 32)
    local self = {stopped=false,cache={}}
    local function signed(fields)
        local body = table.concat(fields,'\n') .. '\n'
        return body .. crypto.hmac(key,body) .. '\n'
    end
    local function reply(id,status,data)
        local encoded = codec.encode(data)
        assert(#encoded <= 500000, 'Response size limit exceeded')
        return signed({'RMC3',id,bridge_id,status,crypto.hex(encoded)})
    end
    function self:process(packet, now)
        if type(packet) ~= 'string' or #packet > 1048576 then return nil end
        local lines = {}
        for line in packet:gmatch('([^\n]*)\n') do lines[#lines+1] = line end
        if #lines ~= 7 or table.concat(lines,'\n') .. '\n' ~= packet or lines[1] ~= 'RMC3' then return nil end
        local body = table.concat(lines,'\n',1,6) .. '\n'
        if not crypto.equal(crypto.hmac(key,body),lines[7]) then return nil end
        local id, deadline, instance, op = lines[2], tonumber(lines[3]), lines[4], lines[5]
        if #id ~= 32 or id:find('[^0-9a-f]') then return nil end
        if not deadline or deadline % 1 ~= 0 or deadline < now or deadline > now + 30 then
            return reply(id,'ERROR',{code='EXPIRED',message='Request deadline is invalid or expired'})
        end
        if instance ~= bridge_id and not (instance == '-' and op == 'ping') then
            return reply(id,'ERROR',{code='BRIDGE_RESTARTED',message='Reconnect after bridge restart'})
        end
        for cached_id,entry in pairs(self.cache) do
            if entry.deadline < now then self.cache[cached_id] = nil end
        end
        local existing = self.cache[id]
        if existing then
            if existing.body ~= body then return reply(id,'ERROR',{code='DUPLICATE_ID',message='Request identifier reused with different data'}) end
            return existing.response
        end
        local count = 0
        for _ in pairs(self.cache) do count = count + 1 end
        if count >= 1024 then return reply(id,'ERROR',{code='BUSY',message='Request cache is full'}) end
        local parsed,params = pcall(codec.params,lines[6],crypto)
        local result
        if not parsed then result = reply(id,'ERROR',{code='INVALID_REQUEST',message='Invalid parameter data'})
        elseif op == 'stop' and next(params) == nil then
            self.stopped = true
            result = reply(id,'OK',{stopped=true})
        elseif not operations[op] then result = reply(id,'ERROR',{code='OP_NOT_ALLOWED',message='Operation is not enabled'})
        elseif next(params) ~= nil then result = reply(id,'ERROR',{code='INVALID_REQUEST',message='Read operations accept no parameters'})
        else
            local ok,data = pcall(operations[op],params)
            if ok then
                local encoded,packet_result = pcall(reply,id,'OK',data)
                if encoded then result = packet_result
                else result = reply(id,'ERROR',{code='RESULT_LIMIT',message='Response is invalid or too large'}) end
            else
                local unsupported = tostring(data):find('UNSUPPORTED_API:',1,true)
                result = reply(id,'ERROR',{code=unsupported and 'UNSUPPORTED_API' or 'API_ERROR',message=unsupported and 'Required Resolve API is unavailable' or 'Resolve API failed; no automatic retry'})
            end
        end
        self.cache[id] = {body=body,response=result,deadline=deadline}
        return result
    end
    return self
end
return M
