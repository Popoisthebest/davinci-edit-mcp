import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from resolve_mcp.editing import Editor,approve,approve_bootstrap,load_approval,prepare_media_root
from resolve_mcp.protocol import BridgeError,request,response
from resolve_mcp.transport import Mailbox,atomic_write
from tests.edit_support import EditBridge
from tests.support import FileBridge


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.box=Editor(self.root/'mailbox',timeout=1)
        self.media_root=self.root/'ResolveMCP_TEST_MEDIA_fixture'
        prepare_media_root(self.box,self.media_root)
        self.media=self.media_root/'fixture.mp4'
        self.media.write_bytes(b'fixture; not actual video')
        self.name='ResolveMCP_TEST_session'
        approve(self.box,self.name,self.media_root,self.name)
        self.bridge=EditBridge(self.box)

    def tearDown(self): self.temp.cleanup()

    def test_missing_approval_blocks_lua_and_python(self):
        (self.box.root/'approval.txt').unlink()
        for call in [lambda:self.box.call('create_test_project'),lambda:self.bridge.call('create_test_project')]:
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):call()
        self.assertEqual(len(self.bridge.api.mutations),0)

    def test_default_mailbox_cannot_edit_even_with_approval(self):
        readonly=Mailbox(self.box.root)
        with self.assertRaisesRegex(BridgeError,'OP_NOT_ALLOWED'): readonly.call('create_test_project')

    def test_exact_confirmation_and_protected_names(self):
        for name,confirmation in [('팩트체크_쇼츠_템플릿','팩트체크_쇼츠_템플릿'),(self.name,'yes')]:
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):approve(self.box,name,self.media_root,confirmation)

    def test_media_root_must_be_new_and_dedicated(self):
        for target in [self.media_root,self.root/'02_원본자료']:
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):prepare_media_root(self.box,target)
        self.assertFalse((self.root/'02_원본자료').exists())

    def test_marker_and_session_binding(self):
        atomic_write(self.media_root/'.resolve-mcp-test-media',b'not authenticated')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):load_approval(self.box)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(len(self.bridge.api.mutations),0)

    @unittest.skipIf(os.name=='nt','POSIX permission mode check')
    def test_shared_media_directory_rejected(self):
        self.media_root.chmod(0o777)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):load_approval(self.box)

    def test_cannot_create_while_original_project_is_open(self):
        self.bridge.api.current=self.bridge.api.protected_project
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(len(self.bridge.api.mutations),0)

    def bootstrap_approval(self):
        name='ResolveMCP_BOOT_'+'a'*32
        self.bridge.lua.execute("fixture.current=fixture.make_bootstrap('"+name+"')")
        self.box.bridge_id=self.bridge.instance
        approve_bootstrap(self.box,load_approval(self.box),name,self.bridge.call('current_project'))

    def test_bootstrap_accepts_empty_or_only_numeric_flags_in_all_three_lists(self):
        for expression in ['{}','{_flags=0}','{_flags=2097152}','{_flags=-2.5}',
                           '{__flags=0}','{__flags=2097152}','{__flags=-2.5}',
                           '{_flags=1,__flags=2097152}']:
            with self.subTest(expression=expression):
                self.bridge=EditBridge(self.box)
                self.bootstrap_approval()
                for field in ['clips','folders','jobs']:
                    self.bridge.lua.execute('fixture.bootstrap.'+field+'='+expression)
                result=self.bridge.call('create_test_project')
                self.assertEqual(result['name'],self.name)
                self.assertEqual(list(self.bridge.api.mutations.values()).count('CloseBootstrap'),1)

    def assert_bootstrap_lists_denied(self,expressions):
        for field in ['clips','folders','jobs']:
            for expression in expressions:
                with self.subTest(field=field,expression=expression):
                    self.bridge=EditBridge(self.box)
                    self.bootstrap_approval()
                    self.bridge.lua.execute('fixture.bootstrap.'+field+'='+expression)
                    with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):
                        self.bridge.call('create_test_project')
                    self.assertEqual(len(self.bridge.api.mutations),0)
                    self.assertEqual(self.bridge.api.current.uid,'bootstrap-unique-id')

    def test_bootstrap_flags_never_hide_real_sparse_or_named_items(self):
        for key in ['_flags','__flags']:
            self.assert_bootstrap_lists_denied([
                '{'+key+'=2097152,[1]={}}','{'+key+'=0,[9]={}}',
                '{'+key+'=0,[0]=false}','{'+key+'=0,render_job={}}',
            ])
        self.assert_bootstrap_lists_denied(['{_flags=0,__flags=0,[9]={}}'])

    def test_bootstrap_rejects_unknown_metadata_or_malformed_flags_in_each_list(self):
        for key in ['_flags','__flags']:
            self.assert_bootstrap_lists_denied([
                '{'+key+"='0'}",'{'+key+'=false}','{'+key+'={}}','{'+key+'=function() end}',
                '{'+key+'=math.huge}','{'+key+'=-math.huge}','{'+key+'=0/0}',
                '{'+key+'=0,_count=0}','{'+key+'=0,items={}}',
            ])
        self.assert_bootstrap_lists_denied([
            '{_FLAGS=0}','{___flags=0}','{__Flags=0}',
            "{_flags=0,__flags='0'}","{_flags='0',__flags=0}",
            '{_flags=0,__flags=math.huge}','{_flags=0,__flags=0,unexpected=0}',
        ])

    def test_bootstrap_rejects_non_table_and_metatable_list_structures(self):
        self.assert_bootstrap_lists_denied([
            'nil','false','0',"'empty'",'function() return {} end','ffi.new("int",0)',
            'setmetatable({_flags=0},{__index={hidden_item={}}})',
            'setmetatable({_flags=0,[1]={}},{__pairs=function() error("must not run") end})',
            'setmetatable({__flags=0},{})',
            'setmetatable({__flags=0,[9]={}},{__pairs=function() error("must not run") end})',
        ])

    def test_numeric_flags_do_not_relax_timeline_guards(self):
        for script in ['fixture.bootstrap.timelines=1',
                       'fixture.bootstrap.GetCurrentTimeline=function() return {} end']:
            with self.subTest(script=script):
                self.bridge=EditBridge(self.box)
                self.bootstrap_approval()
                self.bridge.lua.execute(script)
                with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
                self.assertEqual(len(self.bridge.api.mutations),0)

    def test_numeric_flags_do_not_hide_content_added_before_close(self):
        for field in ['clips','folders','jobs']:
            with self.subTest(field=field):
                self.bridge=EditBridge(self.box)
                self.bootstrap_approval()
                self.bridge.lua.execute('fixture.manager.GetProjectListInCurrentFolder=function() '
                    'fixture.bootstrap.'+field+'[9]={};return {} end')
                with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
                self.assertEqual(len(self.bridge.api.mutations),0)

    def test_bootstrap_grant_rejects_restart_reapproval_and_changed_identity(self):
        self.bootstrap_approval()
        for script in ["fixture.bootstrap.uid='another-id'", "fixture.bootstrap.name='another-name'"]:
            self.bridge.lua.execute(script)
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
            self.assertEqual(len(self.bridge.api.mutations),0)
        self.bootstrap_approval()
        restarted=EditBridge(self.box,'c'*32)
        restarted.lua.execute("fixture.current=fixture.make_bootstrap('ResolveMCP_BOOT_"+'a'*32+"')")
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):restarted.call('create_test_project')
        approve(self.box,self.name,self.media_root,self.name)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(len(self.bridge.api.mutations),0)

    def test_bootstrap_close_failure_cannot_be_retried_or_create_project(self):
        self.bootstrap_approval()
        self.bridge.api.fail_close=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.bridge.call('create_test_project')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(list(self.bridge.api.mutations.values()),['CloseBootstrap'])

    def test_bootstrap_approval_tampering_cannot_close_project(self):
        self.bootstrap_approval()
        path=self.box.root/'bootstrap-approval.txt'
        atomic_write(path,path.read_bytes().replace(b'BOOTSTRAP',b'bootSTRAP'))
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(len(self.bridge.api.mutations),0)

    def test_cannot_reuse_existing_test_project_name(self):
        self.bridge.api.project_names[3]=self.name
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        self.assertEqual(len(self.bridge.api.mutations),0)

    def test_create_test_project_and_scope(self):
        result=self.bridge.call('create_test_project')
        self.assertEqual(result['name'],self.name)
        self.assertTrue(result['project_id'].startswith('new-project-'))
        self.assertEqual(self.bridge.api.protected_project.GetName(),'테스트_프로젝트')
        self.assertEqual(self.bridge.api.protected_project.GetTimelineCount(),1)

    def test_project_switch_blocks_every_edit(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.current=self.bridge.api.protected_project
        before=len(self.bridge.api.mutations)
        for operation,kwargs in [('append_clip',params),('create_bin',{'name':'ResolveMCP_TEST_BIN_other'}),('save_test_project',{})]:
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call(operation,**kwargs)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_revocation_and_policy_replacement_block_existing_state(self):
        self.bridge.call('create_test_project')
        approve(self.box,self.name,self.media_root,self.name)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('save_test_project')
        (self.box.root/'approval.txt').unlink()
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('save_test_project')

    def test_signed_but_expired_approval(self):
        from resolve_mcp.protocol import pack
        approval=load_approval(self.box)
        packet=pack(self.box.key,['RMC3',approval.identifier,str(int(time.time())-1),self.name.encode().hex(),str(self.media_root).encode().hex()])
        atomic_write(self.box.root/'approval.txt',packet)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):load_approval(self.box)

    def test_tampered_approval(self):
        path=self.box.root/'approval.txt'
        data=path.read_bytes().replace(self.name.encode().hex().encode(),b'0'*len(self.name.encode().hex()))
        atomic_write(path,data)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('create_test_project')

    def test_restart_does_not_adopt_existing_project(self):
        self.bridge.call('create_test_project')
        restarted=EditBridge(self.box)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):restarted.call('save_test_project')

    def test_import_outside_root_blocked_on_both_sides(self):
        self.bridge.call('create_test_project')
        bin_id=self.bridge.call('create_bin',name='ResolveMCP_TEST_BIN_fixture')['bin_id']
        original=self.root/'original.mp4';original.write_bytes(b'original')
        for call in [lambda:self.box.call('import_media',bin_id=bin_id,path=str(original)),
                     lambda:self.bridge.call('import_media',bin_id=bin_id,path=str(original))]:
            with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):call()
        self.assertEqual(original.read_bytes(),b'original')
        self.assertNotIn('ImportMedia',list(self.bridge.api.mutations.values()))

    def test_hardlinked_media_rejected(self):
        linked=self.media_root/'linked.mp4'
        try:os.link(self.media,linked)
        except OSError:self.skipTest('Hardlinks unavailable')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.box.call('import_media',bin_id='x',path=str(linked))
        self.bridge.call('create_test_project')
        bin_id=self.bridge.call('create_bin',name='ResolveMCP_TEST_BIN_fixture')['bin_id']
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('import_media',bin_id=bin_id,path=str(linked))

    def test_unknown_bin_rejected_before_import(self):
        self.bridge.call('create_test_project')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('import_media',bin_id='original-bin',path=str(self.media))

    def test_signed_rpc_cannot_import_an_executable(self):
        self.bridge.call('create_test_project')
        bin_id=self.bridge.call('create_bin',name='ResolveMCP_TEST_BIN_fixture')['bin_id']
        executable=self.media_root/'fixture.exe';executable.write_bytes(b'disposable data')
        before=len(self.bridge.api.mutations)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):
            self.bridge.call('import_media',bin_id=bin_id,path=str(executable))
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_relinked_import_is_rejected_before_append(self):
        params=self.bridge.setup_project(self.media)
        relinked=self.media_root/'other.mp4';relinked.write_bytes(b'other fixture')
        self.bridge.state.media[params['media_id']].path=str(relinked)
        before=len(self.bridge.api.mutations)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**params)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_removed_timeline_is_rejected_without_activation(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.current.timelines=self.bridge.lua.table()
        before=len(self.bridge.api.mutations)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('plan_append',**params)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_changed_timeline_origin_is_rejected(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.state.timelines[params['timeline_id']].start_frame=108000
        before=len(self.bridge.api.mutations)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**params)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_timeline_format_and_duplicate(self):
        params=self.bridge.setup_project(self.media)
        timeline=self.bridge.state.timelines[params['timeline_id']]
        self.assertEqual(dict(timeline.settings),{'useCustomSettings':'1','timelineResolutionWidth':'1080','timelineResolutionHeight':'1920','timelineFrameRate':'30'})
        result=self.bridge.call('duplicate_timeline',timeline_id=params['timeline_id'],name='ResolveMCP_TEST_TL_copy')
        self.assertNotEqual(result['timeline_id'],params['timeline_id'])

    def test_original_timeline_cannot_be_duplicated(self):
        self.bridge.call('create_test_project')
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('duplicate_timeline',timeline_id='original',name='ResolveMCP_TEST_TL_copy')

    def test_setting_failure_is_reported(self):
        self.bridge.call('create_test_project')
        self.bridge.api.fail_setting=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.bridge.call('create_timeline',name='ResolveMCP_TEST_TL_fail')

    def test_dry_run_does_not_mutate_or_activate_timeline(self):
        params=self.bridge.setup_project(self.media)
        before=len(self.bridge.api.mutations)
        result=self.bridge.call('plan_append',**params)
        self.assertTrue(result['dry_run']);self.assertEqual(result['duration_frames'],30)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_exact_half_open_source_frames_and_placement(self):
        params=self.bridge.setup_project(self.media)
        params.update(source_in=3,source_out=4,record_frame=77)
        result=self.bridge.call('append_clip',**params)
        self.assertEqual(result['duration_frames'],1)
        self.assertEqual(result['start_frame'],77);self.assertEqual(result['end_frame'],78)
        self.assertEqual(self.bridge.api.last_append.startFrame,3)
        self.assertEqual(self.bridge.api.last_append.endFrame,3)
        self.assertEqual((result['source_in'],result['source_out']),(3,4))

    def test_invalid_frames_indices_and_boolean_rejected(self):
        params=self.bridge.setup_project(self.media)
        for update in [{'source_in':-1},{'source_in':30},{'source_out':301},{'track_index':0},{'track_index':2},
                       {'media_type':3},{'record_frame':-1},{'source_out':True},{'record_frame':2147483647}]:
            with self.subTest(update=update):
                with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**{**params,**update})
        self.assertNotIn('AppendToTimeline',list(self.bridge.api.mutations.values()))

    def test_mismatched_fps_rejected(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.media_fps='29.97'
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**params)

    def test_invalid_source_frame_counts_are_rejected(self):
        params=self.bridge.setup_project(self.media)
        before=len(self.bridge.api.mutations)
        for frames in ['0','-1','300.5','inf','2147483648','unknown']:
            with self.subTest(frames=frames):
                self.bridge.api.media_frames=frames
                with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**params)
        self.assertEqual(len(self.bridge.api.mutations),before)

    def test_overlap_rejected_without_second_append(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.call('append_clip',**params)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.bridge.call('append_clip',**params)
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),1)

    def test_explicit_track_and_audio_routing(self):
        params=self.bridge.setup_project(self.media)
        added=self.bridge.call('add_track',timeline_id=params['timeline_id'],track_type='audio')
        self.assertEqual(added['track_index'],2)
        result=self.bridge.call('append_clip',**{**params,'media_type':2,'track_index':2})
        self.assertEqual(result['track_type'],'audio')

    def test_readback_failure_does_not_retry(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.bad_append=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.bridge.call('append_clip',**params)
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),1)

    def test_source_trim_readback_failure_does_not_retry(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.bad_source=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.bridge.call('append_clip',**params)
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),1)

    def test_target_track_must_match_media_and_source_exactly(self):
        params=self.bridge.setup_project(self.media)
        for index,flag in enumerate(['bad_track_media','bad_track_source','duplicate_track_item']):
            with self.subTest(flag=flag):
                self.bridge.api[flag]=True
                with self.assertRaisesRegex(BridgeError,'API_ERROR'):
                    self.bridge.call('append_clip',**{**params,'record_frame':index*100})
                self.bridge.api[flag]=False
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),3)

    def test_failed_append_return_preserves_partial_edit_for_inspection(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.api.fail_append_return=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.bridge.call('append_clip',**params)
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),1)
        result=self.bridge.call('timeline_items')
        item=result['tracks'][0]['items'][0]
        self.assertEqual(item['media_id'],params['media_id'])
        self.assertEqual((item['left_offset_frames'],item['right_offset_frames']),(0,270))

    def test_duplicate_request_does_not_append_twice(self):
        params=self.bridge.setup_project(self.media)
        rid=secrets.token_hex(16)
        packet=request(self.box.key,rid,self.bridge.instance,'append_clip',params,5)
        first=self.bridge.process(packet)
        self.assertEqual(first,self.bridge.process(packet))
        response(self.box.key,first,rid,self.bridge.instance)
        self.assertEqual(list(self.bridge.api.mutations.values()).count('AppendToTimeline'),1)

    def test_missing_api_and_no_destructive_operations(self):
        params=self.bridge.setup_project(self.media)
        self.bridge.state.timelines[params['timeline_id']].AddTrack=None
        with self.assertRaisesRegex(BridgeError,'UNSUPPORTED_API'):self.bridge.call('add_track',timeline_id=params['timeline_id'],track_type='video')
        for operation in ['delete_media','delete_project','delete_clips','execute_lua']:
            with self.assertRaisesRegex(BridgeError,'OP_NOT_ALLOWED'):self.bridge.call(operation)

    def test_authenticated_file_roundtrip_and_audit(self):
        with FileBridge(self.box,factory=EditBridge):
            self.box.call('create_test_project')
            self.assertTrue(self.box.call('save_test_project')['saved'])
        records=[json.loads(line) for line in (self.box.root/'audit.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records],['requested','completed','requested','completed'])
        self.assertNotIn(self.box.key.hex(),json.dumps(records))

    def test_timed_out_write_is_not_repeated_and_can_be_inspected(self):
        self.box.timeout=0.05
        # Give the packet a deterministic one-second TTL while the client waits
        # only 50ms. Otherwise wall-clock rounding can expire it before dispatch.
        def valid_packet(key,rid,instance,op,params,timeout):
            return request(key,rid,instance,op,params,max(timeout,1))
        with patch('resolve_mcp.transport.request',side_effect=valid_packet), \
                FileBridge(self.box,delay=0.15,factory=EditBridge) as bridge:
            self.box.bridge_id=bridge.instance
            with self.assertRaisesRegex(BridgeError,'TIMEOUT'):self.box.call('create_test_project')
            self.box.timeout=1
            self.assertEqual(self.box.call('current_project')['name'],self.name)
            self.assertEqual(len(bridge.requests),2)  # One write, then one explicit read.
        records=[json.loads(line) for line in (self.box.root/'audit.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records],['requested','TIMEOUT'])
