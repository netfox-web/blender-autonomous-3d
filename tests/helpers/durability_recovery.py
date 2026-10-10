"""Real flush/kill/restart harness. Rendered artifacts are MOCK in this harness."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from batch_process_concurrency import fixture
from batch_process_recovery import save, read, mock_artifacts


def facts(base):
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob('*.json')) if p.name != 'state.json'}


def child(args):
    from fox3d import durability as d, recipe_3d as r, model_batches as b, model_compositions as c
    from fox3d.preview_ownership import PreviewOwnership
    from fox3d.recipe_preview_service import RecipePreviewService
    context = read(args.root/'context.json'); tenant = context['tenant']; model = context['model']
    draft = context['drafts']['same']; data = args.root/'d'
    base = c.folder_for(data, tenant, model['id']); bid = '12345678-1234-4234-8234-123456789012'
    state = {'taskId': bid, 'inputHash': r.input_hash(draft), 'batchVersion': 1,
             'state': 'running', 'progress': 10, 'error': None}
    if args.action == 'write':
        events = []; original_flush = d.flush_file; original_sync = d.sync_directory
        original_committed = d.namespace_committed
        def checkpoint():
            save(args.root/'reached.json', {'pid': os.getpid(), 'events': events, 'facts': facts(base)})
            threading.Event().wait()
        def flush(stream):
            original_flush(stream)
            events.append({'kind': 'file', 'path': str(stream.name), 'success': True,
                           'mechanism': 'FlushFileBuffers' if sys.platform == 'win32' else 'fsync'})
            if args.case == 'D1' and Path(stream.name).name.startswith('state.json.'):
                checkpoint()
        def sync(directory):
            original_sync(directory)
            events.append({'kind': 'directory', 'path': str(directory), 'success': True,
                           'mechanism': 'NTFS directory FlushFileBuffers' if sys.platform == 'win32' else 'directory fd fsync'})
        def committed(path, operation):
            original_committed(path, operation)
            events.append({'kind': 'namespace', 'operation': operation, 'path': str(path), 'success': True})
        d.flush_file = flush; d.sync_directory = sync; d.namespace_committed = committed
        mock_artifacts()
        with PreviewOwnership(base):
            r.atomic_json(base/'state.json', state)
            b.generate(SimpleNamespace(root=data), tenant, model['id'], draft,
                       revision=model['revision'], generation_id=bid)
            assert args.case == 'D5'
            checkpoint()
        raise AssertionError('kill checkpoint not reached')
    real_generate = c.generate
    mock_artifacts()  # Artifact validator only; real authority readers remain unchanged.
    def no_replay(*a, **kw):
        save(args.root/'unexpected-replay.json', {'called': True})
        raise AssertionError('recovery must never replay')
    c.generate = no_replay
    before = facts(base)
    service = RecipePreviewService(SimpleNamespace(root=data), folder_fn=c.folder_for,
                                   status_fn=c.status, generate_fn=b.generate)
    try:
        service.status(tenant, model['id'], model)
    finally:
        service.executor.shutdown()
    result = {'pid': os.getpid(), 'platform': platform.platform(), 'before': before}
    if args.case == 'D1':
        result['finalAbsent'] = not (base/'state.json').exists()
        result['tempsAbsent'] = not list(base.glob('state.json.*.tmp'))
        assert result['finalAbsent'] and result['tempsAbsent']
    else:
        outer = r.read_json(base/'state.json')
        record = b.current(data, tenant, model['id'], bid, outer['state'])
        assert record['state'] == 'interrupted' and record['available']
        anchor = base/'batches'/bid
        result['receipts'] = {p.name: b._load(p) for p in anchor.glob('*.json')}
        assert set(result['receipts']) == {'request.json', '0.json', 'terminal.json'}
        assert result['receipts']['terminal.json']['state'] == 'succeeded'
        result['duplicateReceiptsBlocked'] = []
        for path in anchor.glob('*.json'):
            try: b._once(path, {'duplicate': 'must fail'})
            except FileExistsError: result['duplicateReceiptsBlocked'].append(path.name)
            else: raise AssertionError('immutable overwrite')
        gid = record['rows'][0]['generationId']
        try:
            real_generate(SimpleNamespace(root=data, mock_blender=False, runtime=SimpleNamespace(available=lambda: True)),
                          tenant, model['id'], draft['selections'][0], revision=model['revision'], generation_id=gid)
        except FileExistsError: result['duplicateGenerationBlocked'] = True
        else: raise AssertionError('duplicate generation')
        original = (base/'state.json').read_bytes()
        with PreviewOwnership(base) as owner:
            try: service._write_owned(base/'state.json', {**outer, 'taskId': 'stale-owner'}, owner)
            except ValueError: result['staleWriterBlocked'] = True
            else: raise AssertionError('stale writer accepted')
        assert (base/'state.json').read_bytes() == original
        result['record'] = record
    result['after'] = facts(base)
    result['noReplay'] = not (args.root/'unexpected-replay.json').exists()
    assert result['after'] == before and result['noReplay']
    save(args.root/'recovered.json', result)


def run_case(root, code_root, case):
    root = Path(root).resolve(); code_root = Path(code_root).resolve(); root.mkdir(parents=True, exist_ok=False)
    fixture(root)
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--root', str(root),
               '--code-root', str(code_root), '--case', case]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with (root/'writer.log').open('w', encoding='utf-8') as output:
        proc = subprocess.Popen(command+['--action', 'write'], stdout=output, stderr=output, creationflags=flags)
        try:
            deadline = time.monotonic()+60
            while not (root/'reached.json').exists():
                if proc.poll() is not None: raise AssertionError((root/'writer.log').read_text(encoding='utf-8'))
                if time.monotonic()>deadline: raise TimeoutError('flush checkpoint not reached')
                time.sleep(.01)
            reached = read(root/'reached.json')
            proc.kill(); proc.wait(timeout=15)
            assert proc.returncode != 0
        finally:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=15)
    process = subprocess.run(command+['--action', 'recover'], capture_output=True, text=True,
                             encoding='utf-8', timeout=60, creationflags=flags)
    (root/'recover.log').write_text(process.stdout+process.stderr, encoding='utf-8')
    assert process.returncode == 0, process.stderr
    recovered = read(root/'recovered.json')
    assert recovered['pid'] != proc.pid and any(e['kind']=='file' for e in reached['events'])
    if case == 'D5':
        assert {'replace','link','unlink'} <= {e.get('operation') for e in reached['events']}
        assert any(e['kind']=='directory' for e in reached['events'])
    result = {'case': case, 'status': 'PASS', 'killedPid': proc.pid, 'exitCode': proc.returncode,
              'checkpoint': reached, 'recovered': recovered, 'platform': platform.platform(),
              'classification': 'REAL_PROCESS_RECOVERY + REAL_OS_IO_FLUSH; MOCK artifacts/validation, no power-loss evidence'}
    save(root/'evidence.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ['root','code-root']: parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--action', choices=['write','recover'], required=True)
    parser.add_argument('--case', choices=['D1','D5'], required=True)
    args = parser.parse_args(); sys.path.insert(0, str(args.code_root/'src')); child(args)
