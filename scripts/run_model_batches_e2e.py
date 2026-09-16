"""Clean CODE HTTP/REAL Blender batch, retained-result and restart acceptance."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main(*, round2=False, round3=False):
    import httpx
    from PIL import Image, ImageDraw
    from fox3d import print_assets, asset_usage, product_models, model_compositions as c
    from fox3d.blender import find_blender
    from fox3d.recipe_3d import atomic_json, read_json
    from fox3d import model_batches as b
    from fox3d import variant_authority as authority
    from fox3d.ids import sha256_bytes
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise SystemExit('Formal acceptance requires clean CODE')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    round2 = round2 or round3
    eid=str(uuid.uuid4());base=ROOT/'.fox3d-work'/'batches'/eid[:8];base.mkdir(parents=True)
    data=base/'d';tenant='sonaqueen-home';models=[];assets=[]
    for kind,size in ([('HINGED_CABINET',(780,552))] if round2 else [('HINGED_CABINET',(780,552)),('RECTANGLE',(400,400))]):
        model=product_models.save(data,tenant,{'name':'FIXTURE '+kind,
            'family':'cabinet' if kind=='HINGED_CABINET' else 'coaster','geometry':kind,
            'widthMm':424. if kind=='HINGED_CABINET' else 100.,
            'depthMm':295. if kind=='HINGED_CABINET' else 5.,
            'heightMm':900. if kind=='HINGED_CABINET' else 100.,
            'panelMm':15.,'backMm':3.,'doorMm':15.,'gapMm':2.,'rows':3,
            'dimensionEvidence':'SYNTHETIC FIXTURE dimensions, not physical product truth',
            'structureEvidence':'SYNTHETIC rectangular static geometry'},0)
        authority.declare(data,tenant,model,'SYNTHETIC_FIXTURE',actor='REAL_ACCEPTANCE_FIXTURE_SETUP',
                          reason='Explicit synthetic dimensions; no physical measurement or CAD approval')
        models.append(model);group=[]
        for color in ['#ce923a','#8d51a8']:
            im=Image.new('RGB',size,color);draw=ImageDraw.Draw(im)
            draw.rectangle((0,0,size[0]//3,size[1]//2),fill='#1559c4')
            draw.rectangle((size[0]//2,size[1]//2,size[0]-1,size[1]-1),fill='#df3340')
            buf=io.BytesIO();im.save(buf,'PNG')
            a=print_assets.import_asset(data,tenant,buf.getvalue(),'synthetic-pattern.png')
            asset_usage.classify(data,tenant,a['id'],'ARTWORK','Synthetic asymmetric fixture',0);group.append(a)
        assets.append(group)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';log=(base/'server.log').open('w',encoding='utf-8');proc=None
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def start():
        p=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_recipe_admin.py'),'--port',str(port),'--data-root',str(data)],
            cwd=ROOT,env={**os.environ,'FOX3D_MOCK_BLENDER':'0','PYTHONIOENCODING':'utf-8'},stdout=log,stderr=log,creationflags=flags)
        for _ in range(120):
            if p.poll() is not None:raise RuntimeError('Server exited')
            try:
                if httpx.get(url+'/api/recipe-library/health',timeout=1,trust_env=False).status_code==200:return p
            except httpx.HTTPError:pass
            time.sleep(.5)
        p.terminate();raise RuntimeError('Server timeout')
    evidence={'evidenceId':eid,'codeCommit':sha,'workingTreeClean':True,'inputTruth':'SYNTHETIC_STATIC_FIXTURE',
              'physicalPrintValidated':False,'physicalProductGeometryTruth':False,'globalProductionReady':False,
              'productionReady':False,'generations':[],'round2':round2,'round3':round3,'batches':[],
              'manufacturingReady':False,'authorityVersion':authority.VERSION,'authorityKinds':['SYNTHETIC_FIXTURE']}
    try:
        proc=start()
        with httpx.Client(base_url=url,headers={'X-Tenant-Id':tenant},timeout=180,trust_env=False) as client:
            client.get('/admin/recipes/assets/model-batches.js').raise_for_status()
            for index,item in enumerate(models):
                mid=item['id'];path='/api/product-models/'+mid
                surfaces=client.get(path+'/composition').json()['surfaces'];selections=[]
                for aindex,asset in enumerate(assets[index]):
                    for scene in (['STUDIO','WARM_ROOM'] if index==0 and not round2 else ['STUDIO']):
                        selections.append({'sku':f'FIXTURE-{aindex+1}','scene':scene,
                            'placements':[{'componentId':f['componentId'],'assetId':asset['id']} for f in surfaces if f['componentId']!='back']})
                body={'expectedRevision':item['revision'],'inputHash':item['inputHash'],'assumptionsAccepted':True,
                      'batch':{'name':'REAL batch fixture','selections':selections}}
                response=client.post(path+'/composition/batch',json=body);response.raise_for_status()
                task=response.json()['taskId']
                duplicate=client.post(path+'/composition',json={k:v for k,v in {**body,'selection':selections[0]}.items() if k!='batch'})
                assert duplicate.status_code==422,duplicate.text
                deadline=time.monotonic()+len(selections)*930
                while time.monotonic()<deadline:
                    response=client.get(path+'/composition');response.raise_for_status();state=response.json()
                    if state['state'] not in {'queued','running'}:break
                    time.sleep(3)
                assert state['state']=='succeeded' and state['taskId']==task,state
                assert all(r['state']=='succeeded' and r['available'] for r in state['batch']['rows'])
                for verified in [state['batch'],*state['batch']['rows']]:
                    assert all(verified[key]==value for key,value in authority.readiness(True).items())
                batch_folder=c.folder_for(data,tenant,mid)/'batches'/task
                evidence['batches'].append({'batchId':task,'modelId':mid,'identityVersion':b.IDENTITY_VERSION,
                    'verifiedState':state['batch'],'request':read_json(batch_folder/'request.json'),
                    'requestSha256':sha256_bytes((batch_folder/'request.json').read_bytes()),
                    'terminal':read_json(batch_folder/'terminal.json'),
                    'rowReceipts':[read_json(batch_folder/(str(i)+'.json')) for i in range(len(selections))]})
                history=client.get(path+'/compositions').json()
                assert history['total']==len(selections) and all(r['available'] for r in history['items'])
                hashes=[];pixels=[]
                for row in history['items']:
                    gid=row['generationId'];folder=c.folder_for(data,tenant,mid)/'generations'/gid
                    manifest=c.generation(data,tenant,mid,gid,item)
                    reopen=subprocess.run([find_blender(),'-b',str(folder/'model.blend'),'--python-exit-code','1','--python',str(ROOT/'scripts/check_print_blend.py'),'--',str(folder)],capture_output=True,timeout=180,creationflags=flags)
                    (base/(gid[:8]+'-reopen.log')).write_bytes(reopen.stdout+reopen.stderr)
                    assert reopen.returncode==0 and b'PRINT_BLEND_REOPEN_PASS' in reopen.stdout
                    for name in ['beauty.png','front-closed.png','model.glb','model.blend','geometry.json']:
                        client.get(path+'/composition/files/'+name,params={'workspace':tenant,'generation':gid}).raise_for_status()
                    assert manifest['renderInfo']['realBlender'] is True and manifest['renderInfo']['usedMock'] is False
                    assert manifest['renderInfo']['blenderVersion']=='5.2.1 LTS'
                    assert manifest['renderInfo']['device']=='OPTIX' and manifest['renderInfo']['realOptix'] is True
                    hashes.append(manifest['spec']['engineeringHash']);pixels.append(manifest['files']['beauty.png'])
                    evidence['generations'].append({'modelId':mid,'generationId':gid,'sku':row['sku'],'scene':row['scene'],
                        'renderInfo':manifest['renderInfo'],'files':manifest['files'],
                        'sizes':{n:(folder/n).stat().st_size for n in manifest['files']},
                        'geometryHash':hashes[-1],'jobId':manifest['jobId'],'requestedJobId':manifest['requestedJobId'],
                        'cacheHit':manifest['cacheHit'],'blendReopen':True,
                        'inputAuthorityHash':manifest['inputAuthorityHash'],
                        'inputAuthority':manifest['draft']['inputAuthority']['snapshot'],
                        'publication':read_json(folder/'published.json'),'manifestSha256':sha256_bytes((folder/'manifest.json').read_bytes()),
                        'finitePixels':Image.open(folder/'beauty.png').size==(800,800) and any(a!=z for a,z in Image.open(folder/'beauty.png').convert('RGB').getextrema())})
                assert len(set(hashes))==1 and len(set(pixels))==len(selections)
                print(json.dumps({'model':index,'generations':len(selections),'history':'PASS'}),flush=True)
            proc.terminate();proc.wait(timeout=30);proc=start()
            for index,item in enumerate(models):
                path='/api/product-models/'+item['id'];history=client.get(path+'/compositions').json()
                assert all(r['available'] for r in history['items'])
                restored=client.get(path+'/composition');restored.raise_for_status()
                assert restored.json()['batch']['available']
                assert restored.json()['batch']['authorityHash']==evidence['batches'][index]['verifiedState']['authorityHash']
                for selection in evidence['batches'][index]['request']['draft']['selections']:
                    authority.verify(data,tenant,selection,current=True)
                if round2:
                    evidence['tamperMatrix']=round2_tamper_checks(client,path,data,tenant,item,restored.json())
                if round3:
                    evidence['authorityChecks']=round3_authority_checks(client,path,data,tenant,item,restored.json())
                gid=history['items'][0]['generationId']
                # Change geometry after restart: all old variants become unavailable.
                r=client.put(path,json={'expectedRevision':1,'draft':{**item['draft'],'widthMm':item['draft']['widthMm']+1}});r.raise_for_status()
                assert all(not r['available'] for r in client.get(path+'/compositions').json()['items'])
                assert client.get(path+'/composition').json()['batch']['available'] is False
                assert client.get(path+'/composition/files/model.glb',params={'workspace':tenant,'generation':gid}).status_code==409
                r=client.put(path,json={'expectedRevision':2,'draft':item['draft']});r.raise_for_status()
                assert all(r['available'] for r in client.get(path+'/compositions').json()['items'])
                assert not client.get(path+'/composition').json()['batch']['visualAssetReady']
                asset_usage.classify(data,tenant,assets[index][0]['id'],'REFERENCE','Revoked fixture',1)
                rows=client.get(path+'/compositions').json()['items']
                assert all(r['available']==(r['sku']=='FIXTURE-2') for r in rows)
                batch_state=client.get(path+'/composition').json()
                assert batch_state['state']=='failed' and not batch_state['batch']['available']
                invalid=next(r for r in rows if not r['available'])
                assert client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':invalid['generationId']}).status_code==409
                assert client.get(path+'/compositions',headers={'X-Tenant-Id':'other'}).status_code==404
            evidence.update(status='PASS',geometryPreserved=True,variantPixelsDistinct=True,
                            restartPreserved=True,staleBlocked=True,revokedBlocked=True,serialQueue=True)
    except Exception as exc:evidence.update(status='FAIL',error=str(exc));raise
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=30)
        atomic_json(base/'evidence.json',evidence);log.close()
        print(json.dumps({'evidenceFile':str(base/'evidence.json'),'status':evidence.get('status')}),flush=True)



def round2_tamper_checks(client,path,data,tenant,item,state):
    """REAL_LOGIC corruption trials against actual REAL published fixture outputs."""
    import copy
    from fox3d import model_compositions as c
    from fox3d.recipe_3d import atomic_json,read_json
    bid=state['taskId'];base=c.folder_for(data,tenant,item['id']);batch=base/'batches'/(bid+'.json')
    anchor=base/'batches'/bid;original=batch.read_bytes();service=(base/'state.json').read_bytes()
    terminal=(anchor/'terminal.json').read_bytes();results={}
    for kind in ['batchId','tenant','master','masterHash','revision','selectionHash','version','unknownVersion',
                 'insert','delete','reorder','duplicateGeneration','malformedGeneration','sku','scene','rowHash','rowIndex','truncation']:
        record=json.loads(original)
        if kind=='batchId':record['batchId']=str(uuid.uuid4())
        if kind=='tenant':record['tenantId']='other'
        if kind=='master':record['masterId']='other'
        if kind=='masterHash':record['masterInputHash']='tampered'
        if kind=='revision':record['sourceRevision']+=1
        if kind=='selectionHash':record['selectionHash']='tampered'
        if kind=='version':record.pop('identityVersion')
        if kind=='unknownVersion':record['identityVersion']=99
        if kind=='insert':record['rows'].append(copy.deepcopy(record['rows'][0]))
        if kind=='delete':record['rows'].pop()
        if kind=='reorder':record['rows'].reverse()
        if kind=='duplicateGeneration':record['rows'][0]['generationId']=record['rows'][1]['generationId']
        if kind=='malformedGeneration':record['rows'][0]['generationId']='../escape'
        if kind=='sku':record['rows'][0]['sku']='tampered'
        if kind=='scene':record['rows'][0]['scene']='COOL_ROOM'
        if kind=='rowHash':record['rows'][0]['selectionHash']='tampered'
        if kind=='rowIndex':record['rows'][0]['index']=1
        atomic_json(batch,record)
        if kind=='truncation':batch.write_text('{',encoding='utf-8')
        try:
            response=client.get(path+'/composition');assert response.status_code==422,response.text
            results[kind]={'status':'BLOCK','http':response.status_code}
        finally:batch.write_bytes(original)
    for file,field,label in [(anchor/'request.json','draft','requestContradiction'),
                             (base/'state.json','inputHash','serviceInputHash')]:
        raw=file.read_bytes();value=json.loads(raw)
        if field=='draft':value['draft']['name']='changed request'
        else:value[field]='tampered'
        try:
            atomic_json(file,value)
            assert client.get(path+'/composition').status_code==422
            results[label]={'status':'BLOCK'}
        finally:file.write_bytes(raw)
    receipt_file=anchor/'0.json';receipt_raw=receipt_file.read_bytes()
    try:
        receipt_file.unlink()
        assert client.get(path+'/composition').status_code==422
        results['succeededWithoutRowReceipt']={'status':'BLOCK'}
    finally:receipt_file.write_bytes(receipt_raw)
    for bad_task in [None,'../escape',str(uuid.uuid4())]:
        outer=json.loads(service);outer['taskId']=bad_task;atomic_json(base/'state.json',outer)
        try:
            assert client.get(path+'/composition').status_code==422
            results['outerTask:'+str(bad_task)]={'status':'BLOCK'}
        finally:(base/'state.json').write_bytes(service)
    gid=state['batch']['rows'][0]['generationId'];target=base/'generations'/gid
    for filename in ['published.json','manifest.json']:
        file=target/filename;raw=file.read_bytes()
        try:
            file.write_text('{}',encoding='utf-8')
            response=client.get(path+'/composition');response.raise_for_status();bad=response.json()
            assert bad['state']=='failed' and not bad['batch']['rows'][0]['available']
            download=client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':gid})
            assert download.status_code==409
            results[filename]={'status':'BLOCK','downloadHttp':409}
        finally:file.write_bytes(raw)
    for mode in ['cancelled','interrupted']:
        ending=json.loads(terminal);ending['state']=mode;atomic_json(anchor/'terminal.json',ending)
        try:
            assert client.get(path+'/composition').status_code==422
            results[mode+'Resurrection']={'status':'BLOCK'}
        finally:(anchor/'terminal.json').write_bytes(terminal)
    # Simulated interrupted row with a stray real publication: no terminal receipt,
    # no replay, no conversion to succeeded merely because a manifest is present.
    row_receipt=anchor/'1.json';receipt=row_receipt.read_bytes()
    try:
        row_receipt.unlink();(anchor/'terminal.json').unlink()
        interrupted=json.loads(original);interrupted['rows'][1]['state']='running';atomic_json(batch,interrupted)
        outer=json.loads(service);outer['state']='failed';atomic_json(base/'state.json',outer)
        response=client.get(path+'/composition');response.raise_for_status();value=response.json()
        assert value['state']=='interrupted'
        assert [r['state'] for r in value['batch']['rows']]==['succeeded','interrupted']
        assert value['batch']['rows'][0]['available'] and not value['batch']['rows'][1]['available']
        results['simulatedInterruptedStateWithRealStrayPublication']={'status':'BLOCK_REPLAY','retainedCompleted':True,'input':'SIMULATED_INTERRUPTION_REAL_ARTIFACTS'}
    finally:
        batch.write_bytes(original);row_receipt.write_bytes(receipt)
        (anchor/'terminal.json').write_bytes(terminal);(base/'state.json').write_bytes(service)
    restored=client.get(path+'/composition');restored.raise_for_status();assert restored.json()['batch']['available']
    results['restoredNonLatestDownload']={'status':'PASS'}
    client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':gid}).raise_for_status()
    return results


def round3_authority_checks(client,path,data,tenant,item,state):
    """REAL_LOGIC authority corruption trials using this run's real artifacts."""
    from fox3d import model_compositions as c, variant_authority as a, model_categories, product_models
    from fox3d.recipe_3d import atomic_json,read_json
    from fox3d.ids import stable_hash,sha256_bytes
    base=c.folder_for(data,tenant,item['id']);bid=state['taskId']
    request=read_json(base/'batches'/bid/'request.json');selection=request['draft']['selections'][0]
    binding=selection['inputAuthority'];authority_base=a.folder(data,tenant,item['id'])
    snapshot_file=authority_base/'snapshots'/(binding['hash']+'.json');snapshot_raw=snapshot_file.read_bytes()
    control_file=authority_base/'control.json';control_raw=control_file.read_bytes()
    gid=state['batch']['rows'][0]['generationId'];target=base/'generations'/gid
    results={}
    def blocked(label):
        response=client.get(path+'/composition');response.raise_for_status();batch=response.json()['batch']
        assert not batch['rows'][0]['available'] and not batch['visualAssetReady']
        assert not batch['manufacturingReady'] and not batch['physicalPrintValidated']
        download=client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':gid})
        assert download.status_code==409
        results[label]={'status':'BLOCK','visualAssetReady':False,'manufacturingReady':False,'downloadHttp':409}
    for change in ['snapshotHash','missingVersion','unknownVersion','crossTenant','forgedMeasured','missingSnapshot','referenceHash']:
        value=json.loads(snapshot_raw)
        if change=='snapshotHash':value['masterInputHash']='0'*64
        if change=='missingVersion':value.pop('authorityVersion')
        if change=='unknownVersion':value['authorityVersion']=99
        if change=='crossTenant':value['tenantId']='other'
        if change=='forgedMeasured':value['geometryAuthorityKind']='MEASURED_OR_CAD_AUTHORITY'
        if change=='referenceHash':value['geometryReferenceHashes']['dimensionEvidence']='0'*64
        try:
            atomic_json(snapshot_file,value)
            if change=='missingSnapshot':snapshot_file.unlink()
            blocked(change)
        finally:snapshot_file.write_bytes(snapshot_raw)
    for change in ['revoke','downgrade','missingControl']:
        try:
            if change=='revoke':a.revoke(data,tenant,item['id'])
            if change=='downgrade':a.declare(data,tenant,item,'OPERATOR_DECLARED_UNMEASURED',actor='ACCEPTANCE_TRIAL',reason='Nonphysical authority downgrade trial')
            if change=='missingControl':control_file.unlink()
            blocked(change)
        finally:control_file.write_bytes(control_raw)
    master_file=product_models.directory(data,tenant)/item['id']/'master.json';master_raw=master_file.read_bytes()
    try:
        master=json.loads(master_raw);master['draft']['widthMm']+=1;atomic_json(master_file,master)
        blocked('masterContentHashContradiction')
    finally:master_file.write_bytes(master_raw)
    manifest_file=target/'manifest.json';publication_file=target/'published.json'
    meta_file=target/'meta.json'
    manifest_raw=manifest_file.read_bytes();publication_raw=publication_file.read_bytes();meta_raw=meta_file.read_bytes()
    try:
        manifest=json.loads(manifest_raw);manifest['inputAuthorityHash']='0'*64
        atomic_json(manifest_file,manifest)
        # Even if the ordinary publication seal is recomputed, authority differs.
        atomic_json(publication_file,{'manifestSha256':sha256_bytes(manifest_file.read_bytes())})
        atomic_json(meta_file,{'manifestSha256':sha256_bytes(manifest_file.read_bytes())})
        blocked('publicationAuthorityMismatch')
    finally:manifest_file.write_bytes(manifest_raw);publication_file.write_bytes(publication_raw);meta_file.write_bytes(meta_raw)
    for key,expected in a.readiness(True).items():assert state['batch'][key]==expected
    category=model_categories.get(data,tenant,item['id'])
    model_categories.save(data,tenant,item['id'],'unclassified',category['revision'])
    fresh=client.get(path+'/composition');fresh.raise_for_status()
    assert fresh.json()['batch']['visualAssetReady'] and not fresh.json()['batch']['physicalGeometryAuthorityReady']
    retained=c.generation(data,tenant,item['id'],gid,item)['draft']['inputAuthority']
    assert retained==binding and retained['snapshot']['classificationMetadata']['revision']==category['revision']
    results['categoryMetadataOnly']={'status':'PASS','physicalGeometryAuthorityReady':False}
    results['historicalExactSnapshot']={'status':'PASS','hash':binding['hash'],'neverRebound':True}
    for kind in ['MEASURED_OR_CAD_AUTHORITY']:
        try:a.declare(data,tenant,item,kind,actor='AI/mock',reason='Rendered mesh dimensions are not measurement')
        except ValueError:results['forgedMeasuredDeclaration']={'status':'BLOCK'}
        else:raise AssertionError('Unreviewed measured authority accepted')
    results['restartExactAuthority']={'status':'PASS','authorityHash':state['batch']['authorityHash']}
    client.get(path+'/composition/files/beauty.png',params={'workspace':tenant,'generation':gid}).raise_for_status()
    results['restoredVisualDownload']={'status':'PASS','readiness':a.readiness(True)}
    return results

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--round2',action='store_true');parser.add_argument('--round3',action='store_true')
    args=parser.parse_args();main(round2=args.round2,round3=args.round3)
