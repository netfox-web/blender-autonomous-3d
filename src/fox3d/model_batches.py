"""Operator-reviewed batches using the same serial queue as single compositions."""
from pydantic import Field

from fox3d import model_compositions as compositions, product_models as models
from fox3d.ids import new_id, stable_hash
from fox3d.recipe_3d import atomic_json, read_json


class Batch(models.Strict):
    name: str = Field(min_length=1, max_length=120)
    selections: list[compositions.Selection] = Field(min_length=1, max_length=24)


def snapshot(root, tenant, item, value):
    batch = Batch.model_validate(value)
    if not batch.name.strip():
        raise ValueError('請填批次名稱')
    rows = [compositions.snapshot(root, tenant, item, s.model_dump()) for s in batch.selections]
    if len({(s['sku'].strip(), s['scene'], s.get('placement','AUTO'), s.get('view','THREE_QUARTER')) for s in rows}) != len(rows):
        raise ValueError('同一批次的款式、場景、位置與視角不可重複')
    return {'batchVersion': 1, 'name': batch.name.strip(), 'selections': rows,
            'masterInputHash': item['inputHash'], 'masterRevision': item['revision']}


def current(root, tenant, mid, task_id, state):
    # task_id is a server-generated ID, but persisted state is still untrusted.
    if not compositions.valid_generation(task_id):
        return None
    record = read_json(compositions.folder_for(root, tenant, mid)/'batches'/(task_id+'.json'))
    if not record:
        return None
    if state not in {'queued', 'running'}:
        for row in record['rows']:
            if row['state'] in {'queued', 'running'}:
                row.update(state='cancelled' if state == 'cancelled' else 'interrupted',
                           error='工作已中斷，未完成項目需重新加入批次。')
    return record


def generate(platform, tenant, mid, draft, *, revision=0, generation_id=None,
             on_job=None, cancel_flag=None):
    if 'batchVersion' not in draft:
        return compositions.generate(platform, tenant, mid, draft, revision=revision,
                                     generation_id=generation_id, on_job=on_job, cancel_flag=cancel_flag)
    bid = generation_id or new_id()
    path = compositions.folder_for(platform.root, tenant, mid)/'batches'/(bid+'.json')
    record = {'batchId': bid, 'name': draft['name'], 'masterInputHash': draft['masterInputHash'],
              'sourceRevision': revision, 'selectionHash': stable_hash(draft),
              'rows': [{'sku': s['sku'], 'scene': s['scene'], 'view':s.get('view','THREE_QUARTER'), 'placement':s.get('placement','AUTO'), 'state': 'queued',
                        'generationId': new_id(), 'error': None} for s in draft['selections']]}
    atomic_json(path, record)
    for row, selection in zip(record['rows'], draft['selections']):
        if cancel_flag and cancel_flag.is_set():
            for pending in record['rows']:
                if pending['state'] == 'queued':
                    pending['state'] = 'cancelled'
            atomic_json(path, record)
            raise ValueError('已取消批次，完成的成果仍保留')
        try:
            item = models.get(platform.root, tenant, mid)
            if item['inputHash'] != draft['masterInputHash']:
                raise ValueError('母版已變更，請重新核對後送出')
            # Recheck classification and aspect just before each render.
            compositions.plan(platform.root, tenant, selection)
            row['state'] = 'running'
            atomic_json(path, record)
            result = compositions.generate(platform, tenant, mid, selection, revision=revision,
                                          generation_id=row['generationId'], on_job=on_job,
                                          cancel_flag=cancel_flag)
            if not result['generated'] or result['stale'] or result['generationId'] != row['generationId']:
                raise ValueError('成果驗證未通過')
            row['state'] = 'succeeded'
        except Exception as exc:
            row.update(state='cancelled' if cancel_flag and cancel_flag.is_set() else 'failed',
                       error=str(exc)[:1000])
        atomic_json(path, record)
    if any(r['state'] != 'succeeded' for r in record['rows']):
        raise ValueError('批次有未完成項目；已完成的成果仍保留，請查看每款結果')
    return record
