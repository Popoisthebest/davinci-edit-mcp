-- Windows LuaJIT file adapter. Works without a global io table.
-- Only fixed mailbox paths are used by v0.3; no command execution is exposed.
local module = ...
local ffi = module('runtime').ffi()
assert(ffi.os == 'Windows', 'Windows LuaJIT is required by the live bridge')
ffi.cdef[[unsigned long GetCurrentProcessId(void); int CreateDirectoryW(const wchar_t*,void*);]]
if not pcall(ffi.typeof,'RM_FILE_INFO') then ffi.cdef[[
unsigned long GetLastError(void);
unsigned long GetFileAttributesW(const wchar_t*);
typedef struct { unsigned long low; unsigned long high; } RM_FILETIME;
typedef struct {
    unsigned long attributes; RM_FILETIME created; RM_FILETIME accessed; RM_FILETIME written;
    unsigned long volume; unsigned long size_high; unsigned long size_low;
    unsigned long links; unsigned long index_high; unsigned long index_low;
} RM_FILE_INFO;
int GetFileInformationByHandle(void*,RM_FILE_INFO*);
unsigned long GetFinalPathNameByHandleW(void*,wchar_t*,unsigned long,unsigned long);
int MultiByteToWideChar(unsigned int,unsigned long,const char*,int,wchar_t*,int);
int WideCharToMultiByte(unsigned int,unsigned long,const wchar_t*,int,char*,int,const char*,int*);
unsigned long GetEnvironmentVariableW(const wchar_t*,wchar_t*,unsigned long);
void* CreateFileW(const wchar_t*,unsigned long,unsigned long,void*,unsigned long,unsigned long,void*);
int ReadFile(void*,void*,unsigned long,unsigned long*,void*);
int WriteFile(void*,const void*,unsigned long,unsigned long*,void*);
int FlushFileBuffers(void*);
int CloseHandle(void*);
int MoveFileExW(const wchar_t*,const wchar_t*,unsigned long);
int ReplaceFileW(const wchar_t*,const wchar_t*,const wchar_t*,unsigned long,void*,void*);
int DeleteFileW(const wchar_t*);
void* CreateMutexW(void*,int,const wchar_t*);
unsigned long WaitForSingleObject(void*,unsigned long);
int ReleaseMutex(void*);
unsigned char SystemFunction036(void*,unsigned long);
]] end
local K = ffi.load('kernel32')
local A = ffi.load('advapi32')
local M = {}
local invalid = ffi.cast('void*',-1)
-- File diagnostics must work even when the host omits the bit library. These
-- Win32 flags are single bits in an unsigned DWORD; arithmetic preserves the
-- same reparse/directory checks without weakening the mandatory HMAC bit checks.
local function has_flag(value,mask) return math.floor(tonumber(value)/mask) % 2 == 1 end
local function wide(text)
    local count = K.MultiByteToWideChar(65001,8,text,#text,nil,0)
    assert(count > 0, 'Invalid UTF-8 path')
    local output = ffi.new('wchar_t[?]',count+1)
    assert(K.MultiByteToWideChar(65001,8,text,#text,output,count) == count)
    return output
end
local function utf8(text,length)
    local count = K.WideCharToMultiByte(65001,0,text,length,nil,0,nil,nil)
    assert(count > 0, 'Invalid wide path')
    local output = ffi.new('char[?]',count)
    assert(K.WideCharToMultiByte(65001,0,text,length,output,count,nil,nil) == count)
    return ffi.string(output,count)
end
function M.root()
    local output = ffi.new('wchar_t[32768]')
    local length = K.GetEnvironmentVariableW(wide('LOCALAPPDATA'),output,32768)
    assert(length > 0 and length < 32768, 'LOCALAPPDATA unavailable')
    return utf8(output,length) .. '\\ResolveMCPNext\\mailbox'
end
function M.ffi_call_test()
    local value = ffi.new('int[1]',42)
    assert(ffi.typeof('int') and value[0] == 42,'FFI allocation/type test failed')
    assert(K.GetCurrentProcessId() > 0,'Win32 FFI call failed')
    return true
end
function M.random_hex()
    local buffer = ffi.new('unsigned char[16]')
    assert(A.SystemFunction036(buffer,16) ~= 0, 'Secure random source unavailable')
    local output = {}
    for i = 0,15 do output[#output+1] = string.format('%02x',buffer[i]) end
    return table.concat(output)
end
local function check_path(path)
    -- Reject a junction in any ancestor, not only a linked final file.
    local normalized = path:gsub('/','\\')
    assert(normalized:match('^%a:\\') and not normalized:find('%.%.'), 'Invalid absolute mailbox path')
    local current = normalized:sub(1,3)
    for segment in normalized:sub(4):gmatch('[^\\]+') do
        current = current .. segment
        local attributes = K.GetFileAttributesW(wide(current))
        if attributes ~= 4294967295 then
            assert(not has_flag(attributes,1024), 'Reparse points are forbidden')
        end
        current = current .. '\\'
    end
end
function M.create_probe_directory(parent,context)
    assert(context == 'Console' or context == 'Utility' or context == 'CI','Invalid probe context')
    check_path(parent)
    local attributes = K.GetFileAttributesW(wide(parent))
    assert(attributes ~= 4294967295 and has_flag(attributes,16),'Prepared probe directory is required')
    local path = parent .. '\\' .. context .. '-' .. M.random_hex()
    check_path(path)
    assert(K.CreateDirectoryW(wide(path),nil) ~= 0,'Cannot create new probe directory')
    return path
end
function M.read(path)
    check_path(path)
    local handle = K.CreateFileW(wide(path),2147483648,7,nil,3,2097152,nil)
    if handle == invalid then
        local code = K.GetLastError()
        -- ReplaceFile can briefly retain a non-shared replacement handle.
        -- Let the next polling tick read it; do not stop/re-execute a command.
        if code == 2 or code == 3 or code == 32 or code == 33 then return nil end
        error('Mailbox read failed')
    end
    local buffer, count = ffi.new('char[1048577]'), ffi.new('unsigned long[1]')
    local ok = K.ReadFile(handle,buffer,1048577,count,nil)
    K.CloseHandle(handle)
    assert(ok ~= 0 and count[0] <= 1048576, 'Invalid mailbox file size or read failure')
    return ffi.string(buffer,count[0])
end
function M.write(path,data)
    check_path(path)
    assert(#data <= 1048576, 'Response size limit exceeded')
    local temporary = path .. '.' .. M.random_hex() .. '.tmp'
    local handle = K.CreateFileW(wide(temporary),1073741824,0,nil,1,128,nil)
    assert(handle ~= invalid, 'Mailbox temporary file creation failed')
    local count = ffi.new('unsigned long[1]')
    local ok = K.WriteFile(handle,data,#data,count,nil)
    local flushed = K.FlushFileBuffers(handle)
    K.CloseHandle(handle)
    local moved = false
    if ok ~= 0 and count[0] == #data and flushed ~= 0 then
        moved = K.ReplaceFileW(wide(path),wide(temporary),nil,0,nil,nil) ~= 0
        if not moved then
            local code = K.GetLastError()
            if code == 2 or code == 3 then moved = K.MoveFileExW(wide(temporary),wide(path),9) ~= 0 end
        end
    end
    if not moved then K.DeleteFileW(wide(temporary)); error('Atomic response write failed') end
end
local function canonical(path,directory)
    check_path(path)
    local handle = K.CreateFileW(wide(path),0,7,nil,3,35651584,nil)
    assert(handle ~= invalid, 'Cannot open approved media path')
    local info,buffer = ffi.new('RM_FILE_INFO[1]'),ffi.new('wchar_t[32768]')
    local ok = K.GetFileInformationByHandle(handle,info)
    local size = K.GetFinalPathNameByHandleW(handle,buffer,32768,0)
    K.CloseHandle(handle)
    assert(ok ~= 0 and size > 0 and size < 32768 and not has_flag(info[0].attributes,1024), 'Unsafe media path')
    assert(has_flag(info[0].attributes,16) == directory, 'Unexpected media path type')
    if not directory then assert(info[0].links == 1, 'Hardlinked media is forbidden') end
    local result = utf8(buffer,size)
    if result:sub(1,4) == string.char(92,92,63,92) then result = result:sub(5) end
    return (result:gsub('\\$',''))
end
function M.canonical_file(path) return canonical(path,false) end
function M.canonical_directory(path) return canonical(path,true) end
function M.acquire(name)
    local handle = K.CreateMutexW(nil,1,wide('Local\\ResolveMCP-' .. name))
    assert(handle ~= nil and handle ~= ffi.NULL, 'Bridge mutex unavailable')
    -- Windows mutexes are reentrant on a thread. Reject an existing object even
    -- on the same thread so a second Utility invocation cannot nest a bridge.
    if K.GetLastError() == 183 then K.CloseHandle(handle); return nil end
    return function() K.ReleaseMutex(handle); K.CloseHandle(handle) end
end
return M
