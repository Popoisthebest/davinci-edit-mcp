"""Offline inspection cannot confuse prepared scripts with a completed UI run."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from resolve_mcp.inspection import inspect_probe
from resolve_mcp.protocol import BridgeError


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.identifier='a'*32
        self.root=Path(self.temp.name)/('ResolveMCPProbe_'+self.identifier);self.root.mkdir()
        self.info=self.root/'probe-info.json'
        data={'probe_format':2,'probe_id':self.identifier,'probe_root':str(self.root),'script_sha256':{}}
        for context in ['Console','Utility']:
            script=self.root/(context+'Probe.lua');script.write_bytes(b'trusted fixture')
            data['script_sha256'][context]=hashlib.sha256(script.read_bytes()).hexdigest()
            self.receipt(context,status='PREPARED',last_stage='NOT_ENTERED')
        self.info.write_text(json.dumps(data))

    def tearDown(self):self.temp.cleanup()

    def receipt(self,context='Utility',**fields):
        value={'probe_format':2,'probe_id':self.identifier,'context':context,**fields}
        (self.root/(context+'-launch.json')).write_text(json.dumps(value))

    def test_prepared_receipt_is_not_proof_the_menu_never_ran(self):
        row=inspect_probe(self.info)['contexts']['Utility']
        self.assertEqual(row['status'],'PREPARED')
        self.assertIn('Missing FFI',row['interpretation'])
        self.assertEqual(row['script_integrity'],'MATCH')

    def test_modified_bundle_is_detected(self):
        (self.root/'UtilityProbe.lua').write_bytes(b'modified')
        self.assertEqual(inspect_probe(self.info)['contexts']['Utility']['script_integrity'],'MISMATCH')

    def test_running_stage_and_partial_report_are_visible(self):
        directory=self.root/('Utility-'+'b'*32);directory.mkdir()
        (directory/'result.json').write_text(json.dumps({'result':'RUNNING','checks':[]}))
        self.receipt(status='RUNNING',last_stage='QUERY_projects',artifact_directory=str(directory),result='RUNNING')
        row=inspect_probe(self.info)['contexts']['Utility']
        self.assertEqual((row['last_stage'],row['report_result']),('QUERY_projects','RUNNING'))

    def test_report_write_failure_is_visible_without_result_file(self):
        directory=self.root/('Utility-'+'b'*32);directory.mkdir()
        self.receipt(status='FINISHED',last_stage='FINISHED',artifact_directory=str(directory),result='FAIL',
                     result_file_written=False,result_write_error='permission denied')
        row=inspect_probe(self.info)['contexts']['Utility']
        self.assertEqual(row['report_result'],'MISSING')
        self.assertEqual(row['result_write_error'],'permission denied')

    def test_outside_report_and_wrong_receipt_are_rejected(self):
        self.receipt(status='RUNNING',artifact_directory=str(Path(self.temp.name)))
        with self.assertRaises(ValueError):inspect_probe(self.info)
        self.receipt(status='RUNNING',probe_id='c'*32)
        with self.assertRaises(ValueError):inspect_probe(self.info)

    def test_old_manifest_requires_regeneration(self):
        self.info.write_text('{}')
        with self.assertRaisesRegex(ValueError,'new v2 probe'):inspect_probe(self.info)

    def test_v3_inspects_only_utility_and_preserves_environment_diagnostics(self):
        data=json.loads(self.info.read_text())
        data.update(probe_format=3,probe_kind='utility-entry')
        data['script_sha256'].pop('Console')
        self.info.write_text(json.dumps(data))
        self.receipt(probe_format=3,status='FINISHED',last_stage='FFI_GLOBALS',result='FAIL',
            environment={'lua_version':'Lua 5.1','symbols':{'ffi':{'resolved':'nil','raw_global':'nil'}}},
            entry_error='Missing global library: ffi')
        result=inspect_probe(self.info)
        self.assertEqual(set(result['contexts']),{'Utility'})
        self.assertEqual(result['contexts']['Utility']['last_stage'],'FFI_GLOBALS')
        self.assertEqual(result['contexts']['Utility']['environment']['symbols']['ffi']['resolved'],'nil')

    def test_v3_cannot_use_an_old_menu_filename_or_unknown_kind(self):
        data=json.loads(self.info.read_text())
        data.update(probe_format=3,probe_kind='utility-entry',utility_menu_script=str(
            self.root/f'ResolveMCP_ReadOnlyProbe_v2_{self.identifier[:8]}.lua'))
        self.info.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'filename'):inspect_probe(self.info)
        data['probe_kind']='unknown';self.info.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'old or invalid'):inspect_probe(self.info)
