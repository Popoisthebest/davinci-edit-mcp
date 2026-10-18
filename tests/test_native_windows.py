import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lupa.luajit21 import LuaRuntime
from resolve_mcp.transport import atomic_write, read_data
from tests.support import BRIDGE


@unittest.skipUnless(os.name == 'nt', 'Requires actual Windows kernel file/mutex APIs')
class NativeWindowsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.native = self.lua.execute((BRIDGE/'native.lua').read_text(encoding='utf-8'))

    def test_unicode_file_atomic_replace_and_missing(self):
        with TemporaryDirectory() as temporary:
            path=str(Path(temporary)/'한글.txt')
            self.assertIsNone(self.native.read(path))
            self.native.write(path,'first')
            self.assertEqual(self.native.read(path),'first')
            self.native.write(path,'second')
            self.assertEqual(self.native.read(path),'second')

    def test_duplicate_mutex_and_restart(self):
        name=self.native.random_hex()
        release=self.native.acquire(name)
        self.assertIsNotNone(release)
        self.assertIsNone(self.native.acquire(name))
        release()
        restarted=self.native.acquire(name)
        self.assertIsNotNone(restarted)
        restarted()

    def test_python_reader_allows_atomic_replace_while_handle_is_open(self):
        from unittest.mock import patch
        import os
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'교체.txt'
            original_fdopen=os.fdopen
            for writer in [lambda:atomic_write(path,b'new'),lambda:self.native.write(str(path),'new')]:
                with self.subTest(writer=writer):
                    atomic_write(path,b'old')
                    def open_mode(descriptor,mode,*args,**kwargs):
                        if mode == 'rb':
                            # The Windows read handle remains open during replacement.
                            try:writer()
                            except BaseException:
                                os.close(descriptor)
                                raise
                        return original_fdopen(descriptor,mode,*args,**kwargs)
                    with patch('resolve_mcp.transport.os.fdopen',side_effect=open_mode):
                        self.assertEqual(read_data(path),b'old')
                    self.assertEqual(read_data(path),b'new')
