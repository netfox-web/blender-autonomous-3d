"""Actual hard-kill/link/lock evidence; artifact fixtures remain MOCK only."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from batch_process_recovery import save, read, digest, mock_artifacts
from batch_process_concurrency import fixture


def inventory(base):
    result = {}
    for path in sorted(base.rglob('*')):
        st = path.lstat()
        regular = stat.S_ISREG(st.st_mode)
        result[path.relative_to(base).as_posix()] = {
            'type': 'file' if regular else 'directory' if stat.S_ISDIR(st.st_mode) else 'other',
            'links': st.st_nlink, 'inode': st.st_ino, 'device': st.st_dev,
            'size': st.st_size, 'sha256': digest(path) if regular and path.name != 'owner.lock' else None,
            'bytesHex': path.read_bytes().hex() if regular and path.suffix in {'.json', '.tmp'} else None,
        }
    return result


def child(args):
    from fox3d import model_batches as b, model_compositions as c
    from fox3d.recipe_3d import atomic_json, input_hash, read_json
    from fox3d.recipe_preview_service import RecipePreviewService
    from fox3d.preview_ownership import PreviewOwnership
    from fox3d.ids import new_id
    ctx = read(args.root/'context.json'); tenant = ctx['tenant']; model = ctx['model']
    base = c.folder_for(args.root/'d', tenant, model['id'])
    mock_artifacts()
    if args.action == 'write':
        bid = new_id(); draft = ctx['drafts']['same']; anchor = base/'batches'/bid
        final = anchor/args.target
        save(args.root/'target.json', {'batchId': bid, 'target': str(final), 'workspace': str(base)})
        def checkpoint(temp):
            save(args.root/'reached.json', {'pid': os.getpid(), 'window': args.window,
                'target': str(final), 'temp': str(temp), 'inventory': inventory(base)})
            threading.Event().wait()
        link = os.link
        def paused_link(source, target, *a, **kw):
            if Path(target) == final and args.window == 'W1': checkpoint(source)
            result = link(source, target, *a, **kw)
            if Path(target) == final and args.window == 'W2': checkpoint(source)
            return result
        os.link = paused_link
        original_once = b._once
        def watched_once(path, value):
            if path == final and args.window == 'W3':
                replace = Path.replace
                def paused_replace(nested, target):
                    if Path(target).parent == final.parent and Path(target).suffix == '.tmp':
                        checkpoint(nested)
                    return replace(nested, target)
                Path.replace = paused_replace
            return original_once(path, value)
        b._once = watched_once
        with PreviewOwnership(base):
            atomic_json(base/'state.json', {'taskId': bid, 'state': 'running', 'progress': 10,
                'inputHash': input_hash(draft), 'batchVersion': 1, 'error': None})
            save(args.root/'before.json', inventory(base))
            b.generate(SimpleNamespace(root=args.root/'d'), tenant, model['id'], draft,
                revision=model['revision'], generation_id=bid)
        raise AssertionError('hard-kill window not reached')
    info = read(args.root/'target.json'); final = Path(info['target'])
    before = inventory(base); result = {'pid': os.getpid(), 'before': before}
    def no_render(*a, **kw):
        save(args.root/'unexpected-replay.json', {'called': True})
        raise AssertionError('recovery must never replay')
    c.generate = no_render
    if args.action == 'recover':
        # Verify final independently, before cleanup. W2 is a published fact even
        # when its extra hard link must be preserved as ambiguous debris.
        result['finalVerified'] = False
        if final.exists():
            value = b._load(final)
            request = b._load(final.parent/'request.json')
            identity, rows = b._identity(request, tenant, model['id'], info['batchId'])
            if args.target == 'request.json': assert value == request
            else:
                from fox3d.ids import stable_hash
                assert value['batchIdentityHash'] == stable_hash(identity)
                if args.target == '0.json': assert value['row'] == rows[0]
                assert value['state'] == 'succeeded'
            result['finalVerified'] = True
            original = final.read_bytes()
            try: b._once(final, {'must': 'never overwrite'})
            except FileExistsError: result['duplicateBlocked'] = True
            else: raise AssertionError('duplicate publish accepted')
            result['finalBytesPreserved'] = final.read_bytes() == original
        service = RecipePreviewService(SimpleNamespace(root=args.root/'d'), folder_fn=c.folder_for,
            status_fn=c.status, generate_fn=b.generate)
        try:
            outer = service.status(tenant, model['id'], model)
            result['outer'] = outer
            try: result['batch'] = b.current(args.root/'d', tenant, model['id'], info['batchId'], outer['state'])
            except (ValueError, OSError) as exc: result['recoveryError'] = {'type': type(exc).__name__, 'message': str(exc)}
        finally: service.executor.shutdown()
        result['outerPersisted'] = read_json(base/'state.json')
    elif args.action == 'competitor':
        try:
            with PreviewOwnership(base) as owner:
                b.scavenge_once_temps([final], owner)
                b._once(final, {'unexpected': 'write'})
        except ValueError as exc: result['blocked'] = type(exc).__name__
    result['after'] = inventory(base)
    result['unexpectedReplay'] = (args.root/'unexpected-replay.json').exists()
    save(args.root/(args.action+'.json'), result)


def run_case(root, code_root, window, target):
    root = Path(root).resolve(); code_root = Path(code_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    # The parent imports only fixture helpers; every production operation in the
    # child is imported from the exact requested checkout.
    fixture(root)
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--root', str(root),
        '--code-root', str(code_root), '--window', window, '--target', target]
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    env = {**os.environ, 'FOX3D_MOCK_BLENDER': '1'}
    with (root/'writer.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(command+['--action', 'write'], stdout=log, stderr=log, env=env, creationflags=flags)
        try:
            until = time.monotonic()+60
            while not (root/'reached.json').exists():
                if proc.poll() is not None: raise AssertionError((root/'writer.log').read_text(encoding='utf-8'))
                if time.monotonic()>until: raise TimeoutError('window not reached')
                time.sleep(.01)
            reached = read(root/'reached.json'); base = Path(read(root/'target.json')['workspace'])
            # A live competing process cannot obtain ownership; zero cleanup/write.
            with (root/'competitor.log').open('w', encoding='utf-8') as out:
                subprocess.run(command+['--action', 'competitor'], stdout=out, stderr=out, env=env,
                    check=True, timeout=30, creationflags=flags)
            competitor = read(root/'competitor.json')
            assert competitor['blocked'] == 'PreviewBusy' and competitor['before'] == competitor['after']
            proc.kill(); proc.wait(timeout=15)
            assert proc.returncode != 0
        finally:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=15)
    post = inventory(base); save(root/'post-kill.json', post)
    with (root/'recover.log').open('w', encoding='utf-8') as log:
        p = subprocess.run(command+['--action', 'recover'], stdout=log, stderr=log, env=env, timeout=60, creationflags=flags)
    if p.returncode: raise AssertionError((root/'recover.log').read_text(encoding='utf-8'))
    recovered = read(root/'recover.json'); final = Path(read(root/'target.json')['target'])
    temp = Path(reached['temp']); rel = temp.relative_to(base).as_posix()
    assert rel in post and recovered['pid'] != proc.pid and not recovered['unexpectedReplay']
    assert recovered['outerPersisted']['state'] == 'failed'
    assert recovered.get('batch', {}).get('state') != 'succeeded'
    if window == 'W2':
        assert recovered['finalVerified'] and recovered['duplicateBlocked'] and recovered['finalBytesPreserved']
        f = post[final.relative_to(base).as_posix()]; t = post[rel]
        assert f['sha256'] == t['sha256'] and f['inode'] == t['inode'] and t['links'] == 2
    else: assert final.relative_to(base).as_posix() not in post
    # All pre-existing immutable publication facts survive restart byte-for-byte.
    facts = {n:v for n,v in post.items() if n.endswith('.json') and
        ('/batches/' in '/'+n or '/generations/' in '/'+n)}
    assert all(recovered['after'].get(n, {}).get('sha256') == v['sha256'] for n,v in facts.items())
    result = {'window': window, 'target': target, 'status': 'PASS', 'killedPid': proc.pid,
        'exitCode': proc.returncode, 'before': read(root/'before.json'), 'checkpoint': reached,
        'postKill': post, 'recovered': recovered, 'competitor': competitor,
        'orphanRelativePath': rel, 'orphanPreserved': rel in recovered['after'],
        'classification': 'REAL_PROCESS_RECOVERY + REAL_OS_IO; MOCK artifact validation, no REAL_RENDER'}
    save(root/'evidence.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ['root', 'code-root']: parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--window', choices=['W1', 'W2', 'W3'], required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--action', choices=['write', 'recover', 'competitor'], required=True)
    args = parser.parse_args(); sys.path.insert(0, str(args.code_root/'src'))
    child(args)
