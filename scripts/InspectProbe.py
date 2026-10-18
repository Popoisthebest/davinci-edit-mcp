"""Inspect a prepared probe's files only. No Resolve connection or execution."""
from pathlib import Path
import sys
import argparse
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.inspection import inspect_probe

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--info',type=Path,required=True)
args=parser.parse_args()
print(json.dumps(inspect_probe(args.info),ensure_ascii=True,indent=2))
