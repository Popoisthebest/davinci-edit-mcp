"""Actual Windows FFI, ACLs and HMAC; Resolve editing API is simulated."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
from resolve_mcp.edit_validation import prepare_validation, run_validation
from tests.support import FAKE_RESOLVE,restricted_loader
from tests.edit_support import EDIT_API


@unittest.skipUnless(os.name=='nt','Requires Windows FFI/ACL/canonical paths')
class EditValidationWindowsTests(unittest.TestCase):
    def test_real_win32_automatic_service_completes_approved_new_project_workflow(self):
        with TemporaryDirectory(prefix='편집_') as temporary,patch.dict(os.environ,{
            'LOCALAPPDATA':temporary,'APPDATA':str(Path(temporary)/'roaming')}):
            info=prepare_validation();root=Path(info['root'])
            lua=LuaRuntime(unpack_returned_tuples=True);restricted_loader(lua)
            api=lua.execute(FAKE_RESOLVE);lua.globals().fixture=api;lua.globals().resolve=api.resolve
            lua.execute(EDIT_API+";fixture.media_frames='90';fixture.current=fixture.make_bootstrap('"+info['bootstrap_project_name']+"')")
            # Actual Win32/HMAC path must exercise all three metadata-only lists.
            for field in ['clips','folders','jobs']:
                self.assertEqual(lua.eval('fixture.bootstrap.'+field+'.__flags'),2097152)
                self.assertIsNone(lua.eval('fixture.bootstrap.'+field+'._flags'))
                self.assertIsNone(lua.eval('getmetatable(fixture.bootstrap.'+field+')'))
            self.assertEqual(lua.eval('fixture.current:GetTimelineCount()'),0)
            self.assertIsNone(lua.eval('fixture.current:GetCurrentTimeline()'))
            lua.globals().host_wait=time.sleep
            lua.execute('bmd={wait=function(seconds) host_wait(seconds) end}')
            session=lua.execute(Path(info['service_script']).read_text(encoding='utf-8'))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(run_validation,root/'edit-info.json',info['project_name'],info['bootstrap_project_name'])
                self.assertTrue(session.run(10,'Utility',10))
                report=future.result(timeout=3)
            self.assertEqual(report['result'],'PASS',report)
            self.assertEqual(report['verified']['end_frame'],60)
            self.assertFalse((Path(info['mailbox'])/'approval.txt').exists())
            self.assertTrue(Path(info['fixture']).is_file())
