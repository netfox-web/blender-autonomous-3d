"""Operator-reviewed batches using the existing serial composition queue.

Mutable progress is never publication authority. Versioned, write-once requests
and terminal receipts anchor identity; canonical generation verification supplies
availability. These local records do not authenticate a hostile filesystem owner.
"""
import json
import os
from uuid import UUID, uuid5

from pydantic import Field

from fox3d import model_compositions as compositions, product_models as models
from fox3d.ids import new_id, stable_hash
from fox3d.recipe_3d import atomic_json, input_hash, read_json

IDENTITY_VERSION = 1
TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted'}


class Batch(models.Strict):
    name: str = Field(min_length=1, max_length=120)
    selections: list[compositions.Selection] = Field(min_length=1, max_length=24)


def snapshot(root, tenant, item, value):
    batch = Batch.model_validate(value)
    if not batch.name.strip():
        raise ValueError('請填批次名稱')
    rows = [compositions.snapshot(root, tenant, item, s.model_dump()) for s in batch.selections]
    if len({(s['sku'].strip(), s['scene']) for s in rows}) != len(rows):
        raise ValueError('同一批次的款式名稱與場景不可重複')
    return {'batchVersion': 1, 'name': batch.name.strip(), 'selections': rows,
            'masterInputHash': item['inputHash'], 'masterRevision': item['revision']}


def _once(path, value):
    # Exclusive creation prevents replay/overwriting request and terminal facts.
    # A torn write is rejected by _load, never repaired from mutable progress.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+new_id()+'.tmp')
    try:
        atomic_json(temporary, value)
        os.link(temporary, path)  # Atomic publish; fails if already present.
    finally:
        temporary.unlink(missing_ok=True)


