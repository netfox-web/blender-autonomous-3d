"""Same-origin operator UI endpoints for PrintFox design generation/import."""
import json

from fastapi import APIRouter, Header, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from PIL import Image
from filelock import Timeout

from fox3d import printfox_bridge as bridge
from fox3d.print_assets import workspace
from fox3d.recipe_3d import read_json


def printfox_router(provider, client_factory=None):
    r = APIRouter(prefix=bridge.PREFIX)
    sessions = bridge.Sessions()
    factory = client_factory or bridge.Client

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except bridge.BridgeError as e:
            raise HTTPException(e.status, str(e)) from None
        except Timeout:
            raise HTTPException(409, '此請求正在處理，請稍後更新狀態') from None
        except (ValueError, KeyError, TypeError, OSError, Image.DecompressionBombError):
            raise HTTPException(422, '資料格式或圖稿不符，請檢查原稿與連線設定') from None

    def context(request, tenant):
        root = provider().root
        guard(workspace, root, tenant)
        base = guard(bridge.origin, root)
        session = guard(sessions.get, request.cookies.get(bridge.COOKIE), tenant, base)
        return root, factory(session)

    @r.get('/connection')
    def status(request: Request, x_tenant_id: str | None = Header(None)):
        root = provider().root
        guard(workspace, root, x_tenant_id)
        base = guard(bridge.origin, root)
        try:
            session = sessions.get(request.cookies.get(bridge.COOKIE), x_tenant_id, base)
        except bridge.BridgeError:
            return {'baseUrl': base, 'connected': False}
        return {'baseUrl': base, 'connected': True, 'status': guard(factory(session).status)}

    @r.post('/connection')
    async def connect(request: Request, x_tenant_id: str | None = Header(None)):
        root = provider().root
        guard(workspace, root, x_tenant_id)
        # Parse credentials here so validation responses never echo password input.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 8192:
                raise HTTPException(413, '連線資料過長')
        try:
            body = json.loads(raw)
            token = body['token']
            if set(body) != {'token'} or not isinstance(token, str) or not 1 <= len(token) <= 4096 or '\r' in token or '\n' in token:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, '請輸入有效的 PrintFox Token') from None
        base = guard(bridge.origin, root)
        remote_status = await run_in_threadpool(guard, factory(bridge.Session(x_tenant_id, base, token)).status)
        sessions.remove(request.cookies.get(bridge.COOKIE))
        sid = guard(sessions.add, x_tenant_id, base, token)
        response = JSONResponse({'connected': True, 'baseUrl': base, 'status': remote_status})
        response.set_cookie(bridge.COOKIE, sid, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', path=bridge.PREFIX, max_age=3600)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @r.delete('/connection')
    def disconnect(request: Request, x_tenant_id: str | None = Header(None)):
        guard(workspace, provider().root, x_tenant_id)
        # A disconnect is idempotent, even after an expired session/restart.
        sessions.remove(request.cookies.get(bridge.COOKIE))
        response = JSONResponse({'connected': False})
        response.delete_cookie(bridge.COOKIE, path=bridge.PREFIX)
        return response

    @r.get('/designs')
    def designs(request: Request, q: str = Query('', max_length=150), offset: int = Query(0, ge=0),
                x_tenant_id: str | None = Header(None)):
        _, client = context(request, x_tenant_id)
        return guard(client.designs, q, offset)

    @r.get('/designs/{did}/preview')
    def preview(did: str, request: Request, workspace: str):
        _, client = context(request, workspace)
        return Response(guard(client.thumbnail, did), media_type='image/png', headers={'Cache-Control': 'no-store'})

    @r.post('/designs/{did}/import')
    def import_design(did: str, request: Request, x_tenant_id: str | None = Header(None)):
        root, client = context(request, x_tenant_id)
        return guard(client.import_design, root, x_tenant_id, did)

    @r.get('/tasks')
    def tasks(request: Request, x_tenant_id: str | None = Header(None)):
        root, client = context(request, x_tenant_id)
        paths = sorted(bridge.task_folder(root, x_tenant_id).glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        items = [read_json(p) for p in paths[:100]]
        return {'items': [i for i in items if i.get('baseUrl') == client.session.base_url]}

    @r.post('/tasks')
    def generate(body: bridge.Generate, request: Request, x_tenant_id: str | None = Header(None)):
        root, client = context(request, x_tenant_id)
        return guard(bridge.generate, root, x_tenant_id, client, body.model_dump())

    @r.get('/tasks/{rid}')
    def task(rid: str, request: Request, x_tenant_id: str | None = Header(None)):
        root, client = context(request, x_tenant_id)
        return guard(bridge.update_task, root, x_tenant_id, client, rid)

    @r.post('/tasks/{rid}/cancel')
    def cancel(rid: str, request: Request, x_tenant_id: str | None = Header(None)):
        root, client = context(request, x_tenant_id)
        return guard(bridge.update_task, root, x_tenant_id, client, rid, cancel=True)

    return r
