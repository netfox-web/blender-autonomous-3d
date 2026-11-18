"""Operator-reviewed asset purpose, separate from source bytes and print calibration."""
import json
import logging
import re
from filelock import FileLock

from fox3d import print_assets
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.recipe_workbench import DraftConflict, timestamp

LOG = logging.getLogger(__name__)

ROLES = {'UNCLASSIFIED':'待分類', 'REFERENCE':'商品參考圖／電商圖',
         'DIMENSION':'尺寸／結構圖', 'DIELINE':'刀模',
         'ARTWORK':'印刷圖稿', 'PACKAGING':'貼紙／吊卡／包裝'}


class AssetList(list):
    skipped: int = 0
    total: int = 0


def folder(root, tenant, aid):
    return print_assets.workspace(root, tenant)/'assets'/print_assets.checked_id(aid)


def usage(root, tenant, meta):
    base=folder(root,tenant,meta['id'])
    record=read_json(base/'usage.json')
    if not isinstance(record,dict):
        record={}
    role=record.get('role','UNCLASSIFIED')
    note=record.get('note','')
    if not isinstance(note,str):
        note=''
    rev=record.get('revision',0)
    if not isinstance(rev,int) or isinstance(rev,bool) or rev<0:
        rev=0
    reviewed=role in ROLES and bool(note.strip()) and rev>0
    return {**record,'role':role if role in ROLES else 'UNCLASSIFIED',
            'revision':rev,'note':note,
            'label':ROLES.get(role,ROLES['UNCLASSIFIED']),
            'canUseForModel':reviewed and role=='ARTWORK',
            'canUseForPrint':reviewed and role=='ARTWORK',
            'physicalPrintValidated':False}


def decorate(root,tenant,meta):
    return {**meta,'usage':usage(root,tenant,meta)}


def _valid_asset_meta(path, meta):
    if not isinstance(meta, dict):
        return False
    aid = meta.get('id')
    if not isinstance(aid, str) or not re.fullmatch(r'[a-f0-9]{64}', aid) or aid != path.parent.name:
        return False
    name = meta.get('name')
    if not isinstance(name, str) or not name.strip():
        return False
    info = meta.get('info')
    if not isinstance(info, dict) or info.get('type') not in ('PDF', 'IMAGE'):
        return False
    pages = info.get('pages')
    return isinstance(pages, list) and len(pages) > 0 and all(isinstance(pg, dict) for pg in pages)


def listing(root,tenant,*,offset=0,limit=None):
    base=print_assets.workspace(root,tenant)/'assets'
    items=[]
    skipped=0
    for p in sorted(base.glob('*/asset.json')):
        try:
            meta=json.loads(p.read_text(encoding='utf-8'))
            if not _valid_asset_meta(p, meta):
                raise ValueError('invalid asset metadata')
            items.append(decorate(root,tenant,meta))
        except (OSError,ValueError,KeyError,TypeError):
            skipped+=1
            LOG.warning('略過無法讀取或缺欄位的素材紀錄: asset=%s',p.parent.name)
    total=len(items)
    sliced=items[offset:] if limit is None else items[offset:offset+limit]
    out=AssetList(sliced)
    out.skipped=skipped
    out.total=total
    return out


def listing_page(root,tenant,*,offset=0,limit=100):
    rows=listing(root,tenant,offset=offset,limit=limit)
    return {'items':list(rows),'total':rows.total,'offset':offset,'limit':limit,'skipped':rows.skipped}


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
