"""Prepare and execute one explicitly approved, new-project edit validation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.edit_validation import prepare_validation, load_validation, run_validation
from resolve_mcp.transport import read_data

parser=argparse.ArgumentParser(description=__doc__)
mode=parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--prepare',action='store_true')
mode.add_argument('--run',type=Path,metavar='EDIT_INFO')
parser.add_argument('--confirm-project-name')
args=parser.parse_args()
if args.prepare:result=prepare_validation()
else:
    info=load_validation(args.run)
    if args.confirm_project_name!=info['project_name']:parser.error('--confirm-project-name must match the new test project')
    pending=Path(info['mailbox'])/'request.txt'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(run_validation,args.run,args.confirm_project_name)
        while not future.done():
            if pending.is_file():
                print('Edit requests ready. Start the new Utility item OR paste the prepared Console command once. Do not start both.',file=sys.stderr,flush=True)
                break
            time.sleep(0.005)
        result=future.result()
print(json.dumps(result,ensure_ascii=True,indent=2))
if result.get('result')=='FAIL':raise SystemExit(1)
