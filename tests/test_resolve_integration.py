"""Explicit opt-in checks; never run edits or import media."""
import os
import unittest

from resolve_mcp.transport import Mailbox


@unittest.skipUnless(os.name=='nt' and os.environ.get('RESOLVE_MCP_INTEGRATION')=='1',
                     'Requires Windows + running Resolve + explicit RESOLVE_MCP_INTEGRATION=1')
class RealResolveTests(unittest.TestCase):
    def test_live_read_only_queries(self):
        mailbox=Mailbox()
        for operation in ['ping','current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items']:
            with self.subTest(operation=operation):
                self.assertIsInstance(mailbox.call(operation),dict)


@unittest.skipUnless(os.name=='nt' and os.environ.get('RESOLVE_MCP_EDIT_INTEGRATION')=='1',
                     'Requires Windows + Resolve + local approval + explicit edit integration opt-in')
class RealResolveEditingTests(unittest.TestCase):
    def test_fresh_project_exact_frame_append(self):
        from resolve_mcp.editing import Editor,load_approval
        editor=Editor()
        approval=load_approval(editor)
        # A disposable, copied 30fps fixture is mandatory. No original path is accepted.
        fixture=approval.media_root/'fixture.mp4'
        self.assertTrue(fixture.is_file(),'Copy a 30fps fixture.mp4 into the approved test media root')
        editor.call('create_test_project')
        bin_id=editor.call('create_bin',name='ResolveMCP_TEST_BIN_integration')['bin_id']
        media_id=editor.call('import_media',bin_id=bin_id,path=str(fixture))['media_id']
        timeline_id=editor.call('create_timeline',name='ResolveMCP_TEST_TL_integration')['timeline_id']
        params=dict(timeline_id=timeline_id,media_id=media_id,media_type=1,track_index=1,record_frame=0,source_in=0,source_out=30)
        self.assertTrue(editor.call('plan_append',**params)['dry_run'])
        result=editor.call('append_clip',**params)
        self.assertEqual((result['start_frame'],result['end_frame']),(0,30))
        track=editor.call('add_track',timeline_id=timeline_id,track_type='video')['track_index']
        single={**params,'track_index':track,'record_frame':77,'source_in':3,'source_out':4}
        self.assertEqual(editor.call('append_clip',**single)['duration_frames'],1)
        readback=editor.call('timeline_items')
        items=next(t['items'] for t in readback['tracks'] if t['type']=='video' and t['index']==track)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['media_id'],media_id)
        self.assertEqual((items[0]['start_frame'],items[0]['end_frame'],items[0]['left_offset_frames']),(77,78,3))
        duplicate=editor.call('duplicate_timeline',timeline_id=timeline_id,name='ResolveMCP_TEST_TL_integration_copy')
        self.assertNotEqual(duplicate['timeline_id'],timeline_id)
        self.assertTrue(editor.call('save_test_project')['saved'])
