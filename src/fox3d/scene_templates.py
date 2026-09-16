"""Versioned, metre-scale room templates. No bpy, external assets or product edits."""
from copy import deepcopy
from fox3d.ids import stable_hash

LABELS = {'STUDIO': '白底棚拍', 'WARM_ROOM': '暖色簡易背景', 'COOL_ROOM': '冷色簡易背景',
          'LIVING_ROOM': '客廳 · 沙發與茶几', 'KITCHEN': '廚房 · 櫥櫃與檯面'}
ROOMS = {'LIVING_ROOM', 'KITCHEN'}
VIEWS = {'THREE_QUARTER': '右前方', 'LEFT': '左前方', 'FRONT': '正前方'}
PLACEMENTS = {'AUTO': '依商品自動選位置', 'FLOOR': '地板', 'SURFACE': '茶几／廚房檯面'}


def resolve(scene, master, spec, placement='AUTO', view='THREE_QUARTER'):
    if scene not in LABELS or view not in VIEWS or placement not in PLACEMENTS:
        raise ValueError('未知場景、擺放位置或視角')
    if scene not in ROOMS:
        if placement != 'AUTO': raise ValueError('簡易背景請使用自動位置')
        return None
    family = master['family']
    if family not in {'cabinet', 'coaster', 'mat'}:
        raise ValueError('客廳／廚房目前支援櫃體、杯墊、地墊；此商品需專用擺放配方')
    slot = 'SURFACE' if family == 'coaster' else 'FLOOR'
    if placement not in {'AUTO', slot}:
        raise ValueError('此商品不適合選定位置；櫃體／地墊放地板，杯墊放茶几／檯面')
    w, d, h = (spec[k] / 1000 for k in ('width', 'depth', 'height'))
    flat = family in {'coaster', 'mat'}
    limits = (.45, .45, .05) if slot == 'SURFACE' else ((1.2, .8, .05) if flat else (1.2, .7, 2.1))
    occupied = (w, h, d) if flat else (w, d, h)
    if any(a > b for a, b in zip(occupied, limits)):
        raise ValueError('商品超出此場景的擺放空間；不會自動縮放，請改用棚拍或其他場景')
    support = (0.46 if scene == 'LIVING_ROOM' else .9) if slot == 'SURFACE' else 0.
    transform = ([[1., 0., 0., 0.], [0., 0., -1., h/2], [0., 1., 0., support+d/2], [0., 0., 0., 1.]]
                 if flat else [[1., 0., 0., 0.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]])
    boxes = []
    def box(name, size, location, color, bevel=.015):
        boxes.append(dict(name=name, size=list(size), location=list(location), color=list(color), bevel=bevel))
    cream=(.72,.67,.57); oak=(.35,.19,.085); white=(.8,.8,.74); teal=(.12,.25,.24)
    box('Floor', (6,6,.12), (0,0,-.06), (.36,.27,.18), .0)
    box('BackWall', (6,.12,3.1), (0,1.65,1.55), cream, .0)
    box('Skirting', (6,.035,.1), (0,1.568,.05), white, .002)
    box('SideWall', (.12,6,3.1), (-3,0,1.55), (.64,.66,.61), .0)
    if scene == 'LIVING_ROOM':
        box('SofaBase',(1.8,.72,.27),(-1.48,.95,.32),teal,.065)
        box('SofaBack',(1.8,.18,.58),(-1.48,1.23,.73),teal,.065)
        for x in (-2.31,-.65): box('SofaArm'+str(x),(.16,.78,.49),(x,.94,.51),teal,.045)
        for x in (-1.9,-1.1): box('Cushion'+str(x),(.72,.58,.14),(x,.89,.52),(.2,.35,.31),.05)
        box('PictureFrame',(.74,.06,.82),(-1.5,1.54,1.82),oak,.01)
        box('Picture',(.66,.015,.74),(-1.5,1.502,1.82),(.65,.38,.16),.0)
        box('PictureAccent',(.27,.01,.5),(-1.67,1.49,1.83),(.28,.41,.36),.0)
        tx,ty=(0,0) if slot=='SURFACE' else (-1.42,-.08)
        box('CoffeeTop',(1.0,.65,.055),(tx,ty,.4325),oak,.025)
        for x in (-.4,.4):
            for y in (-.23,.23): box('TableLeg'+str((x,y)),(.05,.05,.405),(tx+x,ty+y,.2025),oak,.009)
        box('LampFoot',(.3,.3,.045),(1.35,1.05,.0225),(.12,.12,.11),.015)
        box('LampStem',(.035,.035,1.45),(1.35,1.05,.75),(.2,.17,.12),.005)
        box('LampShade',(.4,.4,.32),(1.35,1.05,1.48),(.84,.72,.48),.06)
    else:
        # Keep the central floor slot clear; the back counter is behind the product.
        cy = 0 if slot=='SURFACE' else 1.15
        box('BaseCabinet',(2.8,.65,.82),(0,cy,.43),(.18,.29,.27),.012)
        box('Worktop',(2.9,.72,.055),(0,cy,.8725),(.77,.73,.62),.014)
        for x in (-1.02,-.34,.34,1.02):
            box('CabinetDoor'+str(x),(.66,.022,.7),(x,cy-.34,.46),(.24,.36,.33),.006)
            box('Handle'+str(x),(.18,.022,.015),(x,cy-.36,.72),(.055,.065,.058),.002)
        box('Backsplash',(2.9,.03,.6),(0,1.56,1.2),(.63,.65,.57),.0)
        for x in (-.98,0,.98): box('UpperCabinet'+str(x),(.94,.32,.64),(x,1.35,2.02),white,.012)
        # Props are outside the product slot, never over its artwork.
        box('ChoppingBoard',(.3,.035,.4),(-1.08,cy+.21,1.12),oak,.025)
        box('Canister',(.15,.15,.24),(1.03,cy,.9+.12),(.48,.31,.13),.035)
        box('CanisterLid',(.16,.16,.025),(1.03,cy,1.1525),oak,.008)
    extent=max(w,h if flat else d,h if not flat else .0)
    target=[0.,0.,support+(d/2 if flat else h*.5)]
    distance=max(extent*2.6,1.05 if slot=='SURFACE' else 2.0)
    side={'THREE_QUARTER':.58,'LEFT':-.58,'FRONT':0.}[view]
    camera={'location':[distance*side,-distance,target[2]+distance*(.85 if flat else .35)],
            'lookAt':target,'focalLengthMm':48.}
    result={'templateId':scene,'version':1,'rendererContract':'FURNISHED_SCENE_V1','slot':slot,
            'view':view,'supportHeightM':support,'productMatrix':transform,'camera':camera,
            'boxes':boxes,'worldColor':[.72,.77,.84],'worldStrength':.35,
            'lights':[{'name':'Window','location':[-1.8,-2.,3.2],'target':[0,0,.5],'energy':550.,'size':3.,'color':[1.,.91,.78]},
                      {'name':'Fill','location':[2.,-.3,2.4],'target':[0,0,.7],'energy':180.,'size':2.,'color':[.8,.9,1.]}],
            'productScale':1.,'physicalRoomTruth':False}
    return result


