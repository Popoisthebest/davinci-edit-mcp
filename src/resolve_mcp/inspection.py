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
    version=info.get('probe_format')
    entry_only=version == 3 and info.get('probe_kind') == 'utility-entry'
    if (version != 2 and not entry_only) or not re.fullmatch('[0-9a-f]{32}',identifier):
        raise ValueError('Prepare a new v2 probe or v3 Utility entry diagnostic; this manifest is old or invalid')
    root=safe_path(Path(info['probe_root']))
    if root != info_path.parent or root.name != 'ResolveMCPProbe_'+identifier:
        raise ValueError('Probe manifest does not match its dedicated directory')
    result={'probe_format':version,'probe_id':identifier,'probe_root':str(root),'contexts':{}}
    if entry_only:result['probe_kind']='utility-entry'
    def checksum(path,expected):
        try:actual=hashlib.sha256(read_data(safe_path(path))).hexdigest()
        except FileNotFoundError:return 'MISSING'
        return 'MATCH' if actual == expected else 'MISMATCH'
    for context in (('Utility',) if entry_only else ('Console','Utility')):
        expected=info['script_sha256'][context]
        row={'script_integrity':checksum(root/f'{context}Probe.lua',expected)}
        if context == 'Utility' and info.get('utility_menu_script'):
            target=safe_path(Path(info['utility_menu_script']))
            filename=(f'ResolveMCP_UtilityEntry_v3_{identifier[:8]}.lua' if entry_only else
                      f'ResolveMCP_ReadOnlyProbe_v2_{identifier[:8]}.lua')
            if target.name != filename:
                raise ValueError('Unexpected Utility probe filename')
            row['menu_script']=str(target)
            row['menu_script_integrity']=checksum(target,expected)
        try:receipt=json.loads(read_data(root/f'{context}-launch.json').decode('utf-8'))
        except FileNotFoundError:
            row['status']='RECEIPT_MISSING';result['contexts'][context]=row;continue
        if receipt.get('probe_id') != identifier or receipt.get('context') != context:
            raise ValueError('Receipt belongs to a different prepared probe/context')
        row.update({k:receipt[k] for k in ('status','last_stage','result','ffi_type','bit_type',
            'result_file_written','result_write_error','entry_error','environment','output_channels','checks') if k in receipt})
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
            row['interpretation']='No Lua entry receipt. Missing FFI or blocked file I/O can prevent a receipt; this does not prove the menu was never invoked.'
            if entry_only:
                row['interpretation']+=' The independent v3 entry and final dialogs report host globals and the failed stage without needing a file writer. No dialog still cannot prove whether the host invoked the script; UI availability and host errors must also be considered.'
            else:
                row['interpretation']+=' v2 cannot distinguish pre-writer failures; see the independent Utility entry diagnosis. Repeating the same v2 test provides no additional evidence.'
        result['contexts'][context]=row
    return result
