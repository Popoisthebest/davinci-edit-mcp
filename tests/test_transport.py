from concurrent.futures import ThreadPoolExecutor
import importlib.util
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from resolve_mcp.protocol import BridgeError, pack, unpack
from resolve_mcp.transport import Mailbox, atomic_write, read_data
from tests.support import FileBridge


def hold_lock(root, ready, release):
    box=Mailbox(Path(root),timeout=1)
    with box._locked():
        ready.set()
        release.wait(5)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=TemporaryDirectory()
        self.root=Path(self.temporary.name)/'mailbox'
        self.box=Mailbox(self.root,timeout=0.4)

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_reads_real_files_and_lua(self):
        with FileBridge(self.box):
            for op in ['ping','current_project','current_timeline','projects','timelines','tracks','media_pool','render_settings','timeline_items']:
                with self.subTest(op=op): self.assertIsInstance(self.box.call(op),dict)

    def test_unknown_operation_writes_nothing(self):
        with self.assertRaisesRegex(BridgeError,'OP_NOT_ALLOWED'): self.box.call('execute')
        self.assertFalse((self.root/'request.txt').exists())

    def test_concurrent_threads_and_clients_are_serialized(self):
        other=Mailbox(self.root,timeout=2)
        self.box.timeout=2
        with FileBridge(self.box,delay=0.01) as bridge:
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs=[pool.submit((self.box if i%2 else other).call,'current_project') for i in range(8)]
                self.assertTrue(all(job.result()['project_open'] for job in jobs))
            self.assertEqual(len(bridge.requests),10) # two handshakes plus eight requests

    def test_process_lock(self):
        context=multiprocessing.get_context('spawn')
        ready,release=context.Event(),context.Event()
        worker=context.Process(target=hold_lock,args=(str(self.root),ready,release))
        worker.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaisesRegex(BridgeError,'BUSY'): self.box.call('ping')
        finally:
            release.set();worker.join(5)
            if worker.is_alive(): worker.terminate();worker.join()
        self.assertEqual(worker.exitcode,0)

    def test_timeout_has_no_implicit_retry(self):
        start=time.monotonic()
        with self.assertRaisesRegex(BridgeError,'TIMEOUT'): self.box.call('ping')
        self.assertLess(time.monotonic()-start,1)

    def test_ready_wait_authenticates_new_challenge_before_any_request(self):
        with FileBridge(self.box):self.box.wait_ready(1)
        self.assertEqual(self.box.bridge_id,'b'*32)
        self.assertFalse((self.root/'request.txt').exists())
        self.assertFalse((self.root/'start.txt').exists())

    def test_old_ready_cannot_open_gate_and_unsigned_ready_fails(self):
        atomic_write(self.root/'ready.txt',pack(self.box.key,['RMC3','READY','a'*32,'b'*32]))
        with self.assertRaisesRegex(BridgeError,'STARTUP_TIMEOUT'):self.box.wait_ready(0.05)
        atomic_write(self.root/'ready.txt',pack(b'x'*32,['RMC3','READY','a'*32,'b'*32]))
        with self.assertRaisesRegex(BridgeError,'AUTH_FAILED'):self.box.wait_ready(0.05)
        self.assertFalse((self.root/'request.txt').exists())
        self.assertFalse((self.root/'start.txt').exists())

    def test_late_previous_reply_cannot_satisfy_new_request(self):
        self.box.timeout = 0.05
        with FileBridge(self.box,delay=0.15) as bridge:
            with self.assertRaisesRegex(BridgeError,'TIMEOUT'):
                self.box.call('ping')
            self.box.timeout = 1
            result = self.box.call('current_project')
            self.assertEqual(result['name'],'테스트_프로젝트')
            self.assertNotIn('connected',result)
            self.assertEqual(len(bridge.requests),3)

    def test_parent_traversal_is_rejected(self):
        with self.assertRaisesRegex(BridgeError,'UNSAFE_PATH'):
            Mailbox(self.root/'..'/'alias')

    def test_packet_disappearing_during_path_check_does_not_stop_polling(self):
        path=self.root/'response.txt';atomic_write(path,b'complete packet')
        original=Path.lstat
        first=True
        def transient_missing(target,*args,**kwargs):
            nonlocal first
            if target == path and first:
                first=False
                raise FileNotFoundError('Atomic replacement in progress')
            return original(target,*args,**kwargs)
        with patch.object(Path,'lstat',new=transient_missing):
            self.assertEqual(read_data(path),b'complete packet')

    def test_restart_clears_cached_instance(self):
        with FileBridge(self.box,instance='a'*32): self.box.call('ping')
        with FileBridge(self.box,instance='c'*32):
            with self.assertRaisesRegex(BridgeError,'BRIDGE_RESTARTED'): self.box.call('current_project')
            self.assertIsNone(self.box.bridge_id)
            self.assertTrue(self.box.call('current_project')['project_open'])

    def test_rotate_invalidates_other_clients_and_clears_packets(self):
        other=Mailbox(self.root)
        atomic_write(self.root/'response.txt',b'old')
        self.box.rotate_session()
        self.assertFalse((self.root/'response.txt').exists())
        with self.assertRaisesRegex(BridgeError,'SESSION_CHANGED'): other.call('ping')

    def test_stop_and_restart(self):
        with FileBridge(self.box): self.assertTrue(self.box.call('stop')['stopped'])
        self.box.bridge_id=None
        with FileBridge(self.box,instance='c'*32): self.assertTrue(self.box.call('ping')['connected'])

    def test_symlink_mailbox_rejected(self):
        link=Path(self.temporary.name)/'alias'
        try: link.symlink_to(self.root,target_is_directory=True)
        except OSError: self.skipTest('Creating symlinks is unavailable on this Windows runner')
        with self.assertRaisesRegex(BridgeError,'UNSAFE_PATH'): Mailbox(link)

    @unittest.skipIf(os.name=='nt','POSIX permission mode test')
    def test_unsafe_permissions(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(BridgeError,'UNSAFE_PERMISSIONS'): Mailbox(self.root)

    def test_invalid_key_does_not_get_silently_replaced(self):
        atomic_write(self.root/'session.key',b'invalid')
        with self.assertRaisesRegex(BridgeError,'CONFIGURATION'): Mailbox(self.root)

    def test_legacy_read_only_parser_regression(self):
        source=Path(__file__).resolve().parents[1]/'legacy_v0.2/resolve_mcp_server.py'
        with patch.dict(os.environ,{'APPDATA':str(self.root),'LOCALAPPDATA':str(self.root)}):
            spec=importlib.util.spec_from_file_location('legacy_v02',source)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        text=lambda value:value.encode('utf-8').hex()
        cases=[(['id','OK','PING',text('21.1.1')],{'connected':True,'resolve_version':'21.1.1'}),
               (['id','OK','PROJECT',text('테스트'), '2'],{'project_open':True,'name':'테스트','timeline_count':2}),
               (['id','OK','TIMELINE',text('타임라인'),'4','3','0','900'],{'timeline_open':True,'name':'타임라인','video_tracks':4,'audio_tracks':3,'start_frame':0,'end_frame':900}),
               (['id','OK','PROJECT','NONE'],{'project_open':False}),
               (['id','OK','TIMELINE','NONE'],{'timeline_open':False})]
        for fields,expected in cases:
            with self.subTest(kind=fields[2]): self.assertEqual(module._parse_reply(fields),expected)
