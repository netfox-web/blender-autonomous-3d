"""Versioned input meaning for existing masters; never a second master service.

Nonphysical declarations and immutable snapshots live beside the master. Measured
authority is a reserved kind: no reviewed CAD/measurement provider exists here.
Local trusted filesystem semantics, not protection from a hostile administrator.
"""
import re
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import Field

from fox3d import asset_usage, model_categories, product_models as models
from fox3d.ids import new_id, stable_hash
from fox3d.recipe_3d import atomic_json, input_hash
from fox3d.recipe_workbench import timestamp

VERSION = 1
Kind = Literal['SYNTHETIC_FIXTURE', 'REFERENCE_RECIPE', 'OPERATOR_DECLARED_UNMEASURED', 'MEASURED_OR_CAD_AUTHORITY']


class Provenance(models.Strict):
    createdAt: str = Field(min_length=1)
    createdBy: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    approvedBy: None = None
    physicalApproval: Literal[False] = False


class Declaration(models.Strict):
    version: Literal[1]
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    tenantId: str
    masterId: str
    masterRevision: int = Field(ge=1)
    masterInputHash: str
    kind: Kind
    provenance: Provenance


class Control(models.Strict):
    version: Literal[1]
    currentId: str = Field(pattern=r'^[a-f0-9-]{36}$')
    revokedIds: list[str]


def folder(root, tenant, mid):
    models.get(root, tenant, mid)  # Validate tenant/model before using its path.
    # Short, tenant-scoped storage path also works under Windows MAX_PATH.
    return Path(root)/'master-authority'/stable_hash({'tenant': tenant, 'master': mid})[:24]


def _load(path):
    from fox3d.model_batches import _load as checked_load
    return checked_load(path)


def _once(path, value):
    from fox3d.model_batches import _once as exclusive_write
    exclusive_write(path, value)


def _kind(kind, draft):
    if kind == 'MEASURED_OR_CAD_AUTHORITY':
        raise ValueError('尚未接入已核准的實測／CAD 證據與工程簽核，不可升級實物權威')
    if kind == 'REFERENCE_RECIPE' and draft['geometry'] != 'RECIPE_REFERENCE':
        raise ValueError('Recipe 參考權威必須連結原始 Recipe 快照')


def _new(base, tenant, item, kind, actor, decision):
    _kind(kind, item['draft'])
    value = Declaration(version=VERSION, id=new_id(), tenantId=tenant, masterId=item['id'],
                        masterRevision=item['revision'], masterInputHash=item['inputHash'], kind=kind,
                        provenance=Provenance(createdAt=timestamp(), createdBy=actor, decision=decision)).model_dump()
    _once(base/'declarations'/(value['id']+'.json'), value)
    return value


def declare(root, tenant, item, kind, *, actor, reason):
    """Explicit nonphysical declaration; changing it revokes the previous decision.

    Used by fixture setup and trusted operators; no API accepts arbitrary physical
    approval. This cannot grant measured, surface, print or manufacturing authority.
    """
    base = folder(root, tenant, item['id']); base.mkdir(parents=True, exist_ok=True)
    if models.get(root, tenant, item['id'])['revision'] != item['revision']:
        raise ValueError('母版版本已變更')
    with FileLock(str(base/'write.lock'), timeout=10):
        previous = Control.model_validate(_load(base/'control.json')) if (base/'control.json').exists() else None
        value = _new(base, tenant, item, kind, actor, reason)
        revoked = previous.revokedIds + [previous.currentId] if previous else []
        atomic_json(base/'control.json', Control(version=VERSION, currentId=value['id'], revokedIds=revoked).model_dump())
    return value


def revoke(root, tenant, mid):
    base = folder(root, tenant, mid)
    with FileLock(str(base/'write.lock'), timeout=10):
        control = Control.model_validate(_load(base/'control.json'))
        control.revokedIds = list(dict.fromkeys(control.revokedIds + [control.currentId]))
        atomic_json(base/'control.json', control.model_dump())


def _declaration(root, tenant, item):
    base = folder(root, tenant, item['id']); base.mkdir(parents=True, exist_ok=True)
    with FileLock(str(base/'write.lock'), timeout=10):
        if not (base/'control.json').exists():
            if list((base/'declarations').glob('*.json')):
                raise ValueError('來源權威控制紀錄遺失')
            kind = 'REFERENCE_RECIPE' if item['draft']['geometry'] == 'RECIPE_REFERENCE' else 'OPERATOR_DECLARED_UNMEASURED'
            value = _new(base, tenant, item, kind, 'MASTER_INPUT_RULE_V1', 'Source fields only; no independent physical approval')
            atomic_json(base/'control.json', Control(version=VERSION, currentId=value['id'], revokedIds=[]).model_dump())
        control = Control.model_validate(_load(base/'control.json'))
        if control.currentId in control.revokedIds:
            raise ValueError('來源權威已撤銷，請重新核對')
        value = Declaration.model_validate(_load(base/'declarations'/(control.currentId+'.json'))).model_dump()
        if value['tenantId'] != tenant or value['masterId'] != item['id']:
            raise ValueError('來源權威不屬於此工作區／模型')
        if value['masterRevision'] != item['revision'] or value['masterInputHash'] != item['inputHash']:
            kind = 'REFERENCE_RECIPE' if item['draft']['geometry'] == 'RECIPE_REFERENCE' else value['kind']
            if kind == 'REFERENCE_RECIPE' and item['draft']['geometry'] != 'RECIPE_REFERENCE':
                kind = 'OPERATOR_DECLARED_UNMEASURED'
            value = _new(base, tenant, item, kind, 'MASTER_INPUT_RULE_V1', 'New master revision; retains nonphysical status')
            control.currentId = value['id']; atomic_json(base/'control.json', control.model_dump())
        _kind(value['kind'], item['draft'])
        return value


