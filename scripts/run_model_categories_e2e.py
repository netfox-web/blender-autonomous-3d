"""Clean-code HTTP/Blender proof that classification does not invalidate model outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    import httpx
    from fox3d import product_models, model_compositions, recipe_3d
    from fox3d.blender import find_blender
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-dirty', action='store_true')
    parser.add_argument('--keep-server', action='store_true')
    args = parser.parse_args()
    clean = not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
    if not clean and not args.allow_dirty:
        raise SystemExit('Formal evidence requires clean CODE')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    eid = str(uuid.uuid4()); base = ROOT / '.fox3d-work' / 'category-e2e' / eid[:8]
    base.mkdir(parents=True); data = base / 'd'; tenant = 'sonaqueen-home'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'; log = (base / 'server.log').open('w', encoding='utf-8')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0); proc = None
    command = [sys.executable, str(ROOT / 'scripts/run_recipe_admin.py'), '--port', str(port), '--data-root', str(data)]
    def start():
        child = subprocess.Popen(command, cwd=ROOT, env={**os.environ, 'FOX3D_MOCK_BLENDER': '0', 'PYTHONIOENCODING': 'utf-8'},
                                 stdout=log, stderr=log, creationflags=flags)
        for _ in range(120):
            if child.poll() is not None:
                raise RuntimeError('Server exited during startup')
            try:
                if httpx.get(url + '/api/recipe-library/health', trust_env=False, timeout=1).status_code == 200:
                    return child
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        child.terminate(); child.wait(timeout=30)
        raise RuntimeError('Server startup timeout')
    evidence = {'evidenceId': eid, 'codeCommit': sha, 'workingTreeClean': clean, 'developmentOnly': args.allow_dirty,
                'inputTruth': 'SYNTHETIC_RECTANGLE_FIXTURE', 'physicalPrintValidated': False, 'globalProductionReady': False}
    try:
        proc = start()
        with httpx.Client(base_url=url, headers={'X-Tenant-Id': tenant}, trust_env=False, timeout=120) as client:
            def get(path):
                r = client.get('/api/product-models' + path); r.raise_for_status(); return r.json()
            def post(path, payload):
                r = client.post('/api/product-models' + path, json=payload); r.raise_for_status(); return r.json()
            assert get('')['items'] == [] and get('')['categoryTree']
            item = post('', {'expectedRevision': 0, 'draft': {'name': 'FIXTURE mat', 'family': 'mat', 'geometry': 'RECTANGLE',
                'widthMm': 100., 'heightMm': 100., 'depthMm': 5., 'dimensionEvidence': 'Synthetic fixture, not product measurements',
                'structureEvidence': 'Synthetic flat square, no physical validation'}})
            mid = item['id']; master = product_models.directory(data, tenant) / mid / 'master.json'; original = master.read_bytes()
            identities = {}; artifacts = {}
            for mode in ['preview', 'composition']:
                payload = {'expectedRevision': 1, 'inputHash': item['inputHash'], 'assumptionsAccepted': True}
                if mode == 'composition': payload['selection'] = {'sku': 'FIXTURE', 'scene': 'WARM_ROOM', 'placements': []}
                post('/' + mid + '/' + mode, payload)
                deadline = time.monotonic() + 660
                while time.monotonic() < deadline:
                    state = get('/' + mid + '/' + mode)
                    if state['state'] not in {'queued', 'running'}: break
                    time.sleep(2)
                assert state['state'] == 'succeeded' and state['generated'] and not state['stale'], state
                identities[mode] = state['generationId']
                folder = (product_models.folder(data, tenant, mid) if mode == 'preview' else model_compositions.folder_for(data, tenant, mid)) / 'generations' / state['generationId']
                checker = 'check_product_model_blend.py' if mode == 'preview' else 'check_print_blend.py'
                reopened = subprocess.run([find_blender(), '-b', str(folder / 'model.blend'), '--python-exit-code', '1', '--python', str(ROOT / 'scripts' / checker), '--', str(folder)],
                    capture_output=True, timeout=120, creationflags=flags)
                (base / (mode + '-reopen.log')).write_bytes(reopened.stdout + reopened.stderr)
                assert reopened.returncode == 0 and b'BLEND_REOPEN_PASS' in reopened.stdout
                artifacts[mode] = {}
                for name in ['beauty.png', 'model.blend', 'model.glb', 'geometry.json']:
                    raw = (folder / name).read_bytes(); artifacts[mode][name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}
                evidence[mode] = {'generationId': state['generationId'], 'renderInfo': state.get('renderInfo') or state['manifest']['renderInfo'], 'reopenPassed': True}
            classify_url = '/api/product-models/' + mid + '/classification'
            response = client.put(classify_url, json={'categoryId': 'wash_mat', 'expectedRevision': 0}); response.raise_for_status()
            assert client.put(classify_url, json={'categoryId': 'floor_mat', 'expectedRevision': 0}).status_code == 409
            assert master.read_bytes() == original
            proc.terminate(); proc.wait(timeout=30); proc = start()
            assert get('/' + mid + '/classification')['categoryId'] == 'wash_mat'
            listed = get('')['items']; assert len(listed) == 1 and listed[0]['templateState'] == 'PREVIEW_AVAILABLE'
            assert listed[0]['inputHash'] == item['inputHash'] and listed[0]['revision'] == 1
            for mode, generation in identities.items():
                state = get('/' + mid + '/' + mode)
                assert state['generated'] and not state['stale'] and state['generationId'] == generation
                names = {'png': 'beauty.png', 'blend': 'model.blend', 'glb': 'model.glb', 'geometry': 'geometry.json'} if mode == 'preview' else {name: name for name in artifacts[mode]}
                prefix = '/' + mid + ('/files/' if mode == 'preview' else '/composition/files/')
                for key, name in names.items():
                    r = client.get('/api/product-models' + prefix + key, params={'workspace': tenant, 'generation': generation}); r.raise_for_status()
                    assert hashlib.sha256(r.content).hexdigest() == artifacts[mode][name]['sha256'] and len(r.content) == artifacts[mode][name]['sizeBytes']
            assert master.read_bytes() == original
            evidence.update(status='PASS',classificationPersisted=True,modelBytesUnchanged=True,modelInputHashUnchanged=True,
                sameGenerationIds=identities,downloadsPreserved=True,restartVerified=True,staleClassificationRejected=True,artifacts=artifacts)
        if args.keep_server: recipe_3d.atomic_json(base / 'dev-server.json', {'url': url, 'pid': proc.pid, 'dataRoot': str(data)})
    except Exception as exc:
        evidence.update(status='FAIL', error=str(exc)); raise
    finally:
        if proc and proc.poll() is None and (not args.keep_server or evidence.get('status') != 'PASS'):
            proc.terminate(); proc.wait(timeout=30)
        recipe_3d.atomic_json(base / 'evidence.json', evidence); log.close()
        print(json.dumps({'evidenceFile': str(base / 'evidence.json'), 'status': evidence.get('status'), 'url': url}), flush=True)


if __name__ == '__main__':
    main()
