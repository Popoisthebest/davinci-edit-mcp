"""Native Windows I/O and one-shot probe. Resolve getters are still simulated."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
from resolve_mcp.bundle import bundle, prepare_probe, utility_diagnostic
from resolve_mcp.inspection import inspect_probe
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

    def test_missing_bit_still_leaves_a_failure_report_and_receipt(self):
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            info=prepare_probe(False);root=Path(info['probe_root'])
            self.lua.globals().bit=None
            self.lua.execute('print=function() end')
            report=self.lua.execute(bundle(root,'Utility'))
            self.assertEqual(report.result,'FAIL')
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            self.assertEqual((row['status'],row['bit_type'],row['report_result']),('FINISHED','nil','FAIL'))
            self.assertTrue(any(c['name']=='GLOBALS' and c['status']=='FAIL' for c in row['checks']))
            self.assertFalse((root/'approval.txt').exists())

    def test_missing_ffi_keeps_prepared_receipt_and_emits_entry_diagnostic(self):
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            info=prepare_probe(False);root=Path(info['probe_root'])
            self.lua.globals().ffi=None
            self.lua.execute('messages={};print=function(line) messages[#messages+1]=line end')
            report=self.lua.execute(bundle(root,'Utility'))
            self.assertEqual(report.result,'FAIL')
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            self.assertEqual(row['status'],'PREPARED')
            self.assertIn('NO_FILE_WRITER','\n'.join(self.lua.globals().messages.values()))

    def test_failed_result_write_is_recorded_in_launch_receipt(self):
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            info=prepare_probe(False);root=Path(info['probe_root'])
            self.lua.globals().native_fixture=self.module('native')
            self.lua.execute('''
                print=function() end
                local write=native_fixture.write
                native_fixture.write=function(path,data)
                    if path:sub(-11)=='result.json' then error('simulated result write failure') end
                    return write(path,data)
                end
            ''')
            report=self.module('probe').run(str(root),'Utility')
            self.assertEqual(report.result,'FAIL')
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            self.assertEqual(row['report_result'],'MISSING')
            self.assertIn('simulated result write failure',row['result_write_error'])

    def test_mixed_project_response_is_normalized_in_saved_report(self):
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            info=prepare_probe(False);root=Path(info['probe_root'])
            self.lua.execute("resolve:GetProjectManager().GetProjectListInCurrentFolder=function() return {'B',2,'A',count=2} end")
            report=self.lua.execute(bundle(root,'Utility'))
            self.assertEqual(report.result,'PASS')
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            query=next(c for c in row['checks'] if c['name']=='QUERY_projects')
            self.assertEqual(query['status'],'PASS')
            self.assertEqual(query['normalization']['ignored_entries'],2)

    def test_independent_entry_uses_scoped_ffi_without_full_queries_or_bit(self):
        with TemporaryDirectory(prefix='유틸리티_') as temporary,patch.dict(os.environ,{
            'LOCALAPPDATA':temporary,'APPDATA':str(Path(temporary)/'roaming')}):
            info=prepare_probe(True,utility_entry=True);root=Path(info['probe_root'])
            self.assertEqual(info['probe_format'],3)
            self.assertNotIn('console_script',info)
            self.lua.execute('''
                dialogs={}
                env_fixture=setmetatable({ffi=ffi,fusion={AskUser=function(_,title,fields)
                    dialogs[#dialogs+1]=fields[1].Default end}}, {__index=_G})
                ffi=nil;bit=nil;print=nil
                resolve.GetProjectManager=function() error('Project access is forbidden in entry diagnosis') end
            ''')
            chunk=self.lua.compile(Path(info['utility_menu_script']).read_text(encoding='ascii'))
            self.lua.eval('setfenv')(chunk,self.lua.globals().env_fixture)
            report=chunk()
            self.assertEqual(report.result,'PASS')
            self.assertEqual(len(self.lua.globals().dialogs),2)
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            self.assertEqual((row['status'],row['result']),('FINISHED','PASS'))
            self.assertEqual(row['environment']['symbols']['ffi'],{'resolved':'table','raw_global':'nil'})
            self.assertEqual(row['menu_script_integrity'],'MATCH')
            self.assertFalse((root/'session.key').exists())
            self.assertFalse((root/'approval.txt').exists())

    def test_independent_entry_records_a_file_writer_failure_in_ui(self):
        import ctypes
        from ctypes import wintypes as w
        with TemporaryDirectory() as temporary,patch.dict(os.environ,{'LOCALAPPDATA':temporary}):
            info=prepare_probe(False,utility_entry=True);root=Path(info['probe_root'])
            self.lua.execute('dialogs={};fusion={AskUser=function(_,title,fields) dialogs[#dialogs+1]=fields[1].Default end}')
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
            kernel.CreateFileW.restype=w.HANDLE
            kernel.CloseHandle.argtypes=[w.HANDLE]
            handle=kernel.CreateFileW(str(root/'Utility-launch.json'),0x80000000,0,None,3,128,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:report=self.lua.execute(utility_diagnostic(root))
            finally:kernel.CloseHandle(handle)
            self.assertEqual((report.result,report.last_stage),('FAIL','RECEIPT_WRITE'))
            self.assertRegex(self.lua.globals().dialogs[2],r'Replace/Move=\d+')
            self.assertIn('RECEIPT_WRITE',self.lua.globals().dialogs[2])
            row=inspect_probe(root/'probe-info.json')['contexts']['Utility']
            self.assertEqual(row['status'],'PREPARED')
            self.assertIn('dialogs',row['interpretation'])
