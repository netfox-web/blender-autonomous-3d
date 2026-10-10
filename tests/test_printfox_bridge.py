import copy
import io
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from fox3d import printfox_bridge as b
from fox3d.printfox_api import printfox_router
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.ids import sha256_bytes

TOKEN = 'SYNTHETIC-TEST-ONLY-TOKEN'
RID = '11111111-1111-4111-8111-111111111111'


class Remote:
    def __init__(self):
        image = Image.new('RGB', (1200, 800), (30, 80, 100))
        buf = io.BytesIO(); image.save(buf, 'PNG'); self.raw = buf.getvalue()
        self.items = [{'id':'src_1','title':'Fixture art','source':'generated','thumb_url':'/thumbs/fixture.png',
                       'meta':{'filename':'fixture.png','job_id':'previous_job','seed':42}}]
        self.job = None; self.posts = 0; self.cancels = 0; self.timeout = False
        self.download_redirect = False; self.oversize = False

    def handle(self, request):
        assert request.headers.get('x-console-token') == TOKEN
        path = request.url.path
        if path == '/api/status': return httpx.Response(200, json={'workers_online':1,'queue':0,'designs':1})
        if path == '/api/designs': return httpx.Response(200, json={'designs': self.items})
        if path == '/api/designs/src_1/download':
            if self.download_redirect: return httpx.Response(302, headers={'location':'http://elsewhere.invalid/art'})
            if self.oversize: return httpx.Response(200, content=b'x', headers={'content-length':str(b.assets.MAX_BYTES + 1)})
            return httpx.Response(200, content=self.raw)
        if path == '/thumbs/fixture.png': return httpx.Response(200, content=self.raw)
        if path == '/api/jobs' and request.method == 'POST':
            self.posts += 1
            data = json.loads(request.content)
            self.job = {**data,'id':'job_1','status':'pending','progress':0}
            if self.timeout: raise httpx.ReadTimeout('simulated uncertain response')
            return httpx.Response(200, json={'job':self.job})
        if path == '/api/jobs': return httpx.Response(200, json={'jobs':[self.job] if self.job else []})
        if path == '/api/jobs/job_1': return httpx.Response(200, json={'job':self.job})
        if path == '/api/jobs/job_1/cancel':
            self.cancels += 1; self.job['status']='canceled'; return httpx.Response(200,json={'job':self.job})
        raise AssertionError((request.method, path))

    def client(self, session=None):
        return b.Client(session or b.Session('t',b.DEFAULT_URL,TOKEN), httpx.MockTransport(self.handle))


def request_data():
    return {'requestId':RID,'prompt':'blue botanical design','count':1,'size':'wide','engine':'comfyui'}


@pytest.mark.parametrize('url', ['file:///tmp/x','http://user:pass@host','http://host/path','https://host/?token=x','http://host/#x'])
def test_origin_cannot_accept_browser_paths_or_credentials(tmp_path, url):
    atomic_json(tmp_path/'printfox-connection.json', {'baseUrl':url})
    with pytest.raises(b.BridgeError): b.origin(tmp_path)


def test_sessions_tenant_origin_expiry_and_secret_repr():
    sessions=b.Sessions(); sid=sessions.add('t',b.DEFAULT_URL,TOKEN)
    s=sessions.get(sid,'t',b.DEFAULT_URL)
    assert TOKEN not in repr(s)
    for tenant,origin in [('other',b.DEFAULT_URL),('t','http://other')]:
        with pytest.raises(b.BridgeError):sessions.get(sid,tenant,origin)
    s.expires=time.monotonic()-1
    with pytest.raises(b.BridgeError):sessions.get(sid,'t',b.DEFAULT_URL)


def test_import_native_bytes_provenance_and_no_secret(tmp_path):
    remote=Remote(); client=remote.client()
    listing=client.designs(); assert listing['items'][0]['jobId']=='previous_job'
    a=client.import_design(tmp_path,'t','src_1')
    assert a['id']==sha256_bytes(remote.raw)
    meta,raw=b.assets.asset(tmp_path,'t',a['id']); assert raw==remote.raw
    assert meta['provenance']['generation']['seed']==42
    assert not meta['provenance']['physicalDimensionsVerified']
    remote.items[0]['id']='src_2' # existing bytes may have more than one source identity
    for p in tmp_path.rglob('*.json'):assert TOKEN not in p.read_text(encoding='utf-8')
    thumb=Image.open(io.BytesIO(client.thumbnail('src_1'))); assert max(thumb.size)<=600


