"""Operator-reviewed asset purpose, separate from source bytes and print calibration."""
from filelock import FileLock

from fox3d import print_assets
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.recipe_workbench import DraftConflict, timestamp

ROLES = {'UNCLASSIFIED':'待分類', 'REFERENCE':'商品參考圖／電商圖',
         'DIMENSION':'尺寸／結構圖', 'DIELINE':'刀模',
         'ARTWORK':'印刷圖稿', 'PACKAGING':'貼紙／吊卡／包裝'}


def folder(root, tenant, aid):
    return print_assets.workspace(root, tenant)/'assets'/print_assets.checked_id(aid)


def usage(root, tenant, meta):
    base=folder(root,tenant,meta['id'])
    record=read_json(base/'usage.json')
    role=record.get('role','UNCLASSIFIED')
    reviewed=role in ROLES and bool(record.get('note','').strip()) and record.get('revision',0)>0
    return {**record,'role':role if role in ROLES else 'UNCLASSIFIED',
            'revision':record.get('revision',0),'note':record.get('note',''),
            'label':ROLES.get(role,ROLES['UNCLASSIFIED']),
            'canUseForModel':reviewed and role=='ARTWORK',
            'canUseForPrint':reviewed and role=='ARTWORK',
            'physicalPrintValidated':False}


def decorate(root,tenant,meta):
    return {**meta,'usage':usage(root,tenant,meta)}


def listing(root,tenant):
    base=print_assets.workspace(root,tenant)/'assets'
    return [decorate(root,tenant,read_json(p)) for p in sorted(base.glob('*/asset.json'))]


def classify(root,tenant,aid,role,note,expected_revision):
    if role not in ROLES or not isinstance(note,str) or not note.strip() or len(note)>1500:
        raise ValueError('請選擇素材用途並填寫判定依據')
    meta,_=print_assets.asset(root,tenant,aid)
    base=folder(root,tenant,aid)
    with FileLock(str(base/'usage.lock'),timeout=10):
        previous=read_json(base/'usage.json')
        if previous.get('revision',0)!=expected_revision:
            raise DraftConflict('素材用途已變更，請重新載入後再儲存')
        record={'role':role,'note':note.strip(),'revision':expected_revision+1,
                'updatedAt':timestamp(),'assetSha256':aid,'authority':'OPERATOR_CLASSIFICATION_ONLY'}
        atomic_json(base/'usage-history'/f'{record["revision"]}.json',record)
        atomic_json(base/'usage.json',record)
    return decorate(root,tenant,meta)


def require_artwork(root,tenant,aid):
    meta,_=print_assets.asset(root,tenant,aid)
    state=usage(root,tenant,meta)
    if not state['canUseForModel']:
        raise ValueError(f'素材「{meta["name"]}」為{state["label"]}，不可作為套圖原稿；請在素材用途管理核對')
    return state
