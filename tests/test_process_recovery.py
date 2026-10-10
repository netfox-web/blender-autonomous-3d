"""REAL_PROCESS_RECOVERY subprocesses; CI artifacts/verifier remain MOCK.

Formal local runs use the same helper with real Blender and full verification.
Windows Case D also uses a real OS handle (REAL_OS_IO).
"""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('batch_process_recovery',ROOT/'tests/helpers/batch_process_recovery.py')
harness=importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


@pytest.mark.parametrize('case',['A','A_PROGRESS','B','C','D'])
def test_actual_child_kill_and_fresh_process_recovery(tmp_path,case,record_property):
    if case=='D' and sys.platform!='win32':
        pytest.skip('Windows delete-sharing hard-kill integration only')
    result=harness.run_case(tmp_path/'case',ROOT,case,mock=True)
    record_property('REAL_PROCESS_RECOVERY',json.dumps(result))
    assert result['status']=='PASS',result
    assert result['childPid']!=result['restartPid']
    if case=='D':
        assert result['hardKillOrphanCleanup']=='PARTIAL_NOT_SCAVENGED'
        assert any(name.startswith('state.json.') for name in result['beforeRestart']['orphanTemps'])
