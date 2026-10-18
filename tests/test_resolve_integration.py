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
