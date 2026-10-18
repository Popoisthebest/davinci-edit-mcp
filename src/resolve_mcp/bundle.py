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
           'bridge':'ResolveMCP3.lua','probe':'probe.lua','console':'console.lua'}


def lua_string(value: str) -> str:
    return '"' + ''.join(f'\\{byte:03d}' for byte in value.encode('utf-8')) + '"'


def loader_source(names: tuple[str, ...] | None = None) -> str:
    source = '-- Generated from trusted repository sources. No runtime code loading.\n'
    source += 'local factory_loader = (function()\n' + (BRIDGE/'loader.lua').read_text(encoding='utf-8') + '\nend)()\n'
    source += 'local module = factory_loader({\n'
    for name in (names if names is not None else MODULES):
        filename = MODULES[name]
        source += f'[{lua_string(name)}] = function(...)\n'
        source += (BRIDGE/filename).read_text(encoding='utf-8') + '\nend,\n'
    return source + '})\n'


def utility_diagnostic(root: Path) -> str:
    """Small independent entry diagnostic; no queries or production dispatcher."""
    source = (BRIDGE/'utility_entry.lua').read_text(encoding='ascii')
    source = source.replace('-- FIXED_REGISTRY',loader_source(('runtime','codec','native'))+'return module')
    return source + f'\nreturn diagnose({lua_string(str(root))})\n'


def console_bundle(root: Path, *, enable_edits: bool = False) -> str:
    names=('runtime','native','crypto','codec','reads','core','console')
    if enable_edits:
        if 'edits' not in MODULES:raise ValueError('Editing requires the v0.4 source')
        names+=('bridge','edits')
    enabled='true' if enable_edits else 'false'
    return loader_source(names)+f"return module('console').new({lua_string(str(root))},{enabled})\n"


def utility_launcher(payload: Path, identifier: str, seconds: int = 180) -> str:
    utility_path_check(identifier) # validate the fixed build-time ID
    if type(seconds) is not int or not 1 <= seconds <= 600:raise ValueError('Invalid service duration')
    # Only this trusted, owner-protected absolute payload is loaded. Never read
    # code paths from requests. A separate chunk makes compile errors catchable.
    return (f'if type(print)=="function" then pcall(print,"RMC_AUTO_ENTER_{identifier}") end\n'
            'local ok,err=pcall(function()\n'
            'assert(type(loadfile)=="function","BOOTSTRAP_LOADFILE_UNAVAILABLE")\n'
            f'local chunk,why=loadfile({lua_string(str(payload))})\n'
            'assert(chunk,"PAYLOAD_COMPILE: "..tostring(why))\n'
            'if type(getfenv)=="function" and type(setfenv)=="function" then setfenv(chunk,getfenv(1)) end\n'
            'local session=chunk()\n'
            f'session.run({seconds},"Utility")\n'
            'end)\n'
            'if not ok then error("ResolveMCP bootstrap: "..tostring(err),0) end\n')


def utility_path_check(identifier: str) -> str:
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid path check identifier')
    return (f'if type(print) == "function" then pcall(print,"RMC_UTILITY_ENTER_{identifier}") end\n'
            f'error("RMC_UTILITY_ERROR_{identifier} (intentional path check)",0)\n')


def bundle(probe_root: Path | None = None, context: str = 'Console') -> str:
    if context not in {'Console','Utility','CI'}:
        raise ValueError('Invalid probe context')
    tail = "return module('bridge').run()\n" if probe_root is None else (
        f"return module('probe').run({lua_string(str(probe_root))},{lua_string(context)})\n")
    return loader_source() + tail


def prepare_probe(install_utility: bool = False, *, utility_entry: bool = False) -> dict:
    from .permissions import protect_directory
    from .transport import safe_path
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        raise RuntimeError('Prepare the hardware probe on Windows with LOCALAPPDATA')
    identifier = uuid.uuid4().hex
    root = safe_path(Path(os.environ['LOCALAPPDATA']) / f'ResolveMCPProbe_{identifier}')
    root.mkdir(mode=0o700)
    protect_directory(root)
    version = 3 if utility_entry else 2
    result = {'probe_format':version,'probe_id':identifier,'probe_root':str(root),'script_sha256':{}}
    if utility_entry:result['probe_kind']='utility-entry'
    for context in (('Utility',) if utility_entry else ('Console','Utility')):
        path = root / f'{context}Probe.lua'
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(utility_diagnostic(root) if utility_entry else bundle(root,context))
        result[context.lower() + '_script'] = str(path)
        result['script_sha256'][context] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt=root/f'{context}-launch.json'
        receipt.write_text(json.dumps({'probe_format':version,'probe_id':identifier,'context':context,
            'status':'PREPARED','last_stage':'NOT_ENTERED'}),encoding='utf-8')
    if install_utility:
        if not os.environ.get('APPDATA'):raise RuntimeError('APPDATA is required for the Utility probe')
        target = safe_path(Path(os.environ['APPDATA']) / 'Blackmagic Design' / 'DaVinci Resolve' /
            'Support' / 'Fusion' / 'Scripts' / 'Utility' / (
                f'ResolveMCP_UtilityEntry_v3_{identifier[:8]}.lua' if utility_entry else
                f'ResolveMCP_ReadOnlyProbe_v2_{identifier[:8]}.lua'))
        target.parent.mkdir(parents=True,exist_ok=True)
        # A unique entry; never overwrite the active or legacy bridge.
        with target.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(utility_diagnostic(root) if utility_entry else bundle(root,'Utility'))
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
