"""Read-only, explicitly configured NAS inventory. File groups are not product truth."""
from __future__ import annotations

import os
import re
from pathlib import Path

from filelock import FileLock

from fox3d.ids import stable_hash
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.recipe_workbench import timestamp
from fox3d import print_assets

FAMILIES = {'coaster':'杯墊', 'mat':'地墊', 'cabinet':'木櫃', 'curtain':'門簾',
            'mask_box':'口罩收納盒', 'storage_box_50':'50入收納盒', 'spray_bottle':'噴瓶'}
SUBTYPES = {'hinged':'門櫃', 'open':'空欄／開放櫃', 'bedside':'床邊櫃', 'bookcase':'書櫃', 'other':'其他／待確認'}
EXTENSIONS = set('.ai .pdf .psd .psb .cdr .jpg .jpeg .png .tif .tiff .svg .eps .xlsx .xls .csv .docx .doc .txt .blend .step .stp .iges .igs .stl .obj .fbx .glb .gltf .skp .3dm .dxf .dwg'.split())
CODE = re.compile(r'(?<![A-Za-z0-9])([A-Z]{2,4}\d{4,10})(?!\d)')

def source_files(base):
    pending=[base]
    while pending:
        current=pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink() or (os.name=='nt' and getattr(entry.stat(follow_symlinks=False),'st_file_attributes',0)&0x400): continue
                if entry.is_dir(follow_symlinks=False): pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in EXTENSIONS:
                    yield Path(entry.path)


def config(root):
    entries = read_json(Path(root)/'nas-catalog-config.json').get('sources', [])
    seen = set()
    for entry in entries:
        if entry['family'] not in FAMILIES or entry['id'] in seen or not re.fullmatch(r'[a-z0-9_-]{1,60}', entry['id']):
            raise ValueError('NAS 來源設定錯誤')
        if not Path(entry['path']).is_absolute():
            raise ValueError('NAS 來源須使用完整路徑')
        seen.add(entry['id'])
    return entries


def subtype(path):
    if any(x in path for x in ('床邊','床頭')): return 'bedside'
    if '書櫃' in path: return 'bookcase'
    if any(x in path for x in ('空櫃','空欄','開放櫃')): return 'open'
    if '門櫃' in path: return 'hinged'
    return 'other'


def snapshot(root):
    return read_json(Path(root)/'nas-catalog-index.json')


def scan(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root/'nas-catalog-scan.lock'), timeout=0):
        entries = config(root)
        if not entries: raise ValueError('尚未設定 NAS 商品來源')
        groups, files = {}, []
        for entry in entries:
            base = Path(entry['path']).resolve(strict=True)
            if not base.is_dir(): raise ValueError('NAS 商品來源不是資料夾')
            for p in source_files(base):
                name=p.name
                rel = p.relative_to(base)
                # First SKU-bearing folder groups its print/photos/spec descendants together.
                folders = rel.parts[:-1]
                stop = next((i+1 for i, label in enumerate(folders) if CODE.search(label)), None)
                group_path = '/'.join(folders[:stop] if stop else folders[:1]) or '.'
                gid = stable_hash({'source':entry['id'], 'root':str(base), 'group':group_path})
                if gid not in groups:
                    groups[gid] = {'id':gid, 'sourceId':entry['id'], 'folder':group_path,
                        'name':group_path.split('/')[-1] if group_path != '.' else base.name,
                        'family':entry['family'], 'subtype':subtype(base.name+'/'+group_path) if entry['family']=='cabinet' else 'other',
                        'fileCount':0, 'skuCandidates':[], 'isVerifiedProduct':False}
                group = groups[gid]
                sid = stable_hash({'source':entry['id'], 'root':str(base), 'path':rel.as_posix()})
                codes = CODE.findall(rel.as_posix())
                group['fileCount'] += 1
                group['skuCandidates'] = sorted(set(group['skuCandidates']) | set(codes))
                files.append({'id':sid, 'groupId':gid, 'sourceId':entry['id'], 'path':rel.as_posix(),
                              'name':name, 'extension':p.suffix.lower()})
                if len(files)>100000: raise ValueError('來源超過十萬個檔案，請縮小設定範圍')
        result = {'scannedAt':timestamp(), 'configHash':stable_hash(entries), 'fileCount':len(files),
                  'groups':list(groups.values()), 'files':files, 'readOnly':True,
                  'scope':'僅已設定資料夾；檔案群組與商品編號皆待確認，非全公司商品數'}
        atomic_json(root/'nas-catalog-index.json', result)
        return {'scannedAt':result['scannedAt'], 'fileCount':len(files), 'groupCount':len(groups)}


def checked_snapshot(root):
    data = snapshot(root)
    if data and data.get('configHash') != stable_hash(config(root)):
        raise ValueError('NAS 來源設定已變更，請重新掃描')
    return data


def import_file(root, tenant, sid):
    data = checked_snapshot(root)
    item = next((f for f in data.get('files',[]) if f['id']==sid), None)
    if not item: raise KeyError('找不到來源檔案，請重新掃描')
    entry = next(e for e in config(root) if e['id']==item['sourceId'])
    base = Path(entry['path']).resolve(strict=True)
    path = (base/item['path']).resolve(strict=True)
    if not path.is_relative_to(base): raise ValueError('來源超出設定範圍')
    if path.suffix.lower() not in {'.ai','.pdf','.jpg','.jpeg','.png','.tif','.tiff'}:
        raise ValueError('此格式目前僅提供檔案位置；請使用 PDF 相容 AI、PDF 或圖片預覽')
    with path.open('rb') as stream: raw = stream.read(print_assets.MAX_BYTES+1)
    if len(raw)>print_assets.MAX_BYTES: raise ValueError('原稿上限為 150 MB')
    from fox3d import asset_usage
    meta=print_assets.import_asset(root,tenant,raw,item['name'],
        {'type':'NAS_PRODUCT_CATALOG', 'sourceId':sid, 'relativePath':item['path'], 'physicalDimensionsVerified':False})
    return asset_usage.decorate(root,tenant,meta)
