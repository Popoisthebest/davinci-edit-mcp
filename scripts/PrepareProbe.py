"""Run with Python 3.12; no pip installation or production bridge upgrade needed."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from resolve_mcp.bundle import prepare_probe
import argparse
import json

parser=argparse.ArgumentParser(description='Prepare project-read-only Console and Utility probes')
parser.add_argument('--install-utility',action='store_true')
args=parser.parse_args()
print(json.dumps(prepare_probe(args.install_utility),ensure_ascii=True,indent=2))
