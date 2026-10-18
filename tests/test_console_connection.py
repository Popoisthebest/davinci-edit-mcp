"""Manual Console transport uses the real protocol, cache and read handlers."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lupa.luajit21 import LuaError
from lupa.lua51 import LuaRuntime as Lua51Runtime, LuaError as Lua51Error
from resolve_mcp.bundle import BRIDGE, console_bundle, utility_path_check
from resolve_mcp.console_connection import inspect_connection, load_connection, ping_connection
from resolve_mcp.protocol import BridgeError, pack, request, response
from tests.support import LuaBridge


class ConsoleSessionTests(unittest.TestCase):
    def setUp(self):
        self.key=b'k'*32;self.root='C:\\isolated';self.id='b'*32
        self.fixture=LuaBridge(self.key);self.lua=self.fixture.lua
        self.lua.globals().resolve=self.fixture.api.resolve
        self.lua.execute("ffi.os='Windows';os.time=function() return 100 end;bmd=nil")
        self.files={self.root+'\\session.key':self.key.hex()}
        self.writes=[];self.releases=[];self.busy=False;self.fail_write=False
        def write(path,data):
            if self.fail_write:raise RuntimeError('injected write failure')
            self.files[path]=data;self.writes.append(path)
        self.native=self.lua.table(read=lambda path:self.files.get(path),write=write,
            random_hex=lambda:self.id,
            acquire=lambda name:None if self.busy else lambda:self.releases.append(name))
        factory=self.lua.execute('return function(...)\n'+(BRIDGE/'console.lua').read_text()+'\nend')
        module=factory(lambda name:self.native if name=='native' else self.fixture.modules(name))
        self.session=module.new(self.root)

    def queue(self,op='ping',rid='a'*32,instance=None,now=100):
        packet=request(self.key,rid,instance,op,{},10,now=now)
        self.files[self.root+'\\request.txt']=packet.decode('ascii')

    def read_response(self,rid='a'*32):
        return response(self.key,self.files[self.root+'\\response.txt'].encode('ascii'),rid,None)

    def test_one_request_returns_immediately_and_duplicates_use_cached_response(self):
        self.lua.execute('calls=0;fixture.resolve.GetVersionString=function() calls=calls+1;return "21 MOCK" end')
        self.assertEqual(self.session.step(),(False,'IDLE'))
        self.queue()
        self.assertEqual(self.session.step(),(True,'REPLIED'))
        first=self.files[self.root+'\\response.txt']
        self.assertEqual(self.read_response()[0],self.id)
        self.assertEqual(self.session.step(),(True,'REPLIED'))
        self.assertEqual(first,self.files[self.root+'\\response.txt'])
        self.assertEqual(self.lua.globals().calls,1)
        self.assertEqual(len(self.releases),3)

    def test_tampering_and_write_commands_cannot_reach_handlers(self):
        self.queue()
        packet=self.files[self.root+'\\request.txt']
        self.files[self.root+'\\request.txt']=packet.replace('ping','projects')
        self.assertEqual(self.session.step(),(False,'REJECTED'))
        self.assertFalse(self.writes)
        self.queue('create_test_project',instance=self.id)
        self.session.step()
        with self.assertRaises(BridgeError) as error:self.read_response()
        self.assertEqual(error.exception.code,'OP_NOT_ALLOWED')

    def test_expiry_instance_and_duplicate_id_guards_are_preserved(self):
        for expected,op,rid,instance,now in [
            ('EXPIRED','ping','a'*32,None,50),
            ('BRIDGE_RESTARTED','projects','a'*32,'c'*32,100),
        ]:
            self.queue(op,rid,instance,now);self.session.step()
            with self.assertRaises(BridgeError) as error:self.read_response()
            self.assertEqual(error.exception.code,expected)
        self.queue();self.session.step()
        self.queue('projects',instance=self.id);self.session.step()
        with self.assertRaises(BridgeError) as error:self.read_response()
        self.assertEqual(error.exception.code,'DUPLICATE_ID')

    def test_key_rotation_busy_and_close_do_not_process_pending_request(self):
        self.queue();self.busy=True
        self.assertEqual(self.session.step(),(False,'BUSY'))
        self.busy=False;self.files[self.root+'\\session.key']='0'*64
        self.assertEqual(self.session.step(),(False,'SESSION_CHANGED'))
        self.assertEqual(self.session.step(),(False,'CLOSED'))
        self.assertFalse(self.writes)
        self.assertTrue(self.session.close())

    def test_failed_write_releases_mutex_and_preserves_cached_read(self):
        self.lua.execute('calls=0;fixture.resolve.GetVersionString=function() calls=calls+1;return "21 MOCK" end')
        self.queue();self.fail_write=True
        with self.assertRaisesRegex(LuaError,'response write'):self.session.step()
        self.assertEqual(len(self.releases),1)
        self.fail_write=False;self.session.step()
        self.assertEqual(self.lua.globals().calls,1)

    def test_signed_stop_closes_the_console_session(self):
        self.queue('stop',instance=self.id);self.session.step()
        self.assertTrue(self.read_response()[1]['stopped'])
        self.assertEqual(self.session.step(),(False,'CLOSED'))


class UtilityPathTests(unittest.TestCase):
    def test_two_lines_raise_unique_host_error_without_any_libraries_or_ui(self):
        identifier='a'*32
        lua=Lua51Runtime(unpack_returned_tuples=True)
        lua.execute('print=nil;ffi=nil;bit=nil;bmd=nil;fusion=nil;resolve=nil;io=nil;require=nil;package=nil')
        source=utility_path_check(identifier)
        self.assertEqual(len(source.splitlines()),2)
        self.assertTrue(source.isascii())
        with self.assertRaisesRegex(Lua51Error,'RMC_UTILITY_ERROR_'+identifier):lua.execute(source)
        with self.assertRaises(ValueError):utility_path_check('../unsafe')

    def test_console_artifact_excludes_edit_dispatcher_and_wait_loop(self):
        source=console_bundle(Path('C:/fixture/mailbox'))
        self.assertNotIn('writes_require_local_approval',source)
        self.assertNotIn("module('edits')",source)
        self.assertNotIn('bmd.wait',source)
        self.assertNotIn('while not bridge.stopped',source)


class ConnectionInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.base=Path(self.temp.name);self.id='a'*32
        self.root=self.base/('ResolveMCPConsole_'+self.id);self.root.mkdir()
        self.menu=self.base/'Support'/'Fusion'/'Scripts'/'Utility'/f'ResolveMCP_Path_{self.id[:8]}.lua'
        self.menu.parent.mkdir(parents=True);self.menu.write_text(utility_path_check(self.id))
        (self.root/'UtilityPath.lua').write_bytes(self.menu.read_bytes())
        (self.root/'ConsoleReadOnly.lua').write_bytes(b'trusted fixture')
        self.logs=self.base/'Support'/'logs';self.logs.mkdir()
        self.info=self.root/'connection-info.json'
        self.data={'connection_format':1,'connection_id':self.id,'root':str(self.root),
            'console_script':str(self.root/'ConsoleReadOnly.lua'),'mailbox':str(self.root/'mailbox'),
            'utility_menu_script':str(self.menu),'log_directory':str(self.logs),'sha256':{
                'Console':hashlib.sha256(b'trusted fixture').hexdigest(),
                'Utility':hashlib.sha256(self.menu.read_bytes()).hexdigest()}}
        self.info.write_text(json.dumps(self.data))

    def tearDown(self):self.temp.cleanup()

    def test_log_scan_preserves_privacy_and_absence_is_inconclusive(self):
        row=inspect_connection(self.info)['utility']
        self.assertEqual(row['log_scan'],'NO_MARKER_OBSERVED')
        self.assertIn('not proof',row['interpretation'])
        secret='do not disclose unrelated log contents'
        (self.logs/'ResolveDebug.txt').write_text(secret+'\nRMC_UTILITY_ERROR_'+self.id)
        result=inspect_connection(self.info)
        self.assertEqual(result['utility']['log_scan'],'MARKER_OBSERVED')
        self.assertNotIn(secret,json.dumps(result))
        self.assertTrue(result['utility']['evidence'][0]['ERROR'])
        self.menu.write_text('tampered')
        self.assertEqual(inspect_connection(self.info)['utility']['menu_script_integrity'],'MISMATCH')

    def test_outside_mailbox_or_logs_and_missing_key_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'key is missing'):ping_connection(self.info)
        for field in ['mailbox','log_directory']:
            with self.subTest(field=field):
                self.info.write_text(json.dumps({**self.data,field:str(self.base)}))
                with self.assertRaises(ValueError):inspect_connection(self.info)

    def test_saved_response_is_independently_authenticated_and_bound_to_request(self):
        mailbox=self.root/'mailbox';mailbox.mkdir();key=b'k'*32;rid='b'*32
        (mailbox/'session.key').write_text(key.hex())
        (mailbox/'request.txt').write_bytes(request(key,rid,None,'ping',{},10,now=100))
        reply=pack(key,['RMC3',rid,'c'*32,'OK',b'{}'.hex()])
        (mailbox/'response.txt').write_bytes(reply)
        self.assertEqual(inspect_connection(self.info)['console']['saved_response'],'AUTHENTICATED_MATCH')
        (mailbox/'response.txt').write_bytes(reply.replace(rid.encode(),b'd'*32))
        self.assertEqual(inspect_connection(self.info)['console']['saved_response'],'AUTH_FAILED')