@pytest.mark.parametrize('url',['http://elsewhere/art','//elsewhere/art','/thumbs/../secret','/thumbs/%252e%252e/secret','/designs/secret','/thumbs/a?token=x','/thumbs/a\\b'])
def test_thumbnail_origin_and_path_boundary(url):
    remote=Remote();remote.items[0]['thumb_url']=url;client=remote.client();client.designs()
    with pytest.raises(b.BridgeError):client.thumbnail('src_1')


@pytest.mark.parametrize('attribute',['download_redirect','oversize'])
def test_download_never_follows_redirects_or_oversize(tmp_path,attribute):
    remote=Remote();setattr(remote,attribute,True)
    with pytest.raises(b.BridgeError):remote.client().import_design(tmp_path,'t','src_1')
    assert not list(tmp_path.rglob('asset.json'))


def test_bounded_generation_idempotent_and_own_cancel(tmp_path):
    remote=Remote();client=remote.client();body=request_data()
    a=b.generate(tmp_path,'t',client,body)
    assert b.generate(tmp_path,'t',client,body)==a and remote.posts==1
    assert remote.job['params']['continuous'] is False and remote.job['params']['per_style']==1
    assert remote.job['type']=='generate' and remote.job['params']['engine']=='comfyui'
    with pytest.raises(b.BridgeError):b.generate(tmp_path,'t',client,{**body,'prompt':'different'})
    with pytest.raises(b.BridgeError):b.update_task(tmp_path,'other',client,RID,cancel=True)
    assert remote.cancels==0
    assert b.update_task(tmp_path,'t',client,RID,cancel=True)['state']=='canceled'
    assert remote.cancels==1


def test_uncertain_post_restart_reconciliation_no_duplicate(tmp_path):
    remote=Remote();remote.timeout=True;body=request_data()
    a=b.generate(tmp_path,'t',remote.client(),body)
    assert a['state']=='submission_unknown' and remote.posts==1
    assert b.generate(tmp_path,'t',remote.client(),body)['state']=='submission_unknown'
    assert remote.posts==1
    remote.timeout=False
    reconciled=b.update_task(tmp_path,'t',remote.client(),RID)
    assert reconciled['remoteJobId']=='job_1' and reconciled['state']=='pending'
    assert remote.posts==1


def test_missing_uncertain_job_stays_uncertain_and_tamper_cannot_cancel(tmp_path):
    remote=Remote();remote.timeout=True;b.generate(tmp_path,'t',remote.client(),request_data())
    job=remote.job;remote.job=None
    assert b.update_task(tmp_path,'t',remote.client(),RID)['state']=='submission_unknown'
    remote.job=job;remote.job['params']['per_style']=4
    with pytest.raises(b.BridgeError):b.update_task(tmp_path,'t',remote.client(),RID,cancel=True)
    assert remote.cancels==0 and remote.posts==1


def test_request_schema_blocks_unbounded_generation():
    for changes in [{'count':5},{'count':True},{'continuous':True},{'engine':'unknown'},{'size':'custom'}]:
        with pytest.raises(ValueError):b.Generate.model_validate({**request_data(),**changes})


def app_for(root,remote):
    app=FastAPI();app.include_router(printfox_router(lambda:SimpleNamespace(root=root),remote.client));return app


def test_http_connection_import_tasks_logout_restart_and_secret_redaction(tmp_path):
    remote=Remote(); app=app_for(tmp_path,remote)
    with TestClient(app) as c:
        c.headers['X-Tenant-Id']='t';root=b.PREFIX
        assert not c.get(root+'/connection').json()['connected']
        assert c.get(root+'/designs').status_code==401
        bad=c.post(root+'/connection',json={'token':TOKEN,'other':True})
        assert bad.status_code==422 and TOKEN not in bad.text
        response=c.post(root+'/connection',json={'token':TOKEN})
        assert response.status_code==200 and TOKEN not in response.text
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert c.get(root+'/designs').json()['items'][0]['id']=='src_1'
        assert c.get(root+'/designs/src_1/preview?workspace=t').status_code==200
        assert c.get(root+'/designs/src_1/preview?workspace=other').status_code==401
        assert c.post(root+'/designs/src_1/import').json()['id']==sha256_bytes(remote.raw)
        assert c.post(root+'/tasks',json=request_data()).json()['remoteJobId']=='job_1'
        assert c.get(root+'/tasks').json()['items'][0]['requestId']==RID
        cookies=dict(c.cookies)
        with TestClient(app_for(tmp_path,remote)) as restarted:
            restarted.cookies.update(cookies)
            assert restarted.get(root+'/designs',headers={'X-Tenant-Id':'t'}).status_code==401
        assert c.delete(root+'/connection').status_code==200
        assert c.get(root+'/designs').status_code==401
    for p in tmp_path.rglob('*.json'): assert TOKEN not in p.read_text(encoding='utf-8')
