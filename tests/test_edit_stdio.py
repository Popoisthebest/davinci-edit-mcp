import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from resolve_mcp.editing import Editor,approve,prepare_media_root
from tests.edit_support import EditBridge
from tests.support import FileBridge


class EditingStdioTests(unittest.TestCase):
    def test_mcp_create_import_plan_append_readback_and_save(self):
        async def check(box,media):
            parameters=StdioServerParameters(command=sys.executable,
                args=['-m','resolve_mcp.server','--mailbox',str(box.root),'--enable-writes'],
                env={'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),'PYTHONDONTWRITEBYTECODE':'1'})
            async with stdio_client(parameters) as (reader,writer):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=5)) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    self.assertEqual(len(tools.tools),18)
                    self.assertFalse(any('delete' in tool.name or 'execute' in tool.name for tool in tools.tools))
                    self.assertTrue(next(tool for tool in tools.tools if tool.name=='resolve_current_project').annotations.readOnlyHint)
                    self.assertFalse(next(tool for tool in tools.tools if tool.name=='resolve_append_clip').annotations.readOnlyHint)
                    async def call(name,params=None):
                        result=await session.call_tool('resolve_'+name,params or {})
                        self.assertFalse(result.isError,result)
                        return result.structuredContent or json.loads(result.content[0].text)
                    await call('create_test_project')
                    bin_id=(await call('create_bin',{'name':'ResolveMCP_TEST_BIN_stdio'}))['bin_id']
                    media_id=(await call('import_media',{'bin_id':bin_id,'path':str(media)}))['media_id']
                    timeline_id=(await call('create_timeline',{'name':'ResolveMCP_TEST_TL_stdio'}))['timeline_id']
                    params={'timeline_id':timeline_id,'media_id':media_id,'media_type':1,'track_index':1,
                            'record_frame':0,'source_in':0,'source_out':30}
                    self.assertTrue((await call('plan_append',params))['dry_run'])
                    bad=await session.call_tool('resolve_append_clip',{**params,'source_out':True})
                    self.assertTrue(bad.isError)
                    self.assertEqual((await call('append_clip',params))['duration_frames'],30)
                    result=await call('timeline_items')
                    self.assertEqual(result['tracks'][0]['items'][0]['end_frame'],30)
                    await call('duplicate_timeline',{'timeline_id':timeline_id,'name':'ResolveMCP_TEST_TL_stdio_copy'})
                    self.assertTrue((await call('save_test_project'))['saved'])
                    (box.root/'approval.txt').unlink()
                    denied=await session.call_tool('resolve_save_test_project',{})
                    self.assertTrue(denied.isError)
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            box=Editor(root/'mailbox')
            media_root=root/'ResolveMCP_TEST_MEDIA_stdio'
            prepare_media_root(box,media_root)
            media=media_root/'fixture.mp4';media.write_bytes(b'mocked fixture')
            name='ResolveMCP_TEST_stdio';approve(box,name,media_root,name)
            with FileBridge(box,factory=EditBridge):asyncio.run(check(box,media))
