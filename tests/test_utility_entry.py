"""Entry failures must be distinguishable without a working file adapter."""
from pathlib import Path
import re
import unittest

from lupa.luajit21 import LuaError, LuaRuntime
from lupa.lua51 import LuaRuntime as Lua51Runtime
from resolve_mcp.bundle import BRIDGE, loader_source, utility_diagnostic


ROOT=Path('C:/fixtures/ResolveMCPProbe_'+'a'*32)
UI_FIXTURE='''
messages={}; dialogs={}
print=function(text) messages[#messages+1]=text end
fusion={AskUser=function(_,title,fields) dialogs[#dialogs+1]=fields[1].Default end}
require=nil;package=nil;io=nil;debug=nil;loadfile=nil;dofile=nil
'''


class UtilityEntryTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(UI_FIXTURE)

    def test_scoped_and_inherited_host_globals_work_without_raw_global_entries(self):
        self.lua.execute('''
            local libraries={ffi={os='Windows'},bit={},resolve={marker='scoped'},bmd={}}
            for _,name in ipairs({'cdef','load','new','typeof','cast','string'}) do libraries.ffi[name]=function() end end
            for _,name in ipairs({'band','bor','bxor','bnot','ror','rshift','tobit','tohex'}) do libraries.bit[name]=function() end end
            env_fixture=setmetatable({}, {__index=function(_,name) return libraries[name] or _G[name] end})
            ffi=nil;bit=nil;resolve=nil;bmd=nil
        ''')
        execute=self.lua.eval('function(text) local chunk=assert(loadstring(text));setfenv(chunk,env_fixture);return chunk() end')
        runtime=execute(loader_source()+"return module('runtime')")
        self.assertEqual(runtime.ffi().os,'Windows')
        self.assertIsNotNone(runtime.bit().band)
        self.assertEqual(runtime.resolve().marker,'scoped')

    def test_no_ffi_still_shows_entry_and_exact_failure_in_plain_lua51(self):
        lua=Lua51Runtime(unpack_returned_tuples=True)
        lua.execute(UI_FIXTURE+';ffi=nil;bit=nil;print=nil')
        report=lua.execute(utility_diagnostic(ROOT))
        self.assertEqual((report.result,report.last_stage),('FAIL','FFI_GLOBALS'))
        self.assertIn('Missing global library: ffi',report.entry_error)
        self.assertEqual(len(lua.globals().dialogs),2)
        self.assertIn('ENTRY reached',lua.globals().dialogs[1])
        self.assertIn('FFI_GLOBALS',lua.globals().dialogs[2])
        self.assertEqual(report.environment.lua_version,'Lua 5.1')

    def test_no_ffi_or_ui_raises_a_host_error_instead_of_silent_return(self):
        self.lua.execute('ffi=nil;bit=nil;fusion=nil;print=nil')
        with self.assertRaisesRegex(LuaError,'last_stage=FFI_GLOBALS'):
            self.lua.execute(utility_diagnostic(ROOT))

    def test_broken_host_ui_does_not_hide_missing_ffi(self):
        self.lua.execute("ffi=nil;fusion.AskUser=function() error('UI unavailable') end")
        with self.assertRaisesRegex(LuaError,'Missing global library: ffi'):
            self.lua.execute(utility_diagnostic(ROOT))

    def test_cdef_dll_load_and_call_failures_have_distinct_stages(self):
        for stage,setup in [
            ('FFI_CDEF',"ffi.cdef=function() error('cdef refused') end"),
            ('FFI_KERNEL32_LOAD',"ffi.load=function() error('DLL refused') end"),
            ('FFI_CALL',"ffi.load=function() return {GetCurrentProcessId=function() error('call refused') end} end"),
        ]:
            with self.subTest(stage=stage):
                lua=LuaRuntime(unpack_returned_tuples=True)
                lua.execute(UI_FIXTURE+'''
                    ffi={os='Windows',typeof=function() return true end,new=function() return {[0]=42} end,
                        cdef=function() end,load=function() end,cast=function() end,string=function() end}
                '''+setup)
                report=lua.execute(utility_diagnostic(ROOT))
                self.assertEqual((report.result,report.last_stage),('FAIL',stage))
                self.assertIn('refused',report.entry_error)
                self.assertIn(stage,lua.globals().dialogs[2])

    def test_independent_artifact_is_ascii_compiles_and_has_no_full_query_graph(self):
        source=utility_diagnostic(Path('C:/Users/사용자/ResolveMCPProbe_'+'a'*32))
        self.assertTrue(source.isascii())
        self.assertTrue(self.lua.eval('function(text) return loadstring(text) ~= nil end')(source))
        self.assertNotIn('QUERY_projects',source)
        self.assertNotIn('GetProjectManager',source)
        self.assertNotIn('HMAC_VECTOR',source)
        self.assertNotIn('factory_loader({})',source)
        self.assertIsNone(re.search(r'\b(?:require|dofile|loadfile|loadstring)\s*\(',source))
        self.assertNotIn('SetPrefs',(BRIDGE/'utility_entry.lua').read_text())
