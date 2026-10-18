import os
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch

from resolve_mcp.clipboard import copy_lua_command


class ClipboardTests(unittest.TestCase):
    def launch(self,host='Console',copy_error=None):
        events=[]
        info={'project_name':'ResolveMCP_TEST_new','bootstrap_project_name':'ResolveMCP_BOOT_fixture',
              'console_command':'RMCEdit.run(180)','console_command_file':'C:/private/LuaConsoleCommand.txt'}
        def copy(command):
            events.append(('clipboard',command))
            if copy_error:raise copy_error
        def run(*args):events.append(('validation',args));return {'result':'PASS'}
        args=['EditValidation.py','--run','C:/private/edit-info.json',
              '--confirm-project-name',info['project_name'],'--confirm-bootstrap-project-name',info['bootstrap_project_name'],
              '--host',host]
        with patch.object(sys,'argv',args),patch('resolve_mcp.edit_validation.load_validation',return_value=info),\
             patch('resolve_mcp.edit_validation.run_validation',side_effect=run),\
             patch('resolve_mcp.clipboard.copy_lua_command',side_effect=copy),\
             redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()) as messages:
            runpy.run_path(str(Path(__file__).parents[1]/'scripts'/'EditValidation.py'),run_name='__main__')
        return events,messages.getvalue()

    def test_running_powershell_entry_copies_only_lua_before_validation_waits(self):
        events,messages=self.launch()
        self.assertEqual([row[0] for row in events],['clipboard','validation'])
        self.assertEqual(events[0][1],'RMCEdit.run(180)')
        self.assertIn('LUA CONSOLE ONLY',messages)

    def test_utility_entry_does_not_replace_clipboard(self):
        events,_=self.launch('Utility')
        self.assertEqual([row[0] for row in events],['validation'])

    def test_clipboard_failure_provides_fixed_lua_file_and_still_waits_safely(self):
        events,messages=self.launch(copy_error=OSError('clipboard busy'))
        self.assertEqual([row[0] for row in events],['clipboard','validation'])
        self.assertIn('C:/private/LuaConsoleCommand.txt',messages)

    def test_command_is_stdin_data_and_fixed_program_does_not_evaluate_it(self):
        command='RMCEdit.run(180); $x=$(throw "must remain clipboard data")'
        with patch('resolve_mcp.clipboard.os.name','nt'),patch('resolve_mcp.clipboard.subprocess.run') as run:
            copy_lua_command(command)
        args,kwargs=run.call_args
        self.assertEqual(kwargs['input'],command)
        self.assertNotIn(command,args[0])
        self.assertNotIn('shell',kwargs)
        self.assertEqual(args[0][-1],'Set-Clipboard -Value ([Console]::In.ReadToEnd())')

    @unittest.skipUnless(os.name=='nt','Requires Windows clipboard and PowerShell')
    def test_actual_windows_clipboard_contains_lua_data_without_powershell_evaluation(self):
        command='RMCEdit.run(180); $(throw "literal clipboard data")'
        copy_lua_command(command)
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-STA','-Command','Get-Clipboard -Raw'],
                              capture_output=True,text=True,encoding='ascii',check=True,timeout=10)
        self.assertEqual(result.stdout.rstrip('\r\n'),command)