def _load(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (OSError, ValueError) as exc:
        raise ValueError('批次紀錄缺少或損壞，請重新核對後建立新批次') from exc


def _identity(request, tenant, mid, bid):
    if (set(request) != {'identityVersion', 'tenantId', 'masterId', 'batchId', 'sourceRevision', 'draft'}
            or request['identityVersion'] != IDENTITY_VERSION
            or request['tenantId'] != tenant or request['masterId'] != mid or request['batchId'] != bid):
        raise ValueError('批次來源身分不符')
    draft = request['draft']
    if draft['batchVersion'] != 1 or request['sourceRevision'] != draft['masterRevision']:
        raise ValueError('批次來源版本不符')
    selections = draft['selections']
    Batch.model_validate({'name': draft['name'], 'selections': [
        {k: s[k] for k in ('sku', 'scene', 'placements')} for s in selections]})
    rows = []
    for i, selection in enumerate(selections):
        if (selection['masterId'] != mid or selection['masterInputHash'] != draft['masterInputHash']
                or selection['masterRevision'] != draft['masterRevision']):
            raise ValueError('批次款式來源不符')
        sh = stable_hash(selection)
        rows.append({'index': i, 'generationId': str(uuid5(UUID(bid), stable_hash({'index': i, 'selection': sh}))),
                     'sku': selection['sku'], 'scene': selection['scene'], 'selectionHash': sh})
    return {'identityVersion': IDENTITY_VERSION, 'tenantId': tenant, 'masterId': mid,
            'batchId': bid, 'name': draft['name'], 'masterInputHash': draft['masterInputHash'],
            'sourceRevision': draft['masterRevision'], 'selectionHash': stable_hash(draft),
            'rowCount': len(rows)}, rows


def _row_receipt(identity, row, state, error=None):
    return {'batchIdentityHash': stable_hash(identity), 'row': row, 'state': state, 'error': error}


def _published(root, tenant, mid, row, selection, revision, item):
    manifest = compositions.generation(root, tenant, mid, row['generationId'], item)
    if (manifest.get('historyVersion') != 1 or manifest.get('sourceRevision') != revision
            or manifest.get('planHash') != row['selectionHash']
            or stable_hash(manifest['draft']) != row['selectionHash']
            or manifest.get('scene') != row['scene'] or manifest['draft'] != selection):
        raise ValueError('批次款式與已發布成果不符')
    return manifest


def current(root, tenant, mid, task_id, state):
    if not compositions.valid_generation(task_id):
        if task_id is not None or state != 'idle':
            raise ValueError('工作編號缺少或無效，無法核對批次')
        return None
    base = compositions.folder_for(root, tenant, mid)
    path = base/'batches'/(task_id+'.json')
    anchor = base/'batches'/task_id
    if not path.exists() and not anchor.exists():
        service = read_json(base/'state.json')
        if service.get('batchVersion') and state not in {'queued', 'running'}:
            raise ValueError('批次紀錄遺失，無法確認完成')
        return None  # Single-composition tasks have no batch record.
    try:
        request = _load(anchor/'request.json')
        identity, rows = _identity(request, tenant, mid, task_id)
        service = _load(base/'state.json')
        if (service.get('taskId') != task_id or service.get('inputHash') != input_hash(request['draft'])
                or service.get('state') != state or service.get('batchVersion') != 1):
            raise ValueError('批次與佇列請求不符')
        record = _load(path)
        if stable_hash({k: record[k] for k in identity}) != stable_hash(identity) or len(record['rows']) != len(rows):
            raise ValueError('批次身分或款式數量不符')
        item = models.get(root, tenant, mid)
        if state not in {'queued', 'running'} and not (anchor/'terminal.json').exists():
            if state == 'succeeded':
                raise ValueError('批次缺少完成紀錄')
            # A restart never replays work. Persist interruption separately from progress.
            _once(anchor/'terminal.json', {'batchIdentityHash': stable_hash(identity),
                                          'state': 'cancelled' if state == 'cancelled' else 'interrupted'})
        terminal = _load(anchor/'terminal.json') if (anchor/'terminal.json').exists() else None
        if terminal and (terminal.get('batchIdentityHash') != stable_hash(identity)
                         or terminal.get('state') not in TERMINAL
                         or (state == 'succeeded' and terminal['state'] != 'succeeded')):
            raise ValueError('批次結束紀錄不符')
        for row, expected, selection in zip(record['rows'], rows, request['draft']['selections']):
            if stable_hash({k: row[k] for k in expected}) != stable_hash(expected) or row['state'] not in TERMINAL | {'queued', 'running'}:
                raise ValueError('批次款式次序或身分不符')
            receipt_path = anchor/(str(expected['index'])+'.json')
            receipt = _load(receipt_path) if receipt_path.exists() else None
            if receipt:
                if (receipt.get('batchIdentityHash') != stable_hash(identity) or receipt.get('row') != expected
                        or receipt.get('state') not in TERMINAL
                        or (row['state'] in TERMINAL and row['state'] != receipt['state'])):
                    raise ValueError('批次款式結束紀錄不符')
                row.update(state=receipt['state'], error=receipt.get('error'))
            elif row['state'] in TERMINAL:
                raise ValueError('款式缺少完成或中斷紀錄')
            elif terminal:
                row.update(state='cancelled' if terminal['state'] == 'cancelled' else 'interrupted',
                           error='工作已中斷，未完成項目需重新加入批次。')
            row['available'] = False
            if row['state'] == 'succeeded':
                try:
                    _published(root, tenant, mid, expected, selection, identity['sourceRevision'], item)
                    row['available'] = True
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    row.update(state='failed', error='成果核對失敗：'+str(exc)[:500])
        if terminal and terminal['state'] == 'succeeded' and not all(r.get('state') == 'succeeded' for r in record['rows']):
            record['state'] = 'failed'
        else:
            record['state'] = terminal['state'] if terminal and state not in {'queued', 'running'} else state
        if state in {'failed', 'cancelled'} and record['state'] == 'succeeded':
            # Completion receipts preserve results, not a successful outer task
            # that never reached its commit point (or was explicitly cancelled).
            record['state'] = 'cancelled' if state == 'cancelled' else 'interrupted'
        record['available'] = bool(record['rows']) and all(r['available'] for r in record['rows'])
        return record
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('批次紀錄不完整，請重新核對後建立新批次') from exc


def generate(platform, tenant, mid, draft, *, revision=0, generation_id=None,
             on_job=None, cancel_flag=None):
    if 'batchVersion' not in draft:
        return compositions.generate(platform, tenant, mid, draft, revision=revision,
                                     generation_id=generation_id, on_job=on_job, cancel_flag=cancel_flag)
    bid = generation_id or new_id()
    if not compositions.valid_generation(bid):
        raise ValueError('無效批次編號')
    base = compositions.folder_for(platform.root, tenant, mid)/'batches'
    path = base/(bid+'.json'); anchor = base/bid
    request = {'identityVersion': IDENTITY_VERSION, 'tenantId': tenant, 'masterId': mid,
               'batchId': bid, 'sourceRevision': revision, 'draft': draft}
    identity, expected_rows = _identity(request, tenant, mid, bid)
    _once(anchor/'request.json', request)
    record = {**identity, 'rows': [{**r, 'state': 'queued', 'error': None} for r in expected_rows]}
    atomic_json(path, record)
    for row, expected, selection in zip(record['rows'], expected_rows, draft['selections']):
        if cancel_flag and cancel_flag.is_set():
            for pending, expected_pending in zip(record['rows'], expected_rows):
                if pending['state'] == 'queued':
                    _once(anchor/(str(expected_pending['index'])+'.json'),
                          _row_receipt(identity, expected_pending, 'cancelled'))
                    pending['state'] = 'cancelled'
            atomic_json(path, record)
            _once(anchor/'terminal.json', {'batchIdentityHash': stable_hash(identity), 'state': 'cancelled'})
            raise ValueError('已取消批次，完成的成果仍保留')
        try:
            item = models.get(platform.root, tenant, mid)
            if item['inputHash'] != draft['masterInputHash']:
                raise ValueError('母版已變更，請重新核對後送出')
            compositions.plan(platform.root, tenant, selection)
            row['state'] = 'running'; atomic_json(path, record)
            result = compositions.generate(platform, tenant, mid, selection, revision=revision,
                                           generation_id=row['generationId'], on_job=on_job, cancel_flag=cancel_flag)
            if not result['generated'] or result['stale'] or result['generationId'] != row['generationId']:
                raise ValueError('成果驗證未通過')
            _published(platform.root, tenant, mid, expected, selection, revision,
                       models.get(platform.root, tenant, mid))
            row['state'] = 'succeeded'
        except Exception as exc:
            row.update(state='cancelled' if cancel_flag and cancel_flag.is_set() else 'failed', error=str(exc)[:1000])
        _once(anchor/(str(expected['index'])+'.json'), _row_receipt(identity, expected, row['state'], row['error']))
        atomic_json(path, record)
    final = 'succeeded' if all(r['state'] == 'succeeded' for r in record['rows']) else (
        'cancelled' if cancel_flag and cancel_flag.is_set() else 'failed')
    _once(anchor/'terminal.json', {'batchIdentityHash': stable_hash(identity), 'state': final})
    if final != 'succeeded':
        raise ValueError('批次有未完成項目；已完成的成果仍保留，請查看每款結果')
    return record
