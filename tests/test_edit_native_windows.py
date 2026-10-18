"""Real Windows media-path guards; Resolve itself is not simulated here."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lupa.luajit21 import LuaError, LuaRuntime
from tests.support import BRIDGE


@unittest.skipUnless(os.name == 'nt','Requires Windows file identity/reparse APIs')
class NativeEditingWindowsTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.native=self.lua.execute((BRIDGE/'native.lua').read_text(encoding='utf-8'))

    def test_unicode_media_file_and_directory_identity(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)/'복사한_테스트자료';root.mkdir()
            media=root/'한글_테스트.mp4';media.write_bytes(b'disposable fixture')
            self.assertTrue(Path(self.native.canonical_directory(str(root))).samefile(root))
            self.assertTrue(Path(self.native.canonical_file(str(media))).samefile(media))
            with self.assertRaises(LuaError):self.native.canonical_file(str(root))
            with self.assertRaises(LuaError):self.native.canonical_directory(str(media))
            self.assertEqual(media.read_bytes(),b'disposable fixture')

    def test_hardlinked_media_is_rejected_by_win32_adapter(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            media=root/'fixture.mp4';media.write_bytes(b'disposable fixture')
            linked=root/'linked.mp4';os.link(media,linked)
            for path in [media,linked]:
                with self.subTest(path=path):
                    with self.assertRaises(LuaError):self.native.canonical_file(str(path))

    def test_linked_ancestor_is_rejected_by_win32_adapter(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'actual';directory.mkdir()
            media=directory/'fixture.mp4';media.write_bytes(b'disposable fixture')
            alias=root/'alias'
            try:alias.symlink_to(directory,target_is_directory=True)
            except OSError:self.skipTest('Creating directory symlinks requires Windows privilege')
            with self.assertRaises(LuaError):self.native.canonical_file(str(alias/'fixture.mp4'))
