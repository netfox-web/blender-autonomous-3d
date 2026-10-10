"""Versioned NAS product masters, separate from artwork SKUs and manufacturing truth."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fox3d.ids import new_id, stable_hash
from fox3d import nas_catalog as nas, print_assets, asset_usage
from fox3d import recipe_3d as render
from fox3d.recipe_workbench import DraftConflict, timestamp, ProductDraft

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)

class Face(Strict):
    name: str = Field(min_length=1, max_length=100)
    widthMm: float = Field(gt=0, le=6000)
    heightMm: float = Field(gt=0, le=6000)
    bleedMm: float = Field(default=0, ge=0, le=20)
    evidence: str = Field(min_length=1, max_length=1500)
    originNote: str = Field(default='', max_length=1500)

class Variant(Strict):
    sku: str = Field(min_length=1, max_length=120)
    artworkAssetId: str = Field(default='', pattern=r'^([a-f0-9]{64})?$')
    note: str = Field(default='', max_length=1000)

class RecipeReference(Strict):
    revision: int = Field(ge=0)
    draft: ProductDraft

class Master(Strict):
    name: str = Field(min_length=1, max_length=240)
    family: Literal['coaster','mat','cabinet','curtain','mask_box','storage_box_50','spray_bottle']
    subtype: Literal['hinged','open','bedside','bookcase','other'] = 'other'
    sourceGroupId: str = Field(default='', pattern=r'^([a-f0-9]{64})?$')
    geometry: Literal['PENDING','RECTANGLE','OPEN_CABINET','HINGED_CABINET','RECIPE_REFERENCE'] = 'PENDING'
    recipeReference: RecipeReference | None = None
    widthMm: float | None = Field(default=None, gt=0, le=6000)
    depthMm: float | None = Field(default=None, gt=0, le=6000)
    heightMm: float | None = Field(default=None, gt=0, le=6000)
    panelMm: float | None = Field(default=None, gt=0, le=100)
    backMm: float | None = Field(default=None, gt=0, le=100)
    doorMm: float | None = Field(default=None, gt=0, le=100)
    gapMm: float | None = Field(default=None, ge=0, le=20)
    rows: int | None = Field(default=None, ge=1, le=12)
    dimensionEvidence: str = Field(default='', max_length=3000)
    structureEvidence: str = Field(default='', max_length=3000)
    notes: str = Field(default='', max_length=3000)
    variants: list[Variant] = Field(default_factory=list, max_length=200)
    printFaces: list[Face] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def coherent(self):
        if not self.name.strip(): raise ValueError('請填商品名稱')
        skus = [v.sku.strip() for v in self.variants]
        if any(not s for s in skus) or len(set(skus))!=len(skus): raise ValueError('同一模型的 SKU 不可空白或重複')
        if len({f.name.strip() for f in self.printFaces})!=len(self.printFaces) or any(not f.name.strip() or not f.evidence.strip() for f in self.printFaces):
            raise ValueError('印刷面名稱不可重複，且須填尺寸依據')
        if self.geometry=='RECTANGLE' and self.family not in {'coaster','mat','curtain'}:
            raise ValueError('矩形平板只適用於杯墊、地墊、門簾；特殊外形需另建配方')
        if self.geometry.endswith('CABINET') and self.family!='cabinet': raise ValueError('櫃體配方只適用於木櫃')
        return self

def folder(root, tid, mid):
    return render.get_recipe_3d_dir(Path(root)/'nas-models', tid, mid)

def status(root, tid, mid, *, current_draft=None):
    if current_draft:
        validate_artworks(root,tid,current_draft)
    return render.get_recipe_3d_status(Path(root)/'nas-models', tid, mid, current_draft=current_draft)

def generate(platform, tid, mid, draft, **kwargs):
    validate_artworks(platform.root,tid,draft)
    return render.generate_recipe_3d_product(platform,tid,mid,draft,**kwargs,
        spec_builder=build_spec,folder_builder=folder,status_builder=status)

def build_spec(data, *, tenant_id='default'):
    m = Master.model_validate(data)
    if m.geometry=='RECIPE_REFERENCE':
        if not m.recipeReference or m.family!='cabinet': raise ValueError('缺少原有 Recipe 配方快照')
        spec=render.build_recipe_spec(m.recipeReference.draft.model_dump(),tenant_id=tenant_id)
        if [m.widthMm,m.depthMm,m.heightMm]!=[spec['width'],spec['depth'],spec['height']]:
            raise ValueError('原有 Recipe 快照的外尺寸不可分開修改；請回 Recipe 庫修改，再載入新快照')
        for p in spec['components']:
            p.update(sizeMm=[v*1000 for v in p['size']],locationMm=[v*1000 for v in p['location']])
        spec.update(goldenRecipe=True,adapterVersion='NAS_RECIPE_REFERENCE_V1',sku=m.name,name=m.name,
            previewAssumptions=[f"{x['label']}：{x['value']} {x['unit']}；{x['note']}" for x in spec['previewAssumptions']])
        spec['previewAssumptions'].append('沿用原有 Recipe 參考快照與明示假設，未取得實物尺寸或印刷校正。')
        spec['previewHash']=stable_hash(spec)
        return spec
    missing = [label for key,label in [('widthMm','寬'),('depthMm','深／厚'),('heightMm','高／長')]
               if getattr(m,key) is None]
    if not m.dimensionEvidence.strip(): missing.append('外形尺寸依據')
    if not m.structureEvidence.strip(): missing.append('結構與外形依據')
    if m.geometry=='PENDING': missing.append('可用結構配方（曲面、抽屜、異形需另建配方）')
    if m.geometry.endswith('CABINET'):
        for key,label in [('panelMm','板厚'),('backMm','背板厚'),('rows','層數')]:
            if getattr(m,key) is None: missing.append(label)
        if m.geometry=='HINGED_CABINET':
            for key,label in [('doorMm','門厚'),('gapMm','門縫')]:
                if getattr(m,key) is None: missing.append(label)
    if missing: raise ValueError('待補：'+'、'.join(missing))
    w,d,h = m.widthMm,m.depthMm,m.heightMm
    parts=[]
    def part(pid, role, size, loc):
        if min(size)<=0: raise ValueError('尺寸無法構成有效板件，請檢查板厚、門縫及層數')
        parts.append({'componentId':pid,'partName':pid,'role':role,'size':[v/1000 for v in size],
            'location':[v/1000 for v in loc],'sizeMm':size,'locationMm':loc,
            'length':max(size),'width':sorted(size)[1],'thickness':min(size)})
    assumptions=['尺寸與結構由操作人員填寫；尚未獨立量測驗證。', '示意材質與棚拍燈光；尚未套入圖稿。',
                 '未完成刀模、印刷面原點、治具與實機試印校正，不可作為直接印刷依據。']
    if m.geometry=='RECTANGLE':
        part('surface','panel',[w,d,h],[0,0,h/2])
        assumptions.append('規則矩形平板；不包含圓角、異形切邊、布料垂墜或厚度變化。')
    else:
        t,b,rows = m.panelMm,m.backMm,m.rows
        front = (m.doorMm+m.gapMm) if m.geometry=='HINGED_CABINET' else 0
        inner_w, inner_d = w-2*t, d-b-front
        opening = (h-(rows+1)*t)/rows
        if min(inner_w,inner_d,opening)<=0: raise ValueError('櫃體內部尺寸不足，請檢查板厚與層數')
        part('left','left',[t,d,h],[-w/2+t/2,0,h/2])
        part('right','right',[t,d,h],[w/2-t/2,0,h/2])
        part('top','top',[inner_w,d,t],[0,0,h-t/2])
        part('bottom','bottom',[inner_w,d,t],[0,0,t/2])
        part('back','back',[inner_w,b,h-2*t],[0,d/2-b/2,h/2])
        for row in range(rows):
            z=t+row*(opening+t)+opening/2
            if row<rows-1: part(f'shelf_{row+1}','shelf',[inner_w,inner_d,t],[0,(front-b)/2,z+opening/2+t/2])
            if m.geometry=='HINGED_CABINET':
                part(f'door_{row+1}','door',[inner_w-2*m.gapMm,m.doorMm,opening-2*m.gapMm],[0,-d/2+m.doorMm/2,z])
        assumptions.append('單列等高格位、內嵌背板；門櫃每格一片內嵌門。省略五金、榫接及開門機構；非此結構請選「待建立配方」。')
    spec={'productId':'nas_'+stable_hash(data)[:20], 'sku':m.name,'tenantId':tenant_id,'name':m.name,
          'kind':m.geometry,'family':m.family,'width':w,'depth':d,'height':h,'thickness':m.panelMm or d,
          'material':'white_wood','components':parts,'previewAssumptions':assumptions,'recipePreview':True,
          'goldenRecipe':True, 'adapterVersion':'NAS_MASTER_V1','engineeringReady':False,'productionReady':False}
    spec['previewHash']=stable_hash(spec)
    return spec

def readiness(data):
    try:
        spec=build_spec(data)
        return {'previewReady':True,'missing':None,'assumptions':spec['previewAssumptions'],
                'physicalDimensionsVerified':False,'printReady':False}
    except ValueError as exc:
        return {'previewReady':False,'missing':str(exc),'assumptions':[],
                'physicalDimensionsVerified':False,'printReady':False}

def directory(root,tid):
    return print_assets.workspace(root,tid)/'product-masters'

def get(root,tid,mid):
    if not re.fullmatch(r'[a-f0-9-]{36}',mid): raise KeyError('找不到模型')
    data=render.read_json(directory(root,tid)/mid/'master.json')
    if not data: raise KeyError('找不到模型')
    return {**data,'readiness':readiness(data['draft'])}

def listing(root,tid):
    items=[]
    for p in sorted(directory(root,tid).glob('*/master.json')):
        item=get(root,tid,p.parent.name)
        try:
            preview=status(root,tid,item['id'],current_draft=item['draft'])
            available=preview.get('generated') and not preview.get('stale')
        except (ValueError,OSError,KeyError):
            available=False
        if not available:
            from fox3d import model_compositions
            composed=model_compositions.status(root,tid,item['id'],current_draft=item)
            available=composed['generated'] and not composed['stale']
        items.append({**item,'templateState':'PREVIEW_AVAILABLE' if available else 'DRAFT'})
    return items


def validate_artworks(root,tid,data):
    for variant in data.get('variants',[]):
        if variant.get('artworkAssetId'):
            asset_usage.require_artwork(root,tid,variant['artworkAssetId'])

def save(root,tid,data,revision,mid=None):
    m=Master.model_validate(data)
    if m.sourceGroupId and not any(g['id']==m.sourceGroupId for g in nas.checked_snapshot(root).get('groups',[])):
        raise ValueError('來源群組已失效，請重新選擇')
    validate_artworks(root,tid,m.model_dump())
    base=directory(root,tid); base.mkdir(parents=True,exist_ok=True)
    with FileLock(str(base/'write.lock'),timeout=10):
        previous=get(root,tid,mid) if mid else None
        if revision!=(previous['revision'] if previous else 0): raise DraftConflict('版本已變更；請重新載入後再儲存')
        mid=mid or new_id()
        result={'id':mid,'revision':revision+1,'updatedAt':timestamp(),'draft':m.model_dump(),
                'inputHash':render.input_hash(m.model_dump()),'productionReady':False}
        render.atomic_json(base/mid/'revisions'/f'{revision+1}.json',result)
        render.atomic_json(base/mid/'master.json',result)
    return get(root,tid,mid)
