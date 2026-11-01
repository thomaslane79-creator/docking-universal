"""Run one explicitly named regression contract with a strict local receipt.

Fixture/mocked contracts are not represented as native or scientific runs.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import unittest


def ensure_test_paths():
    # Direct script execution puts validation/, not the project root, on
    # sys.path. Some existing contracts deliberately share tests.* fixtures.
    # Resolve those from this checkout, not an unrelated installed tests package.
    project=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(project))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'test_[a-z0-9_]+\.[A-Za-z0-9_]+\.test_[a-z0-9_]+',args.test):
        raise ValueError('Use one explicit local test identifier')
    ensure_test_paths()
    suite = unittest.defaultTestLoader.loadTestsFromName(args.test)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun==1 and result.wasSuccessful() and not result.skipped
    args.out.write_text(json.dumps({'status':'passed' if passed else 'failed',
                                   'test':args.test,'tests_run':result.testsRun,
                                   'skipped':len(result.skipped),'failures':len(result.failures),
                                   'errors':len(result.errors),
                                   'coverage':'Focused source-code contract; may use scientific fixtures/mocked services; not a fresh native pipeline'},indent=2)+'\n')
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