def _references(draft):
    return {key: stable_hash(draft.get(key)) for key in ('dimensionEvidence', 'structureEvidence', 'recipeReference', 'printFaces')}


def snapshot(root, tenant, item, selection):
    current = models.get(root, tenant, item['id'])
    if (current['revision'], current['inputHash']) != (item['revision'], item['inputHash']):
        raise ValueError('母版版本已變更，請重新核對')
    declaration = _declaration(root, tenant, item)
    artworks = {aid: asset_usage.require_artwork(root, tenant, aid) for aid in sorted({p['assetId'] for p in selection['placements']})}
    value = {'authorityVersion': VERSION, 'tenantId': tenant, 'masterId': item['id'],
             'masterRevision': item['revision'], 'masterInputHash': item['inputHash'],
             'geometryAuthorityKind': declaration['kind'], 'geometryReferenceHashes': _references(item['draft']),
             'dimensionAuthorityStatus': 'UNMEASURED', 'surfaceAuthorityStatus': 'UNVERIFIED',
             'artworkAuthority': artworks, 'artworkAuthorityHash': stable_hash(artworks),
             'classificationMetadata': model_categories.get(root, tenant, item['id'], item=item),
             'declaration': declaration, 'declarationHash': stable_hash(declaration)}
    binding = {'snapshot': value, 'hash': stable_hash(value)}
    target = folder(root, tenant, item['id'])/'snapshots'/(binding['hash']+'.json')
    try: _once(target, value)
    except FileExistsError:
        if _load(target) != value: raise ValueError('來源權威快照已損壞')
    return binding


def identity(binding, tenant, mid, revision, master_hash):
    """Pure validation also binds the exact authority to request/row identity."""
    try:
        if set(binding) != {'snapshot', 'hash'} or not re.fullmatch(r'[a-f0-9]{64}', binding['hash']):
            raise ValueError('來源權威識別不完整')
        value = binding['snapshot']
        if (type(value['authorityVersion']) is not int or value['authorityVersion'] != VERSION
                or binding['hash'] != stable_hash(value)
                or (value['tenantId'], value['masterId'], value['masterRevision'], value['masterInputHash']) != (tenant, mid, revision, master_hash)):
            raise ValueError('來源權威版本／雜湊／模型身分不符')
        declaration = Declaration.model_validate(value['declaration']).model_dump()
        if (value['declarationHash'] != stable_hash(declaration) or value['geometryAuthorityKind'] != declaration['kind']
                or any(value[key] != declaration[key] for key in ('tenantId', 'masterId', 'masterRevision', 'masterInputHash'))
                or value['dimensionAuthorityStatus'] != 'UNMEASURED' or value['surfaceAuthorityStatus'] != 'UNVERIFIED'
                or value['artworkAuthorityHash'] != stable_hash(value['artworkAuthority'])):
            raise ValueError('來源權威依據不符')
        if declaration['kind'] == 'MEASURED_OR_CAD_AUTHORITY':
            raise ValueError('缺少已核准的實測／CAD authority provider')
        return value
    except (KeyError, TypeError) as exc:
        raise ValueError('來源權威快照不完整') from exc


def verify(root, tenant, selection, *, current):
    try:
        mid = selection['masterId']; item = models.get(root, tenant, mid)
        value = identity(selection['inputAuthority'], tenant, mid, selection['masterRevision'], selection['masterInputHash'])
        base = folder(root, tenant, mid); declaration = value['declaration']
        if _load(base/'snapshots'/(selection['inputAuthority']['hash']+'.json')) != value:
            raise ValueError('來源權威快照已變更')
        if _load(base/'declarations'/(declaration['id']+'.json')) != declaration:
            raise ValueError('來源權威聲明已變更')
        control = Control.model_validate(_load(base/'control.json'))
        if declaration['id'] in control.revokedIds or (current and control.currentId != declaration['id']):
            raise ValueError('來源權威已撤銷或被取代')
        original = _load(models.directory(root, tenant)/mid/'revisions'/(str(value['masterRevision'])+'.json'))
        if (original['inputHash'] != value['masterInputHash'] or input_hash(original['draft']) != value['masterInputHash']
                or original['draft'] != selection['master'] or _references(original['draft']) != value['geometryReferenceHashes']
                or input_hash(item['draft']) != item['inputHash']
                or item['inputHash'] != value['masterInputHash'] or (current and item['revision'] != value['masterRevision'])):
            raise ValueError('來源權威母版版本已過期')
        _kind(declaration['kind'], original['draft'])
        ids = {p['assetId'] for p in selection['placements']}
        if ids != set(value['artworkAuthority']): raise ValueError('圖稿權威身分不符')
        for aid, authority in value['artworkAuthority'].items():
            if asset_usage.require_artwork(root, tenant, aid) != authority:
                raise ValueError('圖稿權威版本已變更')
        return value
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError('來源權威缺少或不完整') from exc


def readiness(visual=False):
    return {'visualAssetReady': bool(visual), 'physicalGeometryAuthorityReady': False,
            'printSurfaceAuthorityReady': False, 'manufacturingReady': False, 'physicalPrintValidated': False}
