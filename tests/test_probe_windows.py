"""Native Windows I/O and one-shot probe. Resolve getters are still simulated."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
from resolve_mcp.bundle import bundle, prepare_probe
from resolve_mcp.protocol import request,response
from resolve_mcp.transport import Mailbox,atomic_write,read_data
from tests.support import FAKE_RESOLVE,restricted_loader


@unittest.skipUnless(os.name=='nt','Requires native Windows FFI file I/O')
class ProbeWindowsTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.module=restricted_loader(self.lua)
        # The probe cannot call setters: none exist on these simulated objects.
        api=self.lua.execute(FAKE_RESOLVE)
        self.lua.globals().resolve=api.resolve
        self.lua.execute('loadstring=nil; load=nil; bmd={wait=function() end}')

    def test_ffi_function_call_is_separate_from_file_io(self):
        self.assertTrue(self.module('native').ffi_call_test())

    def test_console_and_utility_bundles_use_global_libraries(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            for context in ['Console','Utility']:
                with self.subTest(context=context):
                    report=self.lua.execute(bundle(root,context))
                    self.assertEqual(report.result,'PASS')
                    self.assertEqual(report.context,context)
                    self.assertEqual(report.require_type,'nil')
                    self.assertEqual(report.package_type,'nil')
            files=list(root.glob('*/result.json'))
            self.assertEqual(len(files),2)
            for path in files:
                data=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(data['result'],'PASS')
                self.assertEqual(data['editing_test'],'NOT_RUN')
            self.assertFalse((root/'session.key').exists())
            self.assertFalse((root/'approval.txt').exists())

    def test_production_bundle_starts_without_debug_or_package_system(self):
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            box=Mailbox()
            rid='a'*32
            atomic_write(box.root/'request.txt',request(box.key,rid,None,'ping',{},5))
            ticks=[]
            def tick():
                ticks.append(1)
                if len(ticks)>3:raise AssertionError('Bridge did not stop')
                if len(ticks)>1:return
                encoded=read_data(box.root/'response.txt')
                instance,_=response(box.key,encoded,rid,None)
                atomic_write(box.root/'request.txt',request(box.key,'c'*32,instance,'stop',{},5))
            self.lua.globals().tick=tick
            self.lua.execute('bmd={wait=function() tick() end}')
            self.assertTrue(self.lua.execute(bundle()))
            self.assertGreaterEqual(len(ticks),1)

    def test_preparation_preserves_existing_utility_scripts(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            utility=root/'roaming'/'Blackmagic Design'/'DaVinci Resolve'/'Support'/'Fusion'/'Scripts'/'Utility'
            utility.mkdir(parents=True)
            originals=[utility/'ResolveMCPNext.lua',utility/'ResolveMCP.lua']
            for path in originals:path.write_bytes(b'preserved existing bridge')
            with patch.dict(os.environ,{'LOCALAPPDATA':str(root),'APPDATA':str(root/'roaming')}):
                info=prepare_probe(True)
            for path in originals:self.assertEqual(path.read_bytes(),b'preserved existing bridge')
            self.assertTrue(Path(info['utility_menu_script']).is_file())
            self.assertNotIn(Path(info['utility_menu_script']),originals)
            self.assertTrue(Path(info['console_script']).is_file())
