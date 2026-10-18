"""Build a fixed Lua module registry without runtime filesystem/code loading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

BRIDGE = Path(__file__).parent / 'bridge'
MODULES = {'runtime':'runtime.lua','native':'native.lua','crypto':'crypto.lua',
           'codec':'codec.lua','reads':'reads.lua','core':'core.lua',
           'bridge':'ResolveMCP3.lua','probe':'probe.lua','edits':'edits.lua'}


def lua_string(value: str) -> str:
    return '"' + ''.join(f'\\{byte:03d}' for byte in value.encode('utf-8')) + '"'


def loader_source() -> str:
    source = '-- Generated from trusted repository sources. No runtime code loading.\n'
    source += 'local factory_loader = (function()\n' + (BRIDGE/'loader.lua').read_text(encoding='utf-8') + '\nend)()\n'
    source += 'local module = factory_loader({\n'
    for name, filename in MODULES.items():
        source += f'[{lua_string(name)}] = function(...)\n'
        source += (BRIDGE/filename).read_text(encoding='utf-8') + '\nend,\n'
    return source + '})\n'


def bundle(probe_root: Path | None = None, context: str = 'Console') -> str:
    if context not in {'Console','Utility','CI'}:
        raise ValueError('Invalid probe context')
    tail = "return module('bridge').run()\n" if probe_root is None else (
        f"return module('probe').run({lua_string(str(probe_root))},{lua_string(context)})\n")
    return loader_source() + tail


def prepare_probe(install_utility: bool = False) -> dict:
    from .permissions import protect_directory
    from .transport import safe_path
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        raise RuntimeError('Prepare the hardware probe on Windows with LOCALAPPDATA')
    identifier = uuid.uuid4().hex
    root = safe_path(Path(os.environ['LOCALAPPDATA']) / f'ResolveMCPProbe_{identifier}')
    root.mkdir(mode=0o700)
    protect_directory(root)
    result = {'probe_format':2,'probe_id':identifier,'probe_root':str(root),'script_sha256':{}}
    for context in ('Console','Utility'):
        path = root / f'{context}Probe.lua'
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(bundle(root,context))
        result[context.lower() + '_script'] = str(path)
        result['script_sha256'][context] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt=root/f'{context}-launch.json'
        receipt.write_text(json.dumps({'probe_format':2,'probe_id':identifier,'context':context,
            'status':'PREPARED','last_stage':'NOT_ENTERED'}),encoding='utf-8')
    if install_utility:
        if not os.environ.get('APPDATA'):raise RuntimeError('APPDATA is required for the Utility probe')
        target = safe_path(Path(os.environ['APPDATA']) / 'Blackmagic Design' / 'DaVinci Resolve' /
            'Support' / 'Fusion' / 'Scripts' / 'Utility' / f'ResolveMCP_ReadOnlyProbe_v2_{identifier[:8]}.lua')
        target.parent.mkdir(parents=True,exist_ok=True)
        # A unique entry; never overwrite the active or legacy bridge.
        with target.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(bundle(root,'Utility'))
        result['utility_menu_script'] = str(target)
    (root/'probe-info.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--prepare-probe',action='store_true')
    parser.add_argument('--install-utility',action='store_true')
    args=parser.parse_args()
    if args.prepare_probe:
        print(json.dumps(prepare_probe(args.install_utility),ensure_ascii=True,indent=2))
    elif args.output:
        with args.output.open('x',encoding='utf-8',newline='\n') as stream:stream.write(bundle())
    else:parser.error('--output or --prepare-probe is required')


if __name__ == '__main__':main()
