import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('contract_worker',Path(__file__).resolve().parents[1]/'validation/contract_worker.py')
worker=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(worker)


class ContractReceiptTests(unittest.TestCase):
    def test_project_root_precedes_external_test_packages(self):
        with patch.object(sys,'path',['unrelated-site-packages']):
            worker.ensure_test_paths()
            self.assertEqual(sys.path[0],str(Path(SPEC.origin).parents[1]))

    def invoke(self,test):
        with tempfile.TemporaryDirectory() as folder:
            receipt=Path(folder)/'receipt.json'
            with patch.object(sys,'argv',['worker','--test','test_fixture.Fixture.test_one','--out',str(receipt)]), \
                 patch.object(worker.unittest.defaultTestLoader,'loadTestsFromName',return_value=unittest.TestSuite([test])):
                with contextlib.redirect_stderr(io.StringIO()):
                    code=worker.main()
            return code,json.loads(receipt.read_text())

    def test_success_requires_one_executed_case(self):
        code,receipt=self.invoke(unittest.FunctionTestCase(lambda:None))
        self.assertEqual(code,0);self.assertEqual(receipt['tests_run'],1);self.assertEqual(receipt['skipped'],0)

    def test_skip_is_not_acceptance(self):
        def skip():raise unittest.SkipTest('Unavailable runtime')
        code,receipt=self.invoke(unittest.FunctionTestCase(skip))
        self.assertEqual(code,1);self.assertEqual(receipt['status'],'failed');self.assertEqual(receipt['skipped'],1)

    def test_failure_is_not_acceptance(self):
        def fail():raise AssertionError('Expected validation fixture failure')
        code,receipt=self.invoke(unittest.FunctionTestCase(fail))
        self.assertEqual(code,1);self.assertEqual(receipt['failures'],1)

    def test_arbitrary_module_expression_rejected(self):
        with patch.object(sys,'argv',['worker','--test','os.system','--out','unused.json']):
            with self.assertRaises(ValueError):worker.main()
