import hashlib
import hmac
import secrets
import unittest

from resolve_mcp.protocol import BridgeError, encode_params, pack, request, response
from tests.support import LuaBridge, BRIDGE


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(32))
        self.bridge = LuaBridge(self.key)

    def call(self, op='ping', params=None, rid=None, now=100, instance=None):
        rid = rid or secrets.token_hex(16)
        raw = request(self.key, rid, instance, op, params or {}, 5, now=now)
        output = self.bridge.process(raw, now)
        return response(self.key, output, rid, instance)[1]

    def test_sha_and_rfc_hmac_vectors(self):
        for data in [b'', b'abc', b'a' * 1000, bytes(range(256))]:
            with self.subTest(size=len(data)):
                self.assertEqual(self.bridge.crypto.sha256(data), hashlib.sha256(data).hexdigest())
                self.assertEqual(self.bridge.crypto.hmac(b'key', data), hmac.new(b'key', data, 'sha256').hexdigest())
        self.assertEqual(self.bridge.crypto.hmac(b'\x0b'*20, b'Hi There'),
                         'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7')

    def test_all_lua_modules_compile(self):
        compile_only=self.bridge.lua.eval('function(text) local f,err=loadstring(text); assert(f,err); return true end')
        for path in BRIDGE.glob('*.lua'):
            with self.subTest(file=path.name):self.assertTrue(compile_only(path.read_text(encoding='utf-8')))

    def test_baseline_ping(self):
        result = self.call()
        self.assertTrue(result['connected'])
        self.assertFalse(result['writes_enabled'])
        self.assertIn('MOCK', result['resolve_version'])

    def test_no_project(self):
        self.bridge.api.manager.GetCurrentProject = self.bridge.lua.eval('function() return nil end')
        self.assertEqual(self.call('current_project', instance=self.bridge.instance), {'project_open': False})

    def test_optional_ids_and_source_offsets(self):
        self.bridge.lua.execute('''
            local p = fixture.project
            p.GetUniqueId = function() return 'project-id' end
            fixture.timeline.GetUniqueId = function() return 'timeline-id' end
            local item = fixture.timeline:GetItemListInTrack('video',1)[1]
            item.GetUniqueId = function() return 'item-id' end
            item.GetMediaPoolItem = function() return fixture.clip end
            item.GetLeftOffset = function() return 7 end
            item.GetRightOffset = function() return 53 end
        ''')
        self.assertEqual(self.call('current_project',instance=self.bridge.instance)['project_id'],'project-id')
        result = self.call('timeline_items',instance=self.bridge.instance)
        self.assertEqual(result['timeline_id'],'timeline-id')
        item = result['tracks'][0]['items'][0]
        self.assertEqual((item['item_id'],item['media_id']),('item-id','media-1'))
        self.assertEqual((item['left_offset_frames'],item['right_offset_frames']),(7,53))
        self.assertNotIn('unavailable_fields',item)

    def test_unavailable_metadata_keeps_baseline_reads_working(self):
        result = self.call('timeline_items',instance=self.bridge.instance)
        self.assertEqual(result['unavailable_fields'],['timeline_id'])
        item = result['tracks'][0]['items'][0]
        self.assertEqual(item['name'],'클립')
        self.assertIn('media_id',item['unavailable_fields'])
        self.assertIn('left_offset_frames',item['unavailable_fields'])

    def test_no_timeline(self):
        self.bridge.api.project.GetCurrentTimeline = self.bridge.lua.eval('function() return nil end')
        self.assertEqual(self.call('current_timeline', instance=self.bridge.instance), {'timeline_open': False})

    def test_all_read_operations(self):
        for op in ['current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items']:
            with self.subTest(op=op):
                self.assertIsInstance(self.call(op, instance=self.bridge.instance), dict)
        self.assertEqual(self.call('current_project', instance=self.bridge.instance)['name'], '테스트_프로젝트')

    def test_no_project_switch_or_setters(self):
        # Any unexpected API call is absent and therefore fails this real Lua handler check.
        self.call('projects', instance=self.bridge.instance)
        self.call('timelines', instance=self.bridge.instance)
        self.call('media_pool', instance=self.bridge.instance)

    def test_unsupported_api_is_explicit(self):
        self.bridge.api.project.GetCurrentRenderFormatAndCodec = None
        with self.assertRaisesRegex(BridgeError, 'UNSUPPORTED_API'):
            self.call('render_settings', instance=self.bridge.instance)

    def test_api_failure(self):
        self.bridge.api.resolve.GetVersionString = self.bridge.lua.eval('function() error("device failure") end')
        with self.assertRaisesRegex(BridgeError, 'API_ERROR'):
            self.call()

    def test_bad_authentication_does_not_dispatch(self):
        raw = request(b'x'*32, 'a'*32, None, 'ping', {}, 5, now=100)
        self.assertIsNone(self.bridge.process(raw,100))

    def test_tampered_operation_does_not_dispatch(self):
        raw = request(self.key,'a'*32,None,'ping',{},5,now=100).replace(b'ping',b'stop')
        self.assertIsNone(self.bridge.process(raw,100))
        self.assertFalse(self.bridge.core.stopped)

    def test_malicious_lua_is_only_data(self):
        self.bridge.lua.execute('loadfile = function() error("must never execute") end; dofile = loadfile')
        with self.assertRaisesRegex(BridgeError,'INVALID_REQUEST'):
            self.call(params={'data':'return os.execute("anything")'})
        self.assertTrue(self.call()['connected'])

    def test_signed_unknown_operation(self):
        with self.assertRaisesRegex(BridgeError,'OP_NOT_ALLOWED'):
            self.call('delete_project',instance=self.bridge.instance)

    def test_expired_and_future_requests(self):
        for now in [106,0]:
            with self.subTest(now=now):
                rid='a'*32
                output=self.bridge.process(request(self.key,rid,None,'ping',{},5,now=100),now)
                with self.assertRaisesRegex(BridgeError,'EXPIRED'):
                    response(self.key,output,rid,None)

    def test_duplicate_replay_returns_same_response(self):
        rid='a'*32
        raw=request(self.key,rid,None,'ping',{},5,now=100)
        first=self.bridge.process(raw,100)
        self.bridge.api.resolve.GetVersionString=self.bridge.lua.eval('function() error("must not repeat") end')
        self.assertEqual(self.bridge.process(raw,101),first)

    def test_reused_identifier_different_data(self):
        rid='a'*32
        self.call(rid=rid)
        output=self.bridge.process(request(self.key,rid,self.bridge.instance,'projects',{},5,now=100),100)
        with self.assertRaisesRegex(BridgeError,'DUPLICATE_ID'):
            response(self.key,output,rid,self.bridge.instance)

    def test_wrong_instance(self):
        with self.assertRaisesRegex(BridgeError,'BRIDGE_RESTARTED'):
            self.call('projects',instance='c'*32)

    def test_non_ping_requires_handshake(self):
        with self.assertRaisesRegex(BridgeError,'BRIDGE_RESTARTED'):
            self.call('projects')

    def test_stop(self):
        self.assertEqual(self.call('stop',instance=self.bridge.instance),{'stopped':True})
        self.assertTrue(self.bridge.core.stopped)

    def test_response_auth_and_stale_id(self):
        rid='a'*32
        result=self.bridge.process(request(self.key,rid,None,'ping',{},5,now=100),100)
        with self.assertRaisesRegex(BridgeError,'AUTH_FAILED'):
            response(b'x'*32,result,rid,None)
        with self.assertRaisesRegex(BridgeError,'STALE_RESPONSE'):
            response(self.key,result,'c'*32,None)

    def test_packet_and_scalar_limits(self):
        self.assertIsNone(self.bridge.process(b'x'*(1024*1024+1),100))
        for params in [{'x':[]},{'x':1.5},{'x':'\0'},{'x':2**53},{'x':'a'*32769}]:
            with self.subTest(params_type=type(params['x'])):
                with self.assertRaises(ValueError): encode_params(params)

    def test_codec_unicode_types_and_delimiters(self):
        params={'s':'한글\n|:="','b':False,'i':-12}
        output=self.bridge.codec.params(encode_params(params),self.bridge.crypto)
        self.assertEqual(dict(output),params)

    def test_response_row_limit(self):
        self.bridge.api.project.GetTimelineCount=self.bridge.lua.eval('function() return 1001 end')
        with self.assertRaisesRegex(BridgeError,'API_ERROR'):
            self.call('timelines',instance=self.bridge.instance)
