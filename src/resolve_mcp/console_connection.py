"""Two-line Utility path check and manual, authenticated Console connection."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .bundle import console_bundle, lua_string, utility_path_check
from .permissions import protect_directory
from .protocol import BridgeError, response, unpack
from .transport import Mailbox, read_data, safe_path


def prepare_connection() -> dict:
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA') or not os.environ.get('APPDATA'):
        raise RuntimeError('Prepare this connection on Windows with LOCALAPPDATA and APPDATA')
    identifier=uuid.uuid4().hex
    root=safe_path(Path(os.environ['LOCALAPPDATA'])/('ResolveMCPConsole_'+identifier))
    root.mkdir(mode=0o700);protect_directory(root)
    mailbox=Mailbox(root/'mailbox')
    script=root/'ConsoleReadOnly.lua'
    script.write_text(console_bundle(mailbox.root),encoding='utf-8',newline='\n')
    micro=root/'UtilityPath.lua'
    micro.write_text(utility_path_check(identifier),encoding='ascii',newline='\n')
    support=Path(os.environ['APPDATA'])/'Blackmagic Design'/'DaVinci Resolve'/'Support'
    menu=safe_path(support/'Fusion'/'Scripts'/'Utility'/f'ResolveMCP_Path_{identifier[:8]}.lua')
    menu.parent.mkdir(parents=True,exist_ok=True)
    with menu.open('x',encoding='ascii',newline='\n') as stream:stream.write(utility_path_check(identifier))
    info={'connection_format':1,'connection_id':identifier,'root':str(root),
          'mailbox':str(mailbox.root),'console_script':str(script),'utility_menu_script':str(menu),
          'log_directory':str(support/'logs'),
          'console_command':'RMCConsole = dofile('+lua_string(str(script))+'); print(RMCConsole.mode)',
          'console_step':'print(RMCConsole.step())',
          'sha256':{'Console':hashlib.sha256(script.read_bytes()).hexdigest(),
                    'Utility':hashlib.sha256(micro.read_bytes()).hexdigest()}}
    (root/'connection-info.json').write_text(json.dumps(info,ensure_ascii=True,indent=2),encoding='ascii')
    return info


def load_connection(info_path: Path) -> dict:
    info_path=safe_path(info_path)
    info=json.loads(read_data(info_path).decode('ascii'))
    identifier=info.get('connection_id','')
    if info.get('connection_format') != 1 or not re.fullmatch('[0-9a-f]{32}',identifier):
        raise ValueError('Invalid Console connection manifest')
    root=safe_path(Path(info['root']))
    if root != info_path.parent or root.name != 'ResolveMCPConsole_'+identifier:
        raise ValueError('Connection manifest does not match its dedicated root')
    if Path(info['mailbox']) != root/'mailbox' or Path(info['console_script']) != root/'ConsoleReadOnly.lua':
        raise ValueError('Connection paths escape the dedicated root')
    menu=safe_path(Path(info['utility_menu_script']))
    if (menu.name != f'ResolveMCP_Path_{identifier[:8]}.lua' or
        tuple(part.lower() for part in menu.parent.parts[-4:]) != ('support','fusion','scripts','utility')):
        raise ValueError('Unexpected Utility path-check filename')
    return info


def inspect_connection(info_path: Path) -> dict:
    info=load_connection(info_path)
    root=Path(info['root']);identifier=info['connection_id']
    result={'connection_id':identifier,'mode':'manual-read-only','utility':{},'console':{}}
    def checksum(path,expected):
        try:actual=hashlib.sha256(read_data(safe_path(path))).hexdigest()
        except FileNotFoundError:return 'MISSING'
        return 'MATCH' if actual == expected else 'MISMATCH'
    result['console']['script_integrity']=checksum(Path(info['console_script']),info['sha256']['Console'])
    result['utility'].update(menu_script=info['utility_menu_script'],
        script_integrity=checksum(root/'UtilityPath.lua',info['sha256']['Utility']),
        menu_script_integrity=checksum(Path(info['utility_menu_script']),info['sha256']['Utility']),
        log_scan='NO_MARKER_OBSERVED',evidence=[])
    # Read only bounded tails in this fixed Support/logs location, never print
    # log content. Resolve does not promise to route Lua errors into these files.
    logs=safe_path(Path(info['log_directory']))
    if logs != Path(info['utility_menu_script']).parents[3]/'logs':
        raise ValueError('Unexpected Resolve log directory')
    try:
        candidates=[]
        for i,path in enumerate(logs.iterdir()):
            if i >= 128:break
            if path.suffix.lower() in {'.txt','.log'}:candidates.append(path)
        for path in candidates[:32]:
            try:
                path=safe_path(path)
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-1048576));tail=stream.read(1048576)
                flags={}
                for kind in ['ENTER','ERROR']:
                    token=f'RMC_UTILITY_{kind}_{identifier}'
                    flags[kind]=any(token.encode(encoding) in tail for encoding in ['ascii','utf-16-le'])
                if any(flags.values()):
                    result['utility']['evidence'].append({'file':path.name,**flags})
            except (OSError,RuntimeError):
                result['utility'].setdefault('unreadable_log_files',[]).append(path.name)
        if result['utility']['evidence']:result['utility']['log_scan']='MARKER_OBSERVED'
    except FileNotFoundError:result['utility']['log_scan']='LOG_DIRECTORY_MISSING'
    result['utility']['interpretation']='No marker is not proof of non-execution. The two-line script writes no result file; its second line intentionally raises a unique host error. Do not rerun v2/v3 or the micro check to fill missing logs.'
    mailbox=Path(info['mailbox'])
    try:
        raw=read_data(safe_path(mailbox/'session.key'),65).decode('ascii')
        if not re.fullmatch('[0-9a-f]{64}',raw):raise ValueError('Invalid prepared session key')
        key=bytes.fromhex(raw)
        fields=unpack(key,read_data(mailbox/'request.txt'),6)
        response(key,read_data(mailbox/'response.txt'),fields[1],None if fields[3]=='-' else fields[3])
        result['console']['saved_response']='AUTHENTICATED_MATCH'
    except FileNotFoundError:result['console']['saved_response']='MISSING'
    except BridgeError as error:result['console']['saved_response']=error.code
    return result


def ping_connection(info_path: Path) -> dict:
    info=load_connection(info_path)
    script=Path(info['console_script'])
    if hashlib.sha256(read_data(script)).hexdigest() != info['sha256']['Console']:
        raise ValueError('Console script hash mismatch')
    key=safe_path(Path(info['mailbox'])/'session.key')
    if not key.is_file():raise ValueError('Prepared session key is missing; do not recreate it silently')
    # Unchanged HMAC, 29-second request TTL, ID/instance checks and client lock.
    box=Mailbox(Path(info['mailbox']),timeout=29)
    data=box.call('ping')
    return {'authenticated_ping':'PASS','mode':'manual-read-only','resolve_version':data.get('resolve_version'),
            'editing_test':'NOT_RUN'}
