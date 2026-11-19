"""Read-only, tenant-scoped pilot batch API."""
import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.pilot_batch import run_pilot_batch_scenario
from fox3d.platform import Platform
from tests.test_pilot_batch import _built_unit, _eco_change, _manual_launch_ready, _ops


def test_batch_queries(tmp_path):
    plat = Platform(root=tmp_path / 'live', mock_blender=True)
    run_pilot_batch_scenario(plat, tenant_a='pa', tenant_b='pb')
    client = TestClient(create_app(plat))
    headers = {'X-Tenant-Id': 'pa'}
    expected = sorted(plat.pilot_batch.batches)
    ids = []
    for offset in range(len(expected)):
        result = client.get('/api/pilot/batches', params={'offset': offset, 'limit': 1}, headers=headers).json()
        assert result['total'] == len(expected)
        ids.extend(x['batchId'] for x in result['items'])
    assert ids == expected
    bid = ids[0]
    row = client.get('/api/pilot/batches/' + bid, headers=headers).json()
    assert row['batchId'] == bid and row['liveMachineControl'] is False
    assert all(x['state'] == row['state'] for x in client.get('/api/pilot/batches', params={'state': row['state']}, headers=headers).json()['items'])
    assert client.get('/api/pilot/batches', params={'limit': 101}, headers=headers).status_code == 422
    units = client.get(f'/api/pilot/batches/{bid}/units', params={'limit': 2}, headers=headers).json()
    assert units['total'] == 5 and len(units['items']) == 2 and 'qc' in units['items'][0]
    assert client.get(f'/api/pilot/batches/{bid}/genealogy', headers=headers).json()['units']
    for target in (bid, 'unknown'):
        for suffix in ('', '/units', '/readiness', '/genealogy'):
            response = client.get(f'/api/pilot/batches/{target}{suffix}', headers={'X-Tenant-Id': 'pb'})
            assert response.status_code == 404 and response.json() == {'detail': '找不到批次'}
            assert 'KeyError' not in response.text
    path = plat.pilot_batch.root / 'pilot_batch.json'
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    ready = client.get(f'/api/pilot/batches/{bid}/readiness', headers=headers)
    assert ready.status_code == 200 and ready.json()['liveMachineControl'] is False
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    reloaded = Platform(root=tmp_path / 'live', mock_blender=True)
    assert reloaded.pilot_batch.get(bid, tenant_id='pa') == plat.pilot_batch.get(bid, tenant_id='pa')


def test_eco_is_reported_without_writing(tmp_path):
    plat = Platform(root=tmp_path / 'live', mock_blender=True)
    from fox3d.portfolio import run_portfolio_scenario
    run_portfolio_scenario(plat, tenant_a='pa', tenant_b='pb')
    fixture, shift, human, human_shift = _ops(plat)
    cand, unit, _, _ = _built_unit(plat, fixture=fixture, shift=shift, human=human, human_shift=human_shift)
    _manual_launch_ready(plat, cand, unit, human, human_shift)
    plat.prototype.record_launch_decision(cand['candidateId'], tenant_id='pa', operator_id=human['operatorId'], shift_id=human_shift['shiftId'], decision='HUMAN_GO', reason='go')
    batch = plat.pilot_batch.create(cand['candidateId'], tenant_id='pa', operator_id=human['operatorId'], shift_id=human_shift['shiftId'], quantity=2, source='MANUAL', reason='eco')
    plat.prototype.create_eco(cand['candidateId'], tenant_id='pa', operator_id=human['operatorId'], shift_id=human_shift['shiftId'], reason='change', changes=_eco_change(cand))
    path = plat.pilot_batch.root / 'pilot_batch.json'
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    result = TestClient(create_app(plat)).get(f"/api/pilot/batches/{batch['batchId']}/readiness", headers={'X-Tenant-Id': 'pa'}).json()
    assert result['staleLineage'] is True and 'stale_lineage' in result['blockers']
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("suffix", ("", "/missing", "/missing/units", "/missing/readiness", "/missing/genealogy"))
@pytest.mark.parametrize("header", (None, "", "  ", "../invalid"))
def test_batch_header_validation(platform, suffix, header):
    headers = {} if header is None else {"X-Tenant-Id": header}
    response = TestClient(create_app(platform)).get('/api/pilot/batches' + suffix, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "X-Tenant-Id 無效"}
