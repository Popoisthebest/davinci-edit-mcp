"""Fixed real-protocol editing workflow against guarded simulated Resolve."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resolve_mcp.edit_validation import FIXTURE_SHA256, run_validation
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
        self.info=self.root/'edit-info.json'
        self.info.write_text(json.dumps({'edit_validation_format':1,'run_id':self.id,'root':str(self.root),
            'project_name':self.name,'mailbox':str(self.editor.root),'media_root':str(self.media),
            'fixture':str(self.fixture),'service_script':str(self.service),
            'service_sha256':hashlib.sha256(self.service.read_bytes()).hexdigest(),
            'result_file':str(self.root/'edit-result.json')}))

    def tearDown(self):self.temp.cleanup()

    def bridge(self,script=''):
        def factory(box,instance):
            self.live=EditBridge(box,instance)
            self.live.lua.execute("fixture.media_frames='90';"+script)
            return self.live
        return FileBridge(self.editor,factory=factory)

    def test_whole_sequence_verifies_portrait_trim_placement_and_revokes_approval(self):
        with self.bridge("fixture.project_names={18,'existing',count=1}"):
            report=run_validation(self.info,self.name)
        self.assertEqual(report['result'],'PASS',report)
        self.assertEqual((report['verified']['width'],report['verified']['height'],report['verified']['fps']),(1080,1920,30))
        self.assertEqual((report['verified']['start_frame'],report['verified']['end_frame']),(0,60))
        self.assertFalse((self.editor.root/'approval.txt').exists())
        with self.assertRaises(FileExistsError):run_validation(self.info,self.name)

    def test_open_original_blocks_all_mutation_and_is_never_saved_or_closed(self):
        with self.bridge('fixture.current=fixture.protected_project'):
            report=run_validation(self.info,self.name)
        self.assertEqual(report['error_code'],'WRITE_DENIED')
        self.assertFalse(report['may_have_changes'])
        self.assertEqual(len(self.live.api.mutations),0)
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_append_failure_leaves_partial_project_and_does_not_retry_or_save(self):
        with self.bridge('fixture.bad_source=true'):
            report=run_validation(self.info,self.name)
        self.assertEqual((report['result'],report['failed_stage']),('FAIL','append_clip'))
        mutations=list(self.live.api.mutations.values())
        self.assertEqual(mutations.count('AppendToTimeline'),1)
        self.assertNotIn('SaveProject',mutations)
        self.assertTrue(report['may_have_changes'])
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_confirmation_and_fixture_integrity_fail_before_execution(self):
        with self.assertRaisesRegex(Exception,'Confirm the exact'):run_validation(self.info,'wrong')
        self.assertFalse((self.root/'started.json').exists())
        self.fixture.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'integrity mismatch'):run_validation(self.info,self.name)
        self.assertFalse((self.editor.root/'approval.txt').exists())

    def test_existing_name_among_mixed_values_is_rejected_before_creation(self):
        with self.bridge('fixture.project_names={17,"'+self.name+'",count=1}'):
            report=run_validation(self.info,self.name)
        self.assertEqual(report['error_code'],'WRITE_DENIED')
        self.assertEqual(len(self.live.api.mutations),0)
