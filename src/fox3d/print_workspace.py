"""Versioned print jobs with physical-size PDFs and explicit human RIP release.

No network output, hot-folder dispatch, or machine control exists in this module.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import math
import re
import shutil
import zipfile
from threading import RLock
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import (NameObject, DictionaryObject, NumberObject, DecodedStreamObject,
                           ArrayObject, RectangleObject)

from fox3d.ids import new_id, sha256_bytes, stable_hash
from fox3d.infra import utcnow
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.print_assets import NotFoundError, workspace, asset
from fox3d.asset_usage import require_artwork

LOG=logging.getLogger(__name__)
LOCK=RLock()
PT=72/25.4
MAX_PROOF_BUNDLES=10
_MAX_CACHE_ENTRIES=10_000
_JOB_CACHE:dict[str,tuple[tuple[int,int,int],dict|None]]={}
_CREATED_AT_INDEX:dict[tuple[str,str],str]={}


class JobList(list):
    skipped: int = 0
    total: int = 0
    next_cursor: str | None = None


def _file_sig(path)->tuple[int,int,int]|None:
    try:
        st=path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns,st.st_size,st.st_ino)


def _store_cache(cache:dict,key,value)->None:
    if key in cache:
        cache.pop(key,None)
    elif len(cache)>=_MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)),None)
    cache[key]=value


def _invalidate_job_cache(path)->None:
    with LOCK:
        _JOB_CACHE.pop(str(path),None)


def clear_job_cache()->None:
    with LOCK:
        _JOB_CACHE.clear()
        _CREATED_AT_INDEX.clear()


class Panel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    label:str=Field(min_length=1,max_length=80)
    assetId:str=Field(pattern=r'^[a-f0-9]{64}$')
    page:int=Field(default=0,ge=0,le=99)
    rotation:Literal[0,90,180,270]=0
    quantity:int=Field(default=1,ge=1,le=5000)
    imageWidthMm:float|None=Field(default=None,gt=1,le=3000)
    imageHeightMm:float|None=Field(default=None,gt=1,le=3000)
    imageBleedMm:float=Field(default=0,ge=0,le=20)


class PrintDraft(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    sku:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    name:str=Field(min_length=1,max_length=150)
    layout:Literal['THREE_DOOR','FLAT']='THREE_DOOR'
    panels:list[Panel]=Field(min_length=1,max_length=3)
    rip:str=Field(default='RasterLink 6',max_length=120)
    machine:str=Field(default='',max_length=120)
    substrate:str=Field(default='',max_length=120)

    @model_validator(mode='after')
    def count(self):
        if len(self.panels)!=(3 if self.layout=='THREE_DOOR' else 1):
            raise ValueError('三層櫃需三個印刷面，單片／背板需一個印刷面')
        return self


class Release(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expectedRevision:int=Field(ge=1)
    planHash:str=Field(pattern=r'^[a-f0-9]{64}$')
    proofId:str=Field(pattern=r'^[a-f0-9-]{36}$')
    operator:str=Field(min_length=2,max_length=100)
    measurementRecord:str=Field(min_length=8,max_length=2000)
    testPrintRecord:str=Field(min_length=8,max_length=2000)
    dimensionsChecked:bool
    orderAndOrientationChecked:bool
    bleedAndKeepOutChecked:bool
    colorWhiteVarnishTestPassed:bool
    ripScale100Confirmed:bool


def folder_for(root,tenant,jid):
    if not isinstance(jid,str) or not re.fullmatch(r'[a-f0-9-]{36}',jid):
        raise NotFoundError('找不到印刷工作')
    return workspace(root,tenant)/'jobs'/jid


def get_job(root,tenant,jid):
    path=folder_for(root,tenant,jid)/'job.json'
    if not path.is_file():
        raise NotFoundError('找不到印刷工作')
    j=read_json(path)
    if not isinstance(j,dict) or j.get('id')!=jid:
        raise NotFoundError('找不到印刷工作')
    return j


def _valid_job_record(path, j):
    if not isinstance(j, dict):
        return False
    jid = j.get('id')
    if not isinstance(jid, str) or not re.fullmatch(r'[a-f0-9-]{36}', jid) or jid != path.parent.name:
        return False
    updated_at = j.get('updatedAt')
    if not isinstance(updated_at, str) or not updated_at.strip():
        return False
    created_at = j.get('createdAt')
    if created_at is not None and (not isinstance(created_at, str) or not created_at.strip()):
        return False
    rev = j.get('revision')
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        return False
    draft = j.get('draft')
    if not isinstance(draft, dict):
        return False
    PrintDraft.model_validate(draft)
    return True


def _job_created_at(path_str:str,j:dict)->str:
    created=j.get('createdAt')
    if isinstance(created,str) and created.strip():
        _store_cache(_CREATED_AT_INDEX,(path_str,j['id']),created)
        return created
    existing=_CREATED_AT_INDEX.get((path_str,j['id']))
    if existing is not None:
        return existing
    _store_cache(_CREATED_AT_INDEX,(path_str,j['id']),j['updatedAt'])
    return j['updatedAt']


def _job_sort_key(path_str:str,j:dict)->tuple[str,str]:
    return (_job_created_at(path_str,j),j['id'])


def _jobs_after_cursor(entries,cursor,offset,tag):
    """套用本租戶鍵集游標。對不上的游標改走 offset，避免其他租戶的位置把呼叫者的工作濾掉。"""
    raw=cursor.strip()
    if '|' not in raw:
        idx=next((i for i,item in enumerate(entries) if item[1]['id']==raw),None)
        return entries[idx+1:] if idx is not None else entries[offset:]
    pieces=[part.strip() for part in raw.rsplit('|',2)]
    if len(pieces)==3:
        created,job_id,bound=pieces
        if bound!=tag or not created:
            return entries[offset:]
    else:
        created,job_id=pieces
        if not created or not any(item[1]['id']==job_id for item in entries):
            return entries[offset:]
    boundary=(created,job_id)
    return [item for item in entries if _job_sort_key(item[0],item[1])<boundary]


def listing(root,tenant,*,offset=0,limit=None,cursor=None):
    folder=workspace(root,tenant)/'jobs'
    tag=folder.parent.name
    entries=[]
    skipped=0
    for f in sorted(folder.glob('*/job.json')):
        key=str(f)
        sig=_file_sig(f)
        if sig is None:
            skipped+=1
            LOG.warning('略過無法讀取或缺欄位的印刷工作紀錄: job=%s',f.parent.name)
            continue
        with LOCK:
            cached=_JOB_CACHE.get(key)
        if cached is not None and cached[0]==sig:
            record=cached[1]
            if record is None:
                skipped+=1
                LOG.warning('略過無法讀取或缺欄位的印刷工作紀錄: job=%s',f.parent.name)
            else:
                entries.append((key,record))
            continue
        try:
            j=json.loads(f.read_text(encoding='utf-8'))
            if not _valid_job_record(f,j):
                raise ValueError('invalid job record')
            with LOCK:
                _job_created_at(key,j)
                _store_cache(_JOB_CACHE,key,(sig,j))
            entries.append((key,j))
        except (OSError,ValueError,KeyError,TypeError):
            with LOCK:
                _store_cache(_JOB_CACHE,key,(sig,None))
            skipped+=1
            LOG.warning('略過無法讀取或缺欄位的印刷工作紀錄: job=%s',f.parent.name)
    with LOCK:
        entries.sort(key=lambda item:_job_sort_key(item[0],item[1]),reverse=True)
        if isinstance(cursor,str) and cursor.strip():
            filtered=_jobs_after_cursor(entries,cursor,offset,tag)
            sliced_entries=filtered if limit is None else filtered[:limit]
        else:
            sliced_entries=entries[offset:] if limit is None else entries[offset:offset+limit]
        next_cursor=None
        if limit is not None and sliced_entries and entries:
            last_key,last_job=sliced_entries[-1]
            if last_job['id']!=entries[-1][1]['id']:
                sort_created,sort_id=_job_sort_key(last_key,last_job)
                if '|' not in sort_created and '|' not in sort_id and '|' not in tag:
                    next_cursor=f'{sort_created}|{sort_id}|{tag}'
    total=len(entries)
    out=JobList(copy.deepcopy(j) for _,j in sliced_entries)
    out.skipped=skipped
    out.total=total
    out.next_cursor=next_cursor
    return out


def list_jobs(root,tenant,*,offset=0,limit=100,cursor=None):
    rows=listing(root,tenant,offset=offset,limit=limit,cursor=cursor)
    return {'items':list(rows),'total':rows.total,'offset':offset,'limit':limit,'skipped':rows.skipped,'nextCursor':rows.next_cursor}


def save_job(root,tenant,draft,*,jid=None,expected_revision=0):
    d=PrintDraft.model_validate(draft).model_dump(mode='json')
    with LOCK:
        if jid:
            old=get_job(root,tenant,jid)
            if old['revision']!=expected_revision:
                raise ValueError('版本已變更，請重新載入，避免覆蓋其他人的設定')
        else:
            if expected_revision!=0:raise ValueError('新工作版本必須為 0')
            jid=new_id();old={'revision':0}
        # Validate source pages and real dimensions before saving a job.
        plan(root,tenant,d)
        now=str(utcnow())
        created_at=old.get('createdAt') or old.get('updatedAt') or now
        j={'id':jid,'revision':old['revision']+1,'draft':d,'createdAt':created_at,'updatedAt':now,
           'release':None,'lastProofId':old.get('lastProofId')}
        job_path=folder_for(root,tenant,jid)/'job.json'
        atomic_json(job_path,j)
        _invalidate_job_cache(job_path)
        return j


def _image_page(raw, panel):
    with Image.open(io.BytesIO(raw)) as src:
        icc=src.info.get('icc_profile')
        if src.mode=='RGBA':
            if src.getextrema()[3]!=(255,255):
                raise ValueError('透明圖稿需先完成白墨／底色分版；目前請提供不透明印刷稿')
            src=src.convert('RGB')
        im=src.rotate(-panel.rotation,expand=True)
        mode=im.mode
        if not panel.imageWidthMm or not panel.imageHeightMm:
            raise ValueError('圖片沒有可靠毫米尺寸，請輸入含出血的完整版面寬高')
        w,h=panel.imageWidthMm,panel.imageHeightMm
        if abs((im.width/im.height)/(w/h)-1)>0.002:
            raise ValueError('尺寸比例與圖稿不符（超過 0.2%）；禁止拉伸，請核對方向與完整版面尺寸')
        if min(im.width/w,im.height/h)*25.4<100:
            raise ValueError('圖稿解析度低於 100 DPI，請改用較大原稿')
        if 2*panel.imageBleedMm>=min(w,h):raise ValueError('出血超出版面')
        writer=PdfWriter();page=writer.add_blank_page(width=w*PT,height=h*PT)
        stream=DecodedStreamObject();stream.set_data(im.tobytes())
        stream.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
            NameObject('/Width'):NumberObject(im.width),NameObject('/Height'):NumberObject(im.height),
            NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject({'RGB':'/DeviceRGB','CMYK':'/DeviceCMYK','L':'/DeviceGray'}[mode])})
        if icc:
            profile=DecodedStreamObject();profile.set_data(icc);profile[NameObject('/N')]=NumberObject(len(im.getbands()))
            stream[NameObject('/ColorSpace')]=ArrayObject([NameObject('/ICCBased'),writer._add_object(profile.flate_encode())])
        image_ref=writer._add_object(stream.flate_encode())
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Im'):image_ref})})
        content=DecodedStreamObject();content.set_data(f'q {w*PT:.8f} 0 0 {h*PT:.8f} 0 0 cm /Im Do Q'.encode())
        page[NameObject('/Contents')]=writer._add_object(content)
        b=panel.imageBleedMm*PT;page.trimbox=RectangleObject([b,b,w*PT-b,h*PT-b])
        return page, writer


def panel_page(raw,meta,panel,*,raster=False):
    """Return physical-size source content, with no fit-to-page or aspect stretch."""
    if meta['info']['type']=='PDF':
        if panel.imageWidthMm is not None or panel.imageHeightMm is not None or panel.imageBleedMm:
            raise ValueError('PDF 使用原檔版面與裁切框，不能另填圖片尺寸')
        reader=PdfReader(io.BytesIO(raw));working=PdfWriter();page=working.add_page(reader.pages[panel.page])
        page.rotate(panel.rotation);page.transfer_rotation_to_content()
        x,y=float(page.mediabox.left),float(page.mediabox.bottom)
        if x or y:
            page.add_transformation(Transformation().translate(-x,-y))
            boxes={key:list(getattr(page,key)) for key in ('mediabox','trimbox','cropbox','bleedbox','artbox')}
            for key,box in boxes.items():
                setattr(page,key,RectangleObject([float(box[0])-x,float(box[1])-y,float(box[2])-x,float(box[3])-y]))
        page.cropbox=RectangleObject(page.mediabox)
        for key in ('/AA','/Annots'):
            page.pop(NameObject(key),None)
        return page, reader
    if raster:return _image_page(raw,panel)
    # Geometry/preflight requires only headers; avoid compressing full raster on every poll.
    with Image.open(io.BytesIO(raw)) as im:
        w,h=im.size if panel.rotation in (0,180) else im.size[::-1]
        if im.mode=='RGBA' and im.getextrema()[3]!=(255,255):
            raise ValueError('透明圖稿需先完成白墨／底色分版')
        if not panel.imageWidthMm or not panel.imageHeightMm:
            raise ValueError('圖片需填含出血的完整版面毫米尺寸')
        mw,mh=panel.imageWidthMm,panel.imageHeightMm;b=panel.imageBleedMm
        if abs((w/h)/(mw/mh)-1)>0.002:raise ValueError('尺寸比例與圖稿不符，禁止拉伸')
        if min(w/mw,h/mh)*25.4<100:raise ValueError('原稿低於 100 DPI')
        if 2*b>=min(mw,mh):raise ValueError('出血超出版面')
        page=PageObject.create_blank_page(width=mw*PT,height=mh*PT)
        page.trimbox=RectangleObject([b*PT,b*PT,(mw-b)*PT,(mh-b)*PT])
        return page,None


def plan(root,tenant,draft):
    d=PrintDraft.model_validate(draft);cache={};panels=[]
    for i,p in enumerate(d.panels):
        if p.assetId not in cache:
            require_artwork(root,tenant,p.assetId)
            cache[p.assetId]=asset(root,tenant,p.assetId)
        meta,raw=cache[p.assetId]
        if not 0<=p.page<len(meta['info']['pages']):raise ValueError('原稿頁碼不存在')
        # Size metadata must describe the immutable original, not a rewritten sidecar.
        page,owner=panel_page(raw,meta,p)
        m,t=page.mediabox,page.trimbox
        w,h=float(m.width)/PT,float(m.height)/PT
        tw,th=float(t.width)/PT,float(t.height)/PT
        if not all(math.isfinite(v) and v>0 for v in (w,h,tw,th)) or max(w,h)>5000:
            raise ValueError('無效的毫米版面')
        if tw>w+0.001 or th>h+0.001:raise ValueError('裁切框超出版面')
        panels.append({'index':i,'label':p.label,'quantity':p.quantity,'assetId':p.assetId,'page':p.page,'rotation':p.rotation,
            'sourceName':meta['name'],'sourceType':meta['info']['type'],'sourceTruth':'USER_PROVIDED_SOURCE',
            'widthMm':w,'heightMm':h,'trimWidthMm':tw,'trimHeightMm':th,
            'trimBoxMm':[float(v)/PT for v in t], 'sourceColor':meta['info']['color'],
            'sizeAuthority':'SOURCE_LAYOUT_NOT_MEASURED_PART','face':'FRONT_OF_SELECTED_PART'})
    if d.layout=='THREE_DOOR' and any(abs(p[k]-panels[0][k])>0.02 for p in panels for k in ['trimWidthMm','trimHeightMm']):
        raise ValueError('三層門櫃的三片門需相同裁切尺寸；不同板件請使用單片模式')
    result={'draft':d.model_dump(mode='json'),'panels':panels,'printScale':1.0,'fit':'SOURCE_SIZE_NO_STRETCH',
            'previewColor':'RGB_APPROXIMATION_NOT_COLOR_PROOF','engineeringReady':False,'manufacturingReady':False,
            'liveMachineControl':False,'delivery':'DOWNLOAD_FOR_MANUAL_RIP_IMPORT',
            'requiredHumanChecks':['實測板件與版面尺寸','圖稿順序及方向','出血、孔位與禁印區','RIP 材質／色彩／白墨／光油打樣','RIP 縮放 100%']}
    result['planHash']=stable_hash(result)
    return result


def stamp_proof(page):
    overlay=PageObject.create_blank_page(width=float(page.mediabox.width),height=float(page.mediabox.height))
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica-Bold')})
    overlay[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/FProof'):font})})
    w,h=float(page.mediabox.width),float(page.mediabox.height)
    fs=min(28,w/23)
    s=DecodedStreamObject();s.set_data(f'q 1 0 0 rg BT /FProof {fs:.4f} Tf 12 {h/2:.4f} Td (PROOF - NOT FOR PRINT) Tj ET Q'.encode())
    overlay[NameObject('/Contents')]=s;page.merge_page(overlay)


def validate_bundle(folder):
    meta_path=folder/'bundle-meta.json'
    manifest_path=folder/'manifest.json'
    if not folder.is_dir() or not meta_path.is_file() or not manifest_path.is_file():
        raise NotFoundError('找不到印刷下載包')
    meta=read_json(meta_path)
    try:
        raw=manifest_path.read_bytes()
    except OSError as exc:
        raise NotFoundError('找不到印刷下載包') from exc
    if not isinstance(meta,dict) or sha256_bytes(raw)!=meta.get('manifestSha256'):
        raise ValueError('印刷清單驗證失敗')
    m=json.loads(raw)
    if not isinstance(m,dict) or m.get('kind') not in ('PROOF','APPROVED_FOR_MANUAL_RIP_IMPORT'):
        raise ValueError('不明印刷包類型')
    if m.get('liveMachineControl') is not False or m.get('productionReady') is not False:
        raise ValueError('印刷授權狀態不符')
    expected={f'panel-{i+1}.pdf' for i in range(len(m['plan']['panels']))}
    if set(m['files'])!=expected:raise ValueError('印刷檔案清單不符')
    for name,record in m['files'].items():
        file_path=folder/name
        if not file_path.is_file():
            raise ValueError('印刷檔案已變更，請重新生成')
        data=file_path.read_bytes()
        if sha256_bytes(data)!=record['sha256'] or len(data)!=record['sizeBytes']:
            raise ValueError('印刷檔案已變更，請重新生成')
        reader=PdfReader(io.BytesIO(data))
        if len(reader.pages)!=1:raise ValueError('印刷面必須為單頁 PDF')
        pg=reader.pages[0];want=m['plan']['panels'][int(name.split('-')[1].split('.')[0])-1]
        if abs(float(pg.mediabox.width)/PT-want['widthMm'])>0.01 or abs(float(pg.mediabox.height)/PT-want['heightMm'])>0.01:
            raise ValueError('PDF 實際毫米尺寸不符')
        if any(abs(float(v)/PT-w)>0.01 for v,w in zip(pg.trimbox,want['trimBoxMm'])):
            raise ValueError('PDF 裁切框不符')
        if m['kind']=='PROOF' and 'PROOF - NOT FOR PRINT' not in pg.extract_text():
            raise ValueError('校稿浮水印缺失')
    return m


def _verify_complete_bundle(folder):
    m=validate_bundle(folder)
    zip_path=folder/'package.zip'
    zip_meta_path=folder/'zip-meta.json'
    if not zip_path.is_file() or not zip_meta_path.is_file():
        raise NotFoundError('找不到印刷下載包')
    zip_meta=read_json(zip_meta_path)
    if not isinstance(zip_meta,dict) or sha256_bytes(zip_path.read_bytes())!=zip_meta.get('sha256'):
        raise ValueError('下載包驗證失敗')
    return zip_path,m


def _load_valid_bundle(folder):
    try:
        _,m=_verify_complete_bundle(folder)
        return m
    except (ValueError,OSError,KeyError,TypeError):
        return None


def _find_existing_proof(bundles_root,jid,revision,plan_hash,last_proof_id=None):
    candidates=[]
    if isinstance(last_proof_id,str) and re.fullmatch(r'[a-f0-9-]{36}',last_proof_id):
        candidates.append(bundles_root/last_proof_id)
    if bundles_root.is_dir():
        for child in sorted(bundles_root.iterdir()):
            if child.is_dir() and child not in candidates:
                candidates.append(child)
    for folder in candidates:
        m=_load_valid_bundle(folder)
        if m and m.get('kind')=='PROOF' and m.get('jobId')==jid and m.get('revision')==revision and m.get('plan',{}).get('planHash')==plan_hash:
            return m
    return None


def _find_existing_release(bundles_root,jid,revision,plan_hash,release_data,current_release=None):
    candidates=[]
    if isinstance(current_release,dict):
        rel_bid=current_release.get('bundleId')
        if isinstance(rel_bid,str) and re.fullmatch(r'[a-f0-9-]{36}',rel_bid):
            candidates.append(bundles_root/rel_bid)
    if bundles_root.is_dir():
        for child in sorted(bundles_root.iterdir()):
            if child.is_dir() and child not in candidates:
                candidates.append(child)
    for folder in candidates:
        m=_load_valid_bundle(folder)
        if not m:
            continue
        hr=m.get('humanRelease')
        if (m.get('kind')=='APPROVED_FOR_MANUAL_RIP_IMPORT' and m.get('jobId')==jid
                and m.get('revision')==revision and m.get('plan',{}).get('planHash')==plan_hash
                and isinstance(hr,dict) and hr==release_data):
            return m
    return None


def _prune_proof_bundles(bundles_root,job,*,limit=MAX_PROOF_BUNDLES):
    if not bundles_root.is_dir() or limit<1:
        return
    protected=set()
    last_proof=job.get('lastProofId')
    if isinstance(last_proof,str) and last_proof:
        protected.add(last_proof)
    rel=job.get('release')
    if isinstance(rel,dict):
        for key in ('bundleId','proofId'):
            val=rel.get(key)
            if isinstance(val,str) and val:
                protected.add(val)
    proof_entries=[]
    for child in bundles_root.iterdir():
        if not child.is_dir():
            continue
        manifest=read_json(child/'manifest.json')
        if not isinstance(manifest,dict):
            continue
        kind=manifest.get('kind')
        if kind=='APPROVED_FOR_MANUAL_RIP_IMPORT':
            protected.add(child.name)
            hr=manifest.get('humanRelease')
            if isinstance(hr,dict) and isinstance(hr.get('proofId'),str) and hr['proofId']:
                protected.add(hr['proofId'])
        elif kind=='PROOF':
            try:
                mtime=child.stat().st_mtime_ns
            except OSError:
                mtime=0
            rev=manifest.get('revision',0)
            rev_num=rev if isinstance(rev,int) and not isinstance(rev,bool) else 0
            created=str(manifest.get('createdAt') or '')
            proof_entries.append(((rev_num,created,mtime,child.name),child))
    if len(proof_entries)<=limit:
        return
    proof_entries.sort(key=lambda item:item[0],reverse=True)
    keep={child.name for _,child in proof_entries if child.name in protected}
    for _,child in proof_entries:
        if len(keep)>=limit:
            break
        keep.add(child.name)
    for _,child in proof_entries:
        if child.name not in keep:
            shutil.rmtree(child,ignore_errors=True)


def export_bundle(root,tenant,jid,*,expected_revision,plan_hash,release=None,max_proof_bundles=None):
    with LOCK:
        j=get_job(root,tenant,jid);p=plan(root,tenant,j['draft'])
        if j['revision']!=expected_revision or p['planHash']!=plan_hash:
            raise ValueError('設定已變更，請先儲存並重新核對')
        bundles_root=folder_for(root,tenant,jid)/'bundles'
        kind='PROOF'
        r=None
        if release:
            r=Release.model_validate(release)
            if r.expectedRevision!=expected_revision or r.planHash!=plan_hash:raise ValueError('放行版本不符')
            if not all(getattr(r,k) for k in ('dimensionsChecked','orderAndOrientationChecked','bleedAndKeepOutChecked','colorWhiteVarnishTestPassed','ripScale100Confirmed')):
                raise ValueError('需要操作人員完成全部尺寸與實體打樣確認')
            if any(not s.strip() for s in (r.operator,r.measurementRecord,r.testPrintRecord)) or not all(j['draft'][k].strip() for k in ('rip','machine','substrate')):
                raise ValueError('請填操作人員、量測／打樣紀錄、RIP、機台與材質')
            proof=validate_bundle(bundles_root/r.proofId)
            if proof['kind']!='PROOF' or proof['jobId']!=jid or proof['revision']!=j['revision'] or proof['plan']['planHash']!=plan_hash:
                raise ValueError('請先下載並核對這個版本的校稿')
            kind='APPROVED_FOR_MANUAL_RIP_IMPORT'
            release_payload=r.model_dump()
            existing_rel=_find_existing_release(bundles_root,jid,j['revision'],plan_hash,release_payload,j.get('release'))
            if existing_rel:
                bid=existing_rel['bundleId']
                rel_record={'bundleId':bid,'planHash':plan_hash,'revision':j['revision'],'operator':r.operator,'proofId':r.proofId}
                if j.get('release')!=rel_record:
                    j['release']=rel_record
                    job_path=folder_for(root,tenant,jid)/'job.json'
                    atomic_json(job_path,j)
                    _invalidate_job_cache(job_path)
                return {'bundleId':bid,'kind':kind,'planHash':plan_hash,'revision':j['revision']}
        else:
            existing_proof=_find_existing_proof(bundles_root,jid,j['revision'],plan_hash,j.get('lastProofId'))
            if existing_proof:
                bid=existing_proof['bundleId']
                if j.get('lastProofId')!=bid:
                    j['lastProofId']=bid
                    job_path=folder_for(root,tenant,jid)/'job.json'
                    atomic_json(job_path,j)
                    _invalidate_job_cache(job_path)
                return {'bundleId':bid,'kind':kind,'planHash':plan_hash,'revision':j['revision']}
        bid=new_id();folder=bundles_root/bid;folder.mkdir(parents=True)
        files={};cache={}
        for i,panel in enumerate(PrintDraft.model_validate(j['draft']).panels):
            if panel.assetId not in cache:cache[panel.assetId]=asset(root,tenant,panel.assetId)
            meta,raw=cache[panel.assetId];page,owner=panel_page(raw,meta,panel,raster=True)
            if kind=='PROOF':stamp_proof(page)
            writer=PdfWriter();writer.add_page(page)
            if isinstance(owner,PdfReader) and '/OutputIntents' in owner.trailer['/Root']:
                writer._root_object[NameObject('/OutputIntents')]=owner.trailer['/Root']['/OutputIntents'].clone(writer)
            # Do not carry source document JavaScript, launch actions, or attachments.
            writer.add_metadata({'/Title':f'{kind} {jid} panel {i+1}','/Subject':'Manual RIP import; source scale 100%; machine operation requires human control'})
            target=folder/f'panel-{i+1}.pdf'
            with target.open('wb') as f:writer.write(f)
            data=target.read_bytes();files[target.name]={'sha256':sha256_bytes(data),'sizeBytes':len(data)}
        manifest={'bundleId':bid,'jobId':jid,'revision':j['revision'],'kind':kind,'plan':p,'files':files,
                  'createdAt':str(utcnow()),'humanRelease':r.model_dump() if r else None,
                  'approvalAuthority':'USER_ATTESTATION' if r else 'NONE','liveMachineControl':False,
                  'productionReady':False,'note':'Digital file approval does not certify equipment setup, manufacturing, or color. No machine was contacted.'}
        atomic_json(folder/'manifest.json',manifest)
        atomic_json(folder/'bundle-meta.json',{'manifestSha256':sha256_bytes((folder/'manifest.json').read_bytes())})
        validate_bundle(folder)
        zip_path=folder/'package.zip'
        with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            prefix='PROOF' if kind=='PROOF' else 'RIP_IMPORT'
            for name in files:z.write(folder/name,f'{prefix}_{j["draft"]["sku"]}_{name}')
            z.write(folder/'manifest.json','manifest.json')
            z.writestr('netfox-handoff.json',json.dumps({'schema':'fox3d.print-handoff.v1','jobId':jid,'bundleId':bid,
                'status':kind,'sku':j['draft']['sku'],'productName':j['draft']['name'],'planHash':plan_hash,
                'rip':j['draft']['rip'],'machine':j['draft']['machine'],'substrate':j['draft']['substrate'],
                'panels':[{**row,'file':f'{prefix}_{j["draft"]["sku"]}_panel-{i+1}.pdf','sha256':files[f'panel-{i+1}.pdf']['sha256']} for i,row in enumerate(p['panels'])],
                'targetSystem':'NetFox Print','integrationStatus':'FILE_HANDOFF_ONLY_NOT_SUBMITTED','liveMachineControl':False},ensure_ascii=False,indent=2))
            z.writestr('READ-ME.txt',f'{kind}\nImport each PDF at 100% scale. Preserve page/trim boxes. Confirm jig origin, media profile, white/clear ink and print a measured sample.\nNo hot-folder or printer dispatch has occurred.\n')
        atomic_json(folder/'zip-meta.json',{'sha256':sha256_bytes(zip_path.read_bytes())})
        j['lastProofId']=bid if kind=='PROOF' else j.get('lastProofId')
        if r:j['release']={'bundleId':bid,'planHash':plan_hash,'revision':j['revision'],'operator':r.operator,'proofId':r.proofId}
        job_path=folder_for(root,tenant,jid)/'job.json'
        atomic_json(job_path,j)
        _invalidate_job_cache(job_path)
        _prune_proof_bundles(bundles_root,j,limit=MAX_PROOF_BUNDLES if max_proof_bundles is None else max_proof_bundles)
        return {'bundleId':bid,'kind':kind,'planHash':plan_hash,'revision':j['revision']}


def bundle_download(root,tenant,jid,bid):
    j=get_job(root,tenant,jid)
    if not isinstance(bid,str) or not re.fullmatch(r'[a-f0-9-]{36}',bid):raise NotFoundError('找不到印刷下載包')
    folder=folder_for(root,tenant,jid)/'bundles'/bid;path,m=_verify_complete_bundle(folder)
    if m['jobId']!=jid or m['bundleId']!=bid:raise ValueError('印刷工作身分不符')
    for panel in m['plan']['draft']['panels']:
        require_artwork(root,tenant,panel['assetId'])
    if m['kind']!='PROOF':
        p=plan(root,tenant,j['draft'])
        if not j.get('release') or j['release']['bundleId']!=bid or m['revision']!=j['revision'] or m['plan']['planHash']!=p['planHash']:
            raise ValueError('此印刷放行已過期，請重新校稿與確認')
    return path,m
