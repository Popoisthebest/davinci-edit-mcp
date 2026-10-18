import asyncio
from datetime import timedelta
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from resolve_mcp.transport import Mailbox
from tests.support import FileBridge


class StdioTests(unittest.TestCase):
    def test_real_stdio_tools_and_calls(self):
        async def check(root):
            source=Path(__file__).resolve().parents[1]/'src'
            parameters=StdioServerParameters(command=sys.executable,
                args=['-m','resolve_mcp.server','--mailbox',str(root)],
                env={'PYTHONPATH':str(source),'PYTHONDONTWRITEBYTECODE':'1'})
            async with stdio_client(parameters) as (reader,writer):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=5)) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    self.assertEqual(len(tools.tools),9)
                    self.assertFalse(any('stop' in tool.name or 'write' in tool.name for tool in tools.tools))
                    for tool in tools.tools:
                        result=await session.call_tool(tool.name,{})
                        self.assertFalse(result.isError,result)
                    denied=await session.call_tool('execute_lua',{'code':'anything'})
                    self.assertTrue(denied.isError)
        with TemporaryDirectory() as temporary:
            root=Path(temporary)/'mailbox'
            box=Mailbox(root)
            with FileBridge(box): asyncio.run(check(root))
