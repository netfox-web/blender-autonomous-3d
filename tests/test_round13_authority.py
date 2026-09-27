"""Round 13 regression: synthetic bytes + actual validators, never REAL render evidence."""
import hashlib
import json
from pathlib import Path
import struct

import pytest
from PIL import Image

from fox3d import durability as d, print_preview as p, model_compositions as c
from fox3d.recipe_3d import atomic_json
from test_model_compositions import setup


@pytest.mark.parametrize('publisher', ['publish_binary', 'publish_bytes'])
def test_collision_preserves_unowned_temp_and_final(tmp_path, monkeypatch, publisher):
    source=tmp_path/'source';source.write_bytes(b'new complete bytes')
    final=tmp_path/'final';final.write_bytes(b'old valid final')
    collision=tmp_path/'.artifact.0123456789abcdef.tmp'
    collision.write_bytes(b'unrelated owned bytes')
    monkeypatch.setattr(d.secrets,'token_hex',lambda n:'0123456789abcdef')
    before={x.name:x.read_bytes() for x in tmp_path.iterdir()}
    argument=source if publisher=='publish_binary' else lambda stream:stream.write(source.read_bytes())
    with pytest.raises(FileExistsError):getattr(d,publisher)(argument,final)
    assert {x.name:x.read_bytes() for x in tmp_path.iterdir()}==before


@pytest.mark.parametrize('publisher', ['publish_binary', 'publish_bytes'])
def test_owned_temp_removed_on_precommit_failure(tmp_path, publisher):
    source=tmp_path/'source';source.write_bytes(b'new complete bytes')
    final=tmp_path/'final';final.write_bytes(b'old valid final')
    argument=source if publisher=='publish_binary' else lambda stream:stream.write(source.read_bytes())
    with pytest.raises(ValueError,match='size mismatch'):
        getattr(d,publisher)(argument,final,expected_size=999)
    assert final.read_bytes()==b'old valid final'
    assert not list(tmp_path.glob('.artifact.*.tmp'))


def authority_fixture(tmp_path, chain):
    """Construct format-valid MOCK bytes; do not patch any production validator."""
    model,_,_=setup(tmp_path)
    gid='11111111-1111-4111-8111-111111111111'
    jid='22222222-2222-4222-8222-222222222222'
    base=c.folder_for(tmp_path,'t',model['id']) if chain=='composition' else p.folder_for(tmp_path,'t',jid)
    target=base/'generations'/gid;target.mkdir(parents=True)
    part={'componentId':'surface','partName':'fixture','size':[.1,.005,.05],'location':[0.,0.,.025]}
    package={'sku':'MOCK','packageHash':'fixture-package','engineeringHash':'fixture-geometry','placements':[]}
    Image.new('RGB',(800,800),'red').save(target/'beauty.png')
    (target/'front-closed.png').write_bytes((target/'beauty.png').read_bytes())
    (target/'model.blend').write_bytes(b'BLENDER'+b'\0'*100)
    graph=json.dumps({'meshes':[{}]}).encode()
    (target/'model.glb').write_bytes(struct.pack('<4sIIII',b'glTF',2,20+len(graph),len(graph),0x4e4f534a)+graph)
    atomic_json(target/'geometry.json',{'parts':[part]})
    # Flags are deliberate fixture data exercising validators, not provenance.
    atomic_json(target/'golden-observation.json',{'realBlender':True,'usedMock':False,
        'sku':package['sku'],'packageHash':package['packageHash'],'engineeringHash':package['engineeringHash'],
        'parts':[part],'artwork':[]})
    manifest={'generationId':gid,'historyVersion':1,'sourceRevision':model['revision'],
        'draft':{'masterId':model['id'],'masterInputHash':model['inputHash'],'masterRevision':model['revision'],'sku':'MOCK'},
        'spec':{'components':[part]},'package':package,'renderInfo':{'realBlender':True,'usedMock':False},
        'files':{name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in p.FILES}}
    atomic_json(target/'manifest.json',manifest)
    digest=hashlib.sha256((target/'manifest.json').read_bytes()).hexdigest()
    atomic_json(target/'meta.json',{'manifestSha256':digest})
    atomic_json(target/'published.json',{'manifestSha256':digest})
    atomic_json(base/'latest.json',{'generationId':gid,'manifestSha256':digest})
    atomic_json(base/'state.json',{'state':'succeeded','progress':100})
    def status():
        return c.status(tmp_path,'t',model['id'],current_draft=model) if chain=='composition' else p.status(tmp_path,'t',jid)
    assert p.validate(target)==manifest
    assert status()['generated']
    return model,gid,target,status


