"""Authenticated observations must confirm absence, never infer it from True."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resolve_mcp.editing import Editor, approve, approve_bootstrap, prepare_media_root
from resolve_mcp.project_transition import read_transition
from resolve_mcp.protocol import BridgeError, pack
from resolve_mcp.transport import atomic_write
from tests.edit_support import EditBridge


class ProjectTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.box=Editor(self.root/'mailbox')
        media=self.root/'ResolveMCP_TEST_MEDIA_close';prepare_media_root(self.box,media)
        self.grant=approve(self.box,'ResolveMCP_TEST_close',media,'ResolveMCP_TEST_close')
        self.bridge=EditBridge(self.box);self.box.bridge_id=self.bridge.instance
        self.bridge.lua.execute("fixture.current=fixture.make_bootstrap('ResolveMCP_BOOT_"+'a'*32+"')")
        approve_bootstrap(self.box,self.grant,'ResolveMCP_BOOT_'+'a'*32,self.bridge.call('current_project'))

    def tearDown(self):self.temp.cleanup()

    def trace(self):return read_transition(self.box,self.grant.identifier)
    def script(self,text):self.bridge.lua.execute(text)
    def create(self):return self.bridge.call('create_test_project')
    def only_closed(self):self.assertEqual(list(self.bridge.api.mutations.values()),['CloseBootstrap'])

    def test_synchronous_close_records_names_ids_true_and_two_absent_samples(self):
        self.create();trace=self.trace()
        self.assertEqual(trace['close_call_count'],1)
        self.assertEqual(trace['close_project'],{'ok':True,'value_type':'boolean','value':True})
        self.assertEqual(trace['events'][0]['get_unique_id']['value'],'bootstrap-unique-id')
        self.assertEqual(trace['events'][0]['get_name']['value'],'ResolveMCP_BOOT_'+'a'*32)
        self.assertEqual([r['kind'] for r in trace['events'][-3:]],['NO_CURRENT_PROJECT']*3)
        self.assertEqual(trace['outcome'],'READY_TO_CREATE')

    def test_delayed_close_only_polls_and_proceeds_after_confirmed_absence(self):
        self.script('''fixture.close_hook=function() return true end
            fixture.on_wait=function() if fixture.elapsed>=0.15 then fixture.current=nil end end''')
        self.create();trace=self.trace()
        self.assertTrue(any(r['kind']=='SAME_BOOTSTRAP_REFERENCE' for r in trace['events'][1:]))
        self.assertEqual(trace['outcome'],'READY_TO_CREATE')
        self.assertEqual(list(self.bridge.api.mutations.values()).count('CloseBootstrap'),1)

    def test_new_wrapper_with_same_identity_is_observed_without_adoption(self):
        self.script('''fixture.close_hook=function(p)
            local proxy={};for key,value in pairs(p) do proxy[key]=value end
            fixture.current=proxy;return true end
            fixture.on_wait=function() fixture.current=nil end''')
        self.create()
        self.assertEqual(self.trace()['events'][1]['kind'],'SAME_BOOTSTRAP_IDENTITY')

    def test_unreadable_same_reference_is_only_a_candidate_until_nil(self):
        self.script('''fixture.close_hook=function(p)
            p.GetName=function() error('private SDK error') end
            p.GetUniqueId=function() error('private SDK error') end
            return true end
            fixture.on_wait=function() fixture.current=nil end''')
        self.create();trace=self.trace()
        self.assertEqual(trace['events'][1]['kind'],'STALE_REFERENCE_CANDIDATE')
        self.assertNotIn('private SDK error',json.dumps(trace))

    def test_persistent_reference_times_out_and_cannot_be_closed_again(self):
        self.script('fixture.close_hook=function() return true end')
        with self.assertRaisesRegex(BridgeError,'CLOSE_PENDING_TIMEOUT'):self.create()
        trace=self.trace();self.assertLessEqual(len(trace['events']),105)
        self.assertGreaterEqual(self.bridge.api.elapsed,5)
        self.assertLess(self.bridge.api.elapsed,5.2)
        with self.assertRaisesRegex(BridgeError,'WRITE_DENIED'):self.create()
        self.only_closed()

    def test_persistent_unreadable_reference_cannot_count_as_closed(self):
        self.script('''fixture.close_hook=function(p)
            p.GetName=function() return nil end;p.GetUniqueId=function() return nil end;return true end''')
        with self.assertRaisesRegex(BridgeError,'STALE_REFERENCE_UNRESOLVED'):self.create()
        self.only_closed()

    def test_autoactivated_project_is_recorded_and_never_closed(self):
        self.script('fixture.after_close=fixture.protected_project')
        with self.assertRaisesRegex(BridgeError,'DIFFERENT_PROJECT_ACTIVE'):self.create()
        trace=self.trace();row=trace['events'][-1]
        self.assertEqual(row['get_unique_id']['value'],'protected-project-id')
        self.assertEqual(row['get_name']['value'],'테스트_프로젝트')
        self.only_closed()

    def test_one_nil_followed_by_autoactivation_is_not_close_completion(self):
        self.script('fixture.on_wait=function() fixture.current=fixture.protected_project end')
        with self.assertRaisesRegex(BridgeError,'DIFFERENT_PROJECT_ACTIVE'):self.create()
        self.only_closed()

    def test_activation_after_confirmation_is_caught_immediately_before_create(self):
        self.script('''fixture.close_hook=function()
            local calls=0;fixture.manager.GetCurrentProject=function()
                calls=calls+1;if calls>=3 then return fixture.protected_project end end
            return true end''')
        with self.assertRaisesRegex(BridgeError,'PROJECT_ACTIVATED_BEFORE_CREATE'):self.create()
        self.assertEqual(self.trace()['outcome'],'PROJECT_ACTIVATED_BEFORE_CREATE')
        self.only_closed()

    def test_false_close_return_is_logged_and_never_retried(self):
        self.bridge.api.fail_close=True
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.create()
        self.assertEqual(self.trace()['close_project']['value'],False)
        self.assertEqual(self.trace()['outcome'],'CLOSE_RETURN_NOT_TRUE')
        self.only_closed()

    def test_api_failure_is_recorded_without_raw_error_disclosure(self):
        self.script('''fixture.close_hook=function()
            fixture.manager.GetCurrentProject=function() error('private error text') end;return true end''')
        with self.assertRaisesRegex(BridgeError,'CURRENT_PROJECT_API_ERROR'):self.create()
        self.assertNotIn('private error text',json.dumps(self.trace()))
        self.only_closed()

    def test_revocation_while_waiting_blocks_creation(self):
        self.script('fixture.close_hook=function() return true end;fixture.on_wait=function() revoke() end')
        self.bridge.lua.globals().revoke=lambda:(self.box.root/'bootstrap-approval.txt').unlink()
        with self.assertRaisesRegex(BridgeError,'APPROVAL_OR_SESSION_REVOKED'):self.create()
        self.only_closed()

    def test_session_rotation_while_waiting_blocks_creation(self):
        self.script('fixture.close_hook=function() return true end;fixture.on_wait=function() rotate() end')
        self.bridge.lua.globals().rotate=lambda:atomic_write(self.box.root/'session.key',b'0'*64)
        with self.assertRaisesRegex(BridgeError,'APPROVAL_OR_SESSION_REVOKED'):self.create()
        self.only_closed()

    def test_diagnostic_write_failure_prevents_close(self):
        def fail(*args):raise OSError('private filesystem details')
        self.bridge.lua.globals().adapter_write=fail
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.create()
        self.assertEqual(len(self.bridge.api.mutations),0)

    def test_post_close_write_failure_preserves_intent_as_unknown_and_never_creates(self):
        from resolve_mcp.transport import atomic_write
        def write(path,data):
            if len(self.bridge.api.mutations):raise OSError('write failed after call')
            atomic_write(Path(path.replace('\\','/')),data.encode('utf-8'))
        self.bridge.lua.globals().adapter_write=write
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.create()
        self.assertEqual(self.trace()['outcome'],'CALLING_CLOSE')
        self.only_closed()

    def test_transition_authentication_and_bridge_approval_binding(self):
        self.create();path=self.box.root/'project-transition.txt'
        original=path.read_bytes();atomic_write(path,original.replace(b'PROJECT_TRANSITION',b'PROJECT_TRANsITION'))
        with self.assertRaisesRegex(BridgeError,'AUTH_FAILED'):self.trace()
        for instance,grant in [('c'*32,self.grant.identifier),(self.bridge.instance,'d'*32)]:
            atomic_write(path,pack(self.box.key,['RMC3','PROJECT_TRANSITION',instance,grant,b'{}'.hex()]))
            with self.assertRaisesRegex(BridgeError,'STALE_TRANSITION'):self.trace()
