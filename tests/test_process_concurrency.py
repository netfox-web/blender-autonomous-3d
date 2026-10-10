"""REAL_PROCESS_CONCURRENCY; CI render artifacts/validation remain MOCK."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/helpers'))
spec=importlib.util.spec_from_file_location('batch_process_concurrency',ROOT/'tests/helpers/batch_process_concurrency.py')
harness=importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@pytest.mark.parametrize('case',list('ABCDEF'))
def test_independent_service_process_ownership(tmp_path,case,record_property):
    result=harness.run_case(tmp_path/'race',ROOT,case)
    record_property('REAL_PROCESS_CONCURRENCY',json.dumps(result))
    assert result['status']=='PASS',result
    assert len({child['pid'] for child in result['children'].values()})==len(result['children'])
    for child in result['children'].values():
        if not child['submit']['accepted']:
            assert child['renderEntries']==[] and child['writes']==[]