@pytest.mark.parametrize('chain',['composition','print'])
@pytest.mark.parametrize('authority',['manifest.json','meta.json'])
@pytest.mark.parametrize('damage',['symlink_same_bytes','directory','missing','reported_symlink','reported_nonregular'])
def test_real_validator_and_callers_reject_authority_type(tmp_path_factory,monkeypatch,chain,authority,damage):
    tmp_path=tmp_path_factory.mktemp('r13')
    model,gid,target,status=authority_fixture(tmp_path,chain)
    path=target/authority;original=path.read_bytes()
    if damage=='symlink_same_bytes':
        outside=tmp_path/'same-valid-bytes.json';outside.write_bytes(original)
        path.unlink()
        try:path.symlink_to(outside)
        except OSError:pytest.skip('actual symlink creation unavailable')
    elif damage in {'directory','missing'}:
        path.unlink()
        if damage=='directory':path.mkdir()
    else:
        # Deterministic FAULT_INJECTION: guard branch on otherwise valid bytes.
        # Complements actual OS symlinks/directories; never labelled REAL_SYMLINK.
        method='is_symlink' if damage=='reported_symlink' else 'is_file'
        original_method=getattr(Path,method)
        monkeypatch.setattr(Path,method,lambda self: damage=='reported_symlink' if self==path else original_method(self))
    with pytest.raises(ValueError,match='manifest/meta authority is not regular'):p.validate(target)
    for _ in range(2):
        result=status()
        assert not result['generated'] and result['manifest'] is None and result['generationId'] is None
        assert result['error']
    if chain=='composition':
        with pytest.raises(ValueError):c.generation(tmp_path,'t',model['id'],gid,model)

@pytest.mark.parametrize('publisher',['publish_binary','publish_bytes'])
def test_mutation_unowned_cleanup_is_detected(tmp_path,monkeypatch,publisher):
    """Run the preservation regression with its specific ownership guard removed."""
    import inspect
    source=inspect.getsource(getattr(d,publisher))
    needle='if owned and temporary.exists():'
    assert source.count(needle)==1
    namespace=dict(vars(d))
    exec(compile(source.replace(needle,'if temporary.exists():'),'<ownership-guard-mutant>','exec'),namespace)
    monkeypatch.setattr(d,publisher,namespace[publisher])
    with pytest.raises(AssertionError):
        test_collision_preserves_unowned_temp_and_final(tmp_path,monkeypatch,publisher)


@pytest.mark.parametrize('chain',['composition','print'])
@pytest.mark.parametrize('authority',['manifest.json','meta.json'])
@pytest.mark.parametrize('guard',['symlink','regular'])
def test_mutation_authority_guard_is_detected(tmp_path_factory,monkeypatch,chain,authority,guard):
    """Remove one guard; valid bytes must reach the negative regression assertion."""
    import inspect
    source=inspect.getsource(p.validate)
    needle='authority.is_symlink()' if guard=='symlink' else 'not authority.is_file()'
    assert source.count(needle)==1
    namespace=dict(vars(p))
    exec(compile(source.replace(needle,'False'),'<authority-guard-mutant>','exec'),namespace)
    monkeypatch.setattr(p,'validate',namespace['validate'])
    damage='reported_symlink' if guard=='symlink' else 'reported_nonregular'
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_real_validator_and_callers_reject_authority_type(tmp_path_factory,monkeypatch,chain,authority,damage)
