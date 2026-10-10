"""Product navigation metadata; never part of geometry or artwork authority."""
from filelock import FileLock

from fox3d import product_models as models
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.recipe_workbench import DraftConflict, timestamp


def node(key, label, family=None, *, children=None, subtype='other', rows=None):
    result = {'id': key, 'label': label}
    if children is not None:
        result['children'] = children
    else:
        result['draftDefaults'] = {'family': family, 'subtype': subtype, 'rows': rows,
                                   'geometry': 'PENDING'}
    return result


def cabinet_group(kind, label):
    return node(kind, label, children=[
        node(f'{kind}_{n}', f'{n} 層{label}', 'cabinet', subtype=kind, rows=n)
        for n in range(2, 6)
    ] + [node(f'{kind}_other', '其他層數／待確認', 'cabinet', subtype=kind)])


TREE = [
    node('floor_mat', '地墊', 'mat'), node('coaster', '杯墊', 'coaster'),
    node('wash_mat', '洗漱墊', 'mat'),
    node('wood', '木櫃', children=[cabinet_group('open', '空櫃'), cabinet_group('hinged', '門櫃'),
        node('sliding', '滑門櫃', 'cabinet'), node('bookcase', '書櫃', 'cabinet', subtype='bookcase'),
        node('wood_other', '其他木櫃／待確認', 'cabinet')]),
    node('bedside', '床邊櫃', 'cabinet', subtype='bedside'),
    node('rotating', '旋轉木櫃', 'cabinet'),
    node('other_products', '其他商品', children=[node('curtain', '門簾', 'curtain'),
        node('mask_box', '口罩收納盒', 'mask_box'), node('storage_box_50', '50 入收納盒', 'storage_box_50'),
        node('spray_bottle', '噴瓶', 'spray_bottle')]),
    node('unclassified', '待分類'),
]


def flatten(nodes=TREE, prefix=()):
    result = {}
    for item in nodes:
        path = (*prefix, item['label'])
        result[item['id']] = {**item, 'path': list(path)}
        result.update(flatten(item.get('children', []), path))
    return result


NODES = flatten()


def inferred(draft):
    """Use explicit model fields only, never filenames, artwork or dimensions."""
    family = draft['family']
    if family != 'cabinet':
        return {'mat': 'floor_mat'}.get(family, family if family in NODES else 'unclassified')
    subtype = draft.get('subtype', 'other')
    reference = (draft.get('recipeReference') or {}).get('draft', {}).get('family')
    if reference == 'ROW_SLIDING_CABINET':
        return 'sliding'
    if reference == 'STAGGERED_OPEN_CUBBY':
        return 'bookcase'
    if reference == 'STACKED_HINGED_CABINET':
        subtype = 'hinged'
    if subtype in {'bedside', 'bookcase'}:
        return subtype
    if subtype in {'open', 'hinged'}:
        rows = draft.get('rows')
        return f'{subtype}_{rows}' if rows in {2, 3, 4, 5} else f'{subtype}_other'
    return 'wood_other'


def get(root, tenant, mid, *, item=None):
    item = item or models.get(root, tenant, mid)
    saved = read_json(models.directory(root, tenant) / mid / 'classification.json')
    key = saved.get('categoryId', inferred(item['draft']))
    if key not in NODES or 'children' in NODES[key]:
        raise ValueError('模型分類紀錄無效，請檢查分類資料')
    return {'categoryId': key, 'path': NODES[key]['path'], 'revision': saved.get('revision', 0),
            'source': 'OPERATOR' if saved else 'MODEL_FIELDS', 'updatedAt': saved.get('updatedAt'),
            'geometryAuthority': False}


def save(root, tenant, mid, category_id, expected_revision):
    item = models.get(root, tenant, mid)
    category = NODES.get(category_id)
    if not category or 'children' in category:
        raise ValueError('請選擇最下層的商品分類')
    family = category['draftDefaults']['family']
    if family and family != item['draft']['family']:
        raise ValueError('分類與商品類別不符；請先核對商品資料，再選擇相符分類')
    folder = models.directory(root, tenant) / mid
    with FileLock(str(folder / 'classification.lock'), timeout=3):
        current = get(root, tenant, mid, item=item)
        if expected_revision != current['revision']:
            raise DraftConflict('分類已被修改，請重新載入分類再儲存')
        value = {'categoryId': category_id, 'revision': expected_revision + 1, 'updatedAt': timestamp()}
        atomic_json(folder / 'classification-revisions' / f"{value['revision']}.json", value)
        atomic_json(folder / 'classification.json', value)
    return get(root, tenant, mid, item=item)


def inventory(root, tenant):
    items = models.listing(root, tenant)
    for item in items:
        item['classification'] = get(root, tenant, item['id'], item=item)
    return {'items': items, 'categoryTree': TREE}
