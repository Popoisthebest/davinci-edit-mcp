"""Read diagnostic receipts and script hashes; never execute Lua or touch Resolve."""
import hashlib
import json
from pathlib import Path
import re

from .transport import read_data, safe_path


def inspect_probe(info_path: Path) -> dict:
    info_path=safe_path(info_path)
    info=json.loads(read_data(info_path).decode('utf-8'))
    identifier=info.get('probe_id','')
    if info.get('probe_format') != 2 or not re.fullmatch('[0-9a-f]{32}',identifier):
        raise ValueError('Prepare a new v2 probe; this manifest is old or invalid')
    root=safe_path(Path(info['probe_root']))
    if root != info_path.parent or root.name != 'ResolveMCPProbe_'+identifier:
        raise ValueError('Probe manifest does not match its dedicated directory')
    result={'probe_format':2,'probe_id':identifier,'probe_root':str(root),'contexts':{}}
    def checksum(path,expected):
        try:actual=hashlib.sha256(read_data(safe_path(path))).hexdigest()
        except FileNotFoundError:return 'MISSING'
        return 'MATCH' if actual == expected else 'MISMATCH'
    for context in ('Console','Utility'):
        expected=info['script_sha256'][context]
        row={'script_integrity':checksum(root/f'{context}Probe.lua',expected)}
        if context == 'Utility' and info.get('utility_menu_script'):
            target=safe_path(Path(info['utility_menu_script']))
            if target.name != f'ResolveMCP_ReadOnlyProbe_v2_{identifier[:8]}.lua':
                raise ValueError('Unexpected Utility probe filename')
            row['menu_script']=str(target)
            row['menu_script_integrity']=checksum(target,expected)
        try:receipt=json.loads(read_data(root/f'{context}-launch.json').decode('utf-8'))
        except FileNotFoundError:
            row['status']='RECEIPT_MISSING';result['contexts'][context]=row;continue
        if receipt.get('probe_id') != identifier or receipt.get('context') != context:
            raise ValueError('Receipt belongs to a different prepared probe/context')
        row.update({k:receipt[k] for k in ('status','last_stage','result','ffi_type','bit_type',
            'result_file_written','result_write_error','entry_error') if k in receipt})
        if receipt.get('artifact_directory'):
            directory=safe_path(Path(receipt['artifact_directory']))
            if directory.parent != root or not re.fullmatch(context+'-[0-9a-f]{32}',directory.name):
                raise ValueError('Artifact path escapes the dedicated probe directory')
            report_file=directory/'result.json'
            row['report_file']=str(report_file)
            try:
                report=json.loads(read_data(report_file).decode('utf-8'))
                row['report_result']=report.get('result')
                row['checks']=report.get('checks',[])
            except FileNotFoundError:row['report_result']='MISSING'
        if receipt.get('status') == 'PREPARED':
            row['interpretation']='No Lua entry receipt. Check exact v2 menu item, syntax/startup errors and Utility globals. Missing FFI or blocked file I/O can also prevent a receipt; this does not prove the menu was never invoked.'
        result['contexts'][context]=row
    return result