def identity(spec):
    return stable_hash(spec)


def validate_observation(manifest, observation):
    import math
    definition=manifest['spec'].get('sceneDefinition')
    if not definition: return
    draft=manifest['draft']
    expected=resolve(draft['scene'],draft['master'],manifest['spec'],draft.get('placement','AUTO'),draft.get('view','THREE_QUARTER'))
    digest=identity(expected)
    if definition!=expected or manifest.get('sceneHash')!=digest or manifest['spec'].get('sceneHash')!=digest or draft.get('sceneHash')!=digest:
        raise ValueError('場景版本或內容驗證失敗')
    actual=observation.get('presentationScene') or {}
    for key,value in {'sceneHash':digest,'templateId':definition['templateId'],'version':definition['version'],
                      'slot':definition['slot'],'view':definition['view'],'productScale':1.,
                      'productMatrix':definition['productMatrix'],'environmentCount':len(definition['boxes']),
                      'physicalRoomTruth':False}.items():
        if actual.get(key)!=value: raise ValueError('場景實際輸出與設定不符')
    rows=actual.get('products',[])
    wanted={p['componentId']:p for p in manifest['spec']['components']}
    if len(rows)!=len(wanted) or {p['componentId'] for p in rows}!=set(wanted):
        raise ValueError('場景商品板件不符')
    pose=definition['productMatrix']
    for row in rows:
        loc=wanted[row['componentId']]['location']
        expect=[list(r) for r in pose]
        for i in range(3): expect[i][3]=sum(pose[i][j]*loc[j] for j in range(3))+pose[i][3]
        got=row.get('matrixWorld',[])
        if row.get('linkedMesh') is not True or len(got)!=4 or any(len(r)!=4 for r in got):
            raise ValueError('場景未沿用原商品網格')
        if any(not math.isfinite(a) or abs(a-b)>1e-5 for r,s in zip(got,expect) for a,b in zip(r,s)):
            raise ValueError('場景商品位置或比例驗證失敗')


def catalog():
    return [{'id':sid,'label':LABELS[sid], 'version':1,
             'description':('沙發、茶几、畫框與立燈' if sid=='LIVING_ROOM' else '下櫃、吊櫃、檯面與廚房小物'),
             'families':['cabinet','mat','coaster'],'placements':deepcopy(PLACEMENTS),'views':deepcopy(VIEWS),
             'physicalRoomTruth':False} for sid in ('LIVING_ROOM','KITCHEN')]
