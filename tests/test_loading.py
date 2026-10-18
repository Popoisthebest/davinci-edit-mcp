"""Exercise the installed module graph with Resolve's missing global libraries."""
import re
import unittest

from lupa.luajit21 import LuaError, LuaRuntime
from resolve_mcp.bundle import BRIDGE, MODULES, bundle, loader_source, lua_string
from tests.support import restricted_loader


class LoadingTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.module=restricted_loader(self.lua)

    def test_read_graph_needs_no_require_package_debug_or_file_loader(self):
        self.lua.execute('loadstring=nil; load=nil')
        for name in ['runtime','crypto','codec','reads','core','bridge','probe']:
            with self.subTest(module=name):self.assertIsNotNone(self.module(name))
        for name in ['require','package','io','debug','loadfile','dofile','loadstring','load']:
            self.assertIsNone(self.lua.globals()[name])
        self.assertEqual(self.module('crypto').sha256('abc'),
            'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

    def test_no_lua_module_uses_package_or_dynamic_code_loading(self):
        for name in MODULES.values():
            with self.subTest(file=name):
                source=(BRIDGE/name).read_text(encoding='utf-8')
                self.assertIsNone(re.search(r'\b(?:require|dofile|loadfile|loadstring)\s*\(',source))
        self.assertNotIn('debug.getinfo',bundle())

    def test_unknown_module_path_cannot_be_loaded(self):
        for name in ['../native','C:\\malicious.lua','os','ffi','bit','package']:
            with self.subTest(name=name):
                with self.assertRaisesRegex(LuaError,'fixed registry'):self.module(name)

    def test_cached_and_cyclic_factories(self):
        self.assertTrue(self.lua.eval('function(a,b) return rawequal(a,b) end')(
            self.module('crypto'),self.module('crypto')))
        new_loader=self.lua.execute((BRIDGE/'loader.lua').read_text())
        cycle=self.lua.execute("return {cycle=function(module) return module('cycle') end}")
        loader=new_loader(cycle)
        with self.assertRaisesRegex(LuaError,'Cyclic'):loader('cycle')

    def test_missing_global_bit_and_partial_bit_fail_closed(self):
        self.lua.globals().bit=None
        with self.assertRaisesRegex(LuaError,'global library: bit'):self.module('crypto')
        self.lua.execute('bit={band=function() return 0 end}')
        with self.assertRaisesRegex(LuaError,'global function: bit.bor'):self.module('crypto')

    def test_missing_global_ffi_does_not_try_require_fallback(self):
        self.lua.globals().ffi=None
        with self.assertRaisesRegex(LuaError,'global library: ffi'):self.module('native')

    def test_probe_failure_is_reported_for_its_exact_context(self):
        for context in ['Console','Utility']:
            lua=LuaRuntime(unpack_returned_tuples=True)
            module=restricted_loader(lua)
            lua.globals().ffi=None
            report=module('probe').run('C:\\not-used',context)
            self.assertFalse(report.ok)
            self.assertEqual(report.context,context)
            self.assertEqual(report.result,'FAIL')
            self.assertEqual(report.editing_test,'NOT_RUN')

    def test_lua_path_literal_roundtrip(self):
        text='C:\\사용자\\A "quoted" path\\probe.lua'
        self.assertEqual(self.lua.execute('return '+lua_string(text)),text)
