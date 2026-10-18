"""Project names must remain strings, regardless of Resolve's table metadata."""
import secrets
import unittest

from resolve_mcp.protocol import BridgeError,request,response
from tests.support import LuaBridge


class ProjectListTests(unittest.TestCase):
    def setUp(self):
        self.key=bytes(range(32));self.bridge=LuaBridge(self.key)

    def projects(self,expression):
        self.bridge.api.manager.GetProjectListInCurrentFolder=self.bridge.lua.eval('function() return '+expression+' end')
        rid=secrets.token_hex(16)
        packet=request(self.key,rid,self.bridge.instance,'projects',{},5,now=100)
        return response(self.key,self.bridge.process(packet,100),rid,self.bridge.instance)[1]

    def test_string_names_are_sorted_without_coercion(self):
        result=self.projects("{'Z','한글','A','10','2'}")
        self.assertEqual(result['projects'],['10','2','A','Z','한글'])
        self.assertEqual(result['normalization']['ignored_entries'],0)
        self.assertFalse(result['normalization']['may_be_incomplete'])

    def test_sparse_mixed_values_and_numeric_metadata(self):
        result=self.projects("{[1]='Z',[4]=10,[7]='A',count=3,unexpected=false,sub={}}")
        self.assertEqual(result['projects'],['A','Z'])
        self.assertEqual(result['normalization'],{'input_entries':6,'accepted_names':2,'ignored_entries':4,
            'ignored_value_types':{'number':2,'boolean':1,'table':1},'may_be_incomplete':True})

    def test_nonfinite_numbers_never_reach_json(self):
        result=self.projects("{'A',0/0,math.huge,-math.huge}")
        self.assertEqual(result['projects'],['A'])
        self.assertEqual(result['normalization']['ignored_value_types'],{'number':3})

    def test_objects_are_never_stringified_into_names(self):
        result=self.projects("{'A',setmetatable({},{__tostring=function() error('must not stringify') end}),function() end}")
        self.assertEqual(result['projects'],['A'])
        self.assertEqual(result['normalization']['ignored_value_types'],{'table':1,'function':1})

    def test_all_nonstring_values_are_explicitly_incomplete(self):
        result=self.projects('{42,0,false}')
        self.assertEqual(result['projects'],[])
        self.assertTrue(result['normalization']['may_be_incomplete'])
        self.assertEqual(result['normalization']['ignored_entries'],3)

    def test_empty_table_is_a_complete_empty_array(self):
        result=self.projects('{}')
        self.assertEqual(result['projects'],[])
        self.assertFalse(result['normalization']['may_be_incomplete'])

    def test_input_limit_and_invalid_top_level_fail_explicitly(self):
        for expression in ['nil','42',"'invalid'","(function() local t={} for i=1,1001 do t[i]=i end return t end)()"]:
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(BridgeError,'API_ERROR'):self.projects(expression)
