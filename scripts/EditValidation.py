"""Prepare and execute one explicitly approved, new-project edit validation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.edit_validation import prepare_validation, load_validation, run_validation

parser=argparse.ArgumentParser(description=__doc__)
mode=parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--prepare',action='store_true')
mode.add_argument('--run',type=Path,metavar='EDIT_INFO')
parser.add_argument('--confirm-project-name')
parser.add_argument('--confirm-bootstrap-project-name')
args=parser.parse_args()
if args.prepare:result=prepare_validation()
else:
    info=load_validation(args.run)
    if args.confirm_project_name!=info['project_name']:parser.error('--confirm-project-name must match the new test project')
    if args.confirm_bootstrap_project_name!=info['bootstrap_project_name']:
        parser.error('--confirm-bootstrap-project-name must match the new empty bootstrap project')
    print('Waiting up to 10 minutes for authenticated service readiness. Open the prepared empty bootstrap project, then paste the Console command once OR start its Utility item. No edit request has been sent. Do not start both.',file=sys.stderr,flush=True)
    result=run_validation(args.run,args.confirm_project_name,args.confirm_bootstrap_project_name)
print(json.dumps(result,ensure_ascii=True,indent=2))
if result.get('result')=='FAIL':raise SystemExit(1)
