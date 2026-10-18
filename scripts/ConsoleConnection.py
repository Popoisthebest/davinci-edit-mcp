"""Prepare/inspect a manual Console connection; no pip installation required."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.console_connection import prepare_connection, inspect_connection, ping_connection, load_connection
from resolve_mcp.transport import read_data

parser=argparse.ArgumentParser(description=__doc__)
group=parser.add_mutually_exclusive_group(required=True)
group.add_argument('--prepare',action='store_true')
group.add_argument('--prepare-auto',action='store_true',help='Prepare bounded Utility/Console automatic reads')
group.add_argument('--inspect',type=Path,metavar='INFO')
group.add_argument('--ping',type=Path,metavar='INFO')
args=parser.parse_args()
if args.prepare or args.prepare_auto:result=prepare_connection(automatic=args.prepare_auto)
elif args.inspect:result=inspect_connection(args.inspect)
else:
    from concurrent.futures import ThreadPoolExecutor
    import time
    pending=Path(load_connection(args.ping)['mailbox'])/'request.txt'
    try:previous=read_data(pending)
    except FileNotFoundError:previous=None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(ping_connection,args.ping)
        while not future.done():
            try:published=read_data(pending)
            except FileNotFoundError:published=None
            if published is not None and published != previous:
                print('Request ready. Resolve Lua Console: print(RMCConsole.step()) within 29 seconds; no automatic retry.',file=sys.stderr,flush=True)
                break
            time.sleep(0.005)
        result=future.result()
print(json.dumps(result,ensure_ascii=True,indent=2))
