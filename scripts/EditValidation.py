"""Prepare and execute one explicitly approved, new-project edit validation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.edit_validation import prepare_validation, load_validation, run_validation
from resolve_mcp.clipboard import copy_lua_command

parser=argparse.ArgumentParser(description=__doc__)
mode=parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--prepare',action='store_true')
mode.add_argument('--run',type=Path,metavar='EDIT_INFO')
parser.add_argument('--confirm-project-name')
parser.add_argument('--confirm-bootstrap-project-name')
parser.add_argument('--host',choices=['Console','Utility'],default='Console')
args=parser.parse_args()
if args.prepare:result=prepare_validation()
else:
    info=load_validation(args.run)
    if args.confirm_project_name!=info['project_name']:parser.error('--confirm-project-name must match the new test project')
    if args.confirm_bootstrap_project_name!=info['bootstrap_project_name']:
        parser.error('--confirm-bootstrap-project-name must match the new empty bootstrap project')
    print('Test projects only: close '+info['bootstrap_project_name']+' -> create '+info['project_name'],file=sys.stderr,flush=True)
    if args.host=='Console':
        try:
            copy_lua_command(info['console_command'])
            print('Clipboard now contains LUA CONSOLE ONLY. Paste once into Resolve Lua Console. Do not paste it into PowerShell or copy another PowerShell command first.',file=sys.stderr,flush=True)
        except Exception:
            print('Clipboard unavailable. Open '+info['console_command_file']+' and copy its LUA-only line into Resolve Lua Console.',file=sys.stderr,flush=True)
    entry='Paste once into Resolve Lua Console.' if args.host=='Console' else 'Start the new Utility menu item once; clipboard is unchanged.'
    print('Waiting up to 10 minutes for authenticated service readiness. '+entry+' No edit request has been sent. Do not start another host.',file=sys.stderr,flush=True)
    result=run_validation(args.run,args.confirm_project_name,args.confirm_bootstrap_project_name)
print(json.dumps(result,ensure_ascii=True,indent=2))
if result.get('result')=='FAIL':raise SystemExit(1)
