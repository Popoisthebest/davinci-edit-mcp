"""Fixed real-protocol editing workflow against guarded simulated Resolve."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resolve_mcp.edit_validation import FIXTURE_SHA256, console_command, run_validation
from resolve_mcp.editing import Editor,prepare_media_root
from resolve_mcp.transport import atomic_write
from tests.edit_support import EditBridge
from tests.support import FileBridge


class EditValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.id='a'*32
        self.root=Path(self.temp.name)/('ResolveMCPEdit_'+self.id);self.root.mkdir(mode=0o700)
        self.editor=Editor(self.root/'mailbox',timeout=2)
        self.media=self.root/('ResolveMCP_TEST_MEDIA_'+self.id[:12]);prepare_media_root(self.editor,self.media)
        fixture=base64.b64decode((Path(__file__).parents[1]/'src/resolve_mcp/fixtures/portrait30.mp4.b64').read_bytes())
        self.assertEqual(hashlib.sha256(fixture).hexdigest(),FIXTURE_SHA256)
        self.fixture=self.media/'fixture.mp4';atomic_write(self.fixture,fixture)
        self.service=self.root/'EditService.lua';self.service.write_bytes(b'trusted service fixture')
        self.name='ResolveMCP_TEST_probe_'+self.id[:12]
        self.boot='ResolveMCP_BOOT_'+self.id
        self.info=self.root/'edit-info.json'
        command=console_command(self.service)
        atomic_write(self.root/'LuaConsoleCommand.txt',(command+'\n').encode('ascii'))
        self.info.write_text(json.dumps({'edit_validation_format':3,'run_id':self.id,'root':str(self.root),
            'console_command':command,'console_command_file':str(self.root/'LuaConsoleCommand.txt'),
            'transition_file':str(self.editor.root/'project-transition.txt'),
            'bootstrap_project_name':self.boot,
            'project_name':self.name,'mailbox':str(self.editor.root),'media_root':str(self.media),
            'fixture':str(self.fixture),'service_script':str(self.service),
            'service_sha256':hashlib.sha256(self.service.read_bytes()).hexdigest(),
            'result_file':str(self.root/'edit-result.json')}))

    def tearDown(self):self.temp.cleanup()

    def bridge(self,script=''):
        def factory(box,instance):
            self.live=EditBridge(box,instance)
            self.live.lua.execute("fixture.media_frames='90';fixture.current=fixture.make_bootstrap('"+self.boot+"');"+script)
            return self.live
        return FileBridge(self.editor,factory=factory)

    def run_validation(self,confirmation=None,bootstrap=None):
        return run_validation(self.info,confirmation or self.name,bootstrap or self.boot,startup_timeout=2)

    def test_whole_sequence_verifies_portrait_trim_placement_and_revokes_approval(self):
        with self.bridge("fixture.project_names={18,'existing',count=1}"):
            report=self.run_validation()
        self.assertEqual(report['result'],'PASS',report)
        self.assertEqual((report['verified']['width'],report['verified']['height'],report['verified']['fps']),(1080,1920,30))
        self.assertEqual((report['verified']['start_frame'],report['verified']['end_frame']),(0,60))
        self.assertFalse((self.editor.root/'approval.txt').exists())
        self.assertEqual(list(self.live.api.mutations.values()).count('CloseBootstrap'),1)
        self.assertEqual(report['project_transition_authentication'],'PASS')
        self.assertEqual(report['project_transition']['outcome'],'READY_TO_CREATE')
        self.assertFalse((self.editor.root/'bootstrap-approval.txt').exists())
        with self.assertRaises(FileExistsError):self.run_validation()

    def test_open_original_blocks_all_mutation_and_is_never_saved_or_closed(self):
        with self.bridge('fixture.current=fixture.protected_project'):
            report=self.run_validation()
        self.assertEqual(report['error_code'],'WRITE_DENIED')
        self.assertFalse(report['may_have_changes'])
        self.assertEqual(len(self.live.api.mutations),0)
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_append_failure_leaves_partial_project_and_does_not_retry_or_save(self):
        with self.bridge('fixture.bad_source=true'):
            report=self.run_validation()
        self.assertEqual((report['result'],report['failed_stage']),('FAIL','append_clip'))
        mutations=list(self.live.api.mutations.values())
        self.assertEqual(mutations.count('AppendToTimeline'),1)
        self.assertNotIn('SaveProject',mutations)
        self.assertTrue(report['may_have_changes'])
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_confirmation_and_fixture_integrity_fail_before_execution(self):
        with self.assertRaisesRegex(Exception,'Confirm the exact'):self.run_validation('wrong')
        with self.assertRaisesRegex(Exception,'Confirm the exact'):self.run_validation(bootstrap='wrong')
        self.assertFalse((self.root/'started.json').exists())
        self.fixture.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'integrity mismatch'):self.run_validation()
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_old_session_and_tampered_console_command_are_rejected_before_execution(self):
        original=json.loads(self.info.read_text())
        for updates in [{'edit_validation_format':2},{'console_command':'arbitrary code'}]:
            with self.subTest(updates=updates):
                self.info.write_text(json.dumps({**original,**updates}))
                with self.assertRaises(ValueError):self.run_validation()
                self.assertFalse((self.root/'started.json').exists())
                self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_existing_name_among_mixed_values_is_rejected_before_creation(self):
        with self.bridge('fixture.project_names={17,"'+self.name+'",count=1}'):
            report=self.run_validation()
        self.assertEqual(report['error_code'],'WRITE_DENIED')
        self.assertEqual(len(self.live.api.mutations),0)

    def test_nonempty_bootstrap_blocks_close_and_all_edits(self):
        for attribute,value in [('clips','{1}'),('folders','{1}'),('jobs','{1}')]:
            with self.subTest(attribute=attribute):
                (self.root/'started.json').unlink(missing_ok=True)
                for name in ['request.txt','response.txt']:(self.editor.root/name).unlink(missing_ok=True)
                with self.bridge('fixture.bootstrap.'+attribute+'='+value):report=self.run_validation()
                self.assertEqual(report['error_code'],'WRITE_DENIED',report)
                self.assertEqual(len(self.live.api.mutations),0)

    def test_project_switch_during_preflight_never_closes_original(self):
        with self.bridge('''fixture.manager.GetProjectListInCurrentFolder=function()
            fixture.current=fixture.protected_project;return {} end'''):
            report=self.run_validation()
        self.assertEqual(report['error_code'],'WRITE_DENIED',report)
        self.assertEqual(len(self.live.api.mutations),0)

    def test_unexpected_project_after_close_stops_before_create(self):
        with self.bridge('fixture.after_close=fixture.protected_project'):report=self.run_validation()
        self.assertEqual(report['error_code'],'WRITE_DENIED',report)
        self.assertEqual(list(self.live.api.mutations.values()),['CloseBootstrap'])
        self.assertEqual(report['project_transition']['outcome'],'DIFFERENT_PROJECT_ACTIVE')

    def test_bootstrap_revocation_during_enumeration_stops_before_close(self):
        with self.bridge():
            self.live.lua.globals().revoke_bootstrap=lambda:(self.editor.root/'bootstrap-approval.txt').unlink()
            self.live.lua.execute('fixture.manager.GetProjectListInCurrentFolder=function() revoke_bootstrap();return {} end')
            report=self.run_validation()
        self.assertEqual(report['error_code'],'WRITE_DENIED',report)
        self.assertEqual(len(self.live.api.mutations),0)

    def test_startup_timeout_never_grants_approval_or_publishes_rpc(self):
        report=run_validation(self.info,self.name,self.boot,startup_timeout=0.05)
        self.assertEqual(report['error_code'],'STARTUP_TIMEOUT')
        self.assertEqual(report['editing_test'],'NOT_RUN')
        for name in ['approval.txt','bootstrap-approval.txt','request.txt','start.txt']:
            self.assertFalse((self.editor.root/name).exists(),name)
