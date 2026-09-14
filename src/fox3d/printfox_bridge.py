"""Bounded design-service bridge; never sends a production print job.

Only the operator configures an origin. Console credentials live in expiring
memory sessions, never in job journals or imported artwork metadata.
"""
from __future__ import annotations

import io
import json
import re
import time
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit, unquote

import httpx
from filelock import FileLock
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from fox3d import print_assets as assets
from fox3d.ids import stable_hash, sha256_bytes
from fox3d.recipe_3d import atomic_json, read_json

DEFAULT_URL = 'http://100.99.216.78:8101'
COOKIE = 'fox3d_printfox_session'
PREFIX = '/api/print-workspace/printfox'
ID = r'^[A-Za-z0-9_-]{1,120}$'
JSON_LIMIT = 8 * 1024 * 1024


class BridgeError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def origin(root):
    value = read_json(Path(root) / 'printfox-connection.json').get('baseUrl', DEFAULT_URL)
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
        raise BridgeError('PrintFox 伺服器設定必須是沒有帳密與路徑的 HTTP(S) 網址')
    return value.rstrip('/')


def checked_id(value):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise BridgeError('無效的 PrintFox 編號')
    return value


@dataclass
class Session:
    tenant: str
    base_url: str
    token: str = field(repr=False)
    expires: float = 0
    catalog: dict = field(default_factory=dict)


class Sessions:
    def __init__(self):
        self.items = {}
        self.lock = RLock()

    def add(self, tenant, base_url, token):
        with self.lock:
            self.items = {k: v for k, v in self.items.items() if v.expires > time.monotonic()}
            if len(self.items) >= 32:
                raise BridgeError('連線數已滿，請稍後再試', 429)
            sid = secrets.token_urlsafe(32)
            self.items[sid] = Session(tenant, base_url, token, time.monotonic() + 3600)
            return sid

    def get(self, sid, tenant, base_url):
        with self.lock:
            s = self.items.get(sid)
            if not s or s.tenant != tenant or s.base_url != base_url or s.expires <= time.monotonic():
                raise BridgeError('請先連接 PrintFox；連線有效一小時，重啟後需重新連接', 401)
            return s

    def remove(self, sid):
        with self.lock:
            self.items.pop(sid, None)


class Client:
    def __init__(self, session, transport=None):
        self.session = session
        self.transport = transport

    def request(self, method, path, *, body=None, binary=False, limit=None):
        # Every caller constructs a known route. Never follow remote URLs/redirects.
        if not path.startswith('/') or path.startswith('//'):
            raise BridgeError('不允許的遠端路徑')
        limit = limit or (assets.MAX_BYTES if binary else JSON_LIMIT)
        try:
            with httpx.Client(base_url=self.session.base_url, headers={'X-Console-Token': self.session.token},
                              timeout=30, follow_redirects=False, trust_env=False, transport=self.transport) as c:
                with c.stream(method, path, json=body) as response:
                    if response.status_code in (401, 403):
                        raise BridgeError('PrintFox 驗證失敗，請重新輸入 Token', 401)
                    if not 200 <= response.status_code < 300:
                        raise BridgeError('PrintFox 未完成請求，請查看服務狀態', 502)
                    if response.headers.get('content-length', '').isdigit() and int(response.headers['content-length']) > limit:
                        raise BridgeError('PrintFox 回傳檔案超過上限', 413)
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > limit:
                            raise BridgeError('PrintFox 回傳檔案超過上限', 413)
        except httpx.HTTPError:
            raise BridgeError('無法確認 PrintFox 回應；請檢查連線', 502) from None
        if binary:
            return bytes(raw)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise BridgeError('PrintFox 回傳格式不符', 502) from None

    def status(self):
        r = self.request('GET', '/api/status')
        return {k: r.get(k) for k in ('workers_online', 'queue', 'designs')}

    def designs(self, q='', offset=0):
        data = self.request('GET', '/api/designs').get('designs')
        if not isinstance(data, list):
            raise BridgeError('PrintFox 圖庫格式不符', 502)
        catalog = {}
        for d in data:
            if not isinstance(d, dict) or not re.fullmatch(ID, str(d.get('id', ''))):
                continue
            meta = d.get('meta') if isinstance(d.get('meta'), dict) else {}
            catalog[d['id']] = {
                'id': d['id'], 'title': str(d.get('title') or d['id'])[:200],
                'source': str(d.get('source') or '')[:50], 'createdAt': str(d.get('created_at') or '')[:80],
                'jobId': str(meta.get('job_id') or '')[:120],
                'filename': str(meta.get('filename') or d['id'] + '.png').replace('\\', '/').split('/')[-1][:200],
                'thumb': str(d.get('thumb_url') or ''),
                'generation': {k: meta[k] for k in ('job_id', 'seed', 'engine', 'width', 'height', 'round')
                               if isinstance(meta.get(k), (str, int, float, bool))},
            }
        self.session.catalog = catalog
        items = [d for d in catalog.values() if q.casefold() in (d['title'] + ' ' + d['id']).casefold()]
        return {'total': len(items), 'items': [{k: v for k, v in d.items() if k not in ('thumb', 'filename', 'generation')}
                                             for d in items[offset:offset + 20]]}

    def design(self, did):
        did = checked_id(did)
        if did not in self.session.catalog:
            self.designs()
        if did not in self.session.catalog:
            raise BridgeError('找不到 PrintFox 圖稿', 404)
        return self.session.catalog[did]

    def thumbnail(self, did):
        d = self.design(did)
        path = unquote(d['thumb'])
        p = urlsplit(path)
        if p.scheme or p.netloc or p.query or p.fragment or not path.startswith('/thumbs/') or '\\' in path or '%' in path or '..' in path.split('/'):
            raise BridgeError('此圖稿沒有可安全讀取的縮圖', 404)
        raw = self.request('GET', path, binary=True, limit=8 * 1024 * 1024)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > assets.MAX_PIXELS:
                raise BridgeError('縮圖尺寸超過上限')
            im.thumbnail((600, 600)); out = io.BytesIO(); im.convert('RGB').save(out, format='PNG')
            return out.getvalue()

    def import_design(self, root, tenant, did):
        d = self.design(did)
        raw = self.request('GET', '/api/designs/' + checked_id(did) + '/download', binary=True)
        lineage = {'type': 'PRINTFOX_DESIGN', 'baseUrl': self.session.base_url, 'designId': did,
                   'designSource': d['source'], 'generation': d['generation'], 'originalSha256': sha256_bytes(raw),
                   'physicalDimensionsVerified': False}
        a = assets.import_asset(root, tenant, raw, d['filename'], lineage)
        # Keep every source link even when content-addressed artwork already existed.
        p = assets.workspace(root, tenant) / 'printfox' / 'imports' / (stable_hash(lineage) + '.json')
        atomic_json(p, {'assetId': a['id'], 'lineage': lineage})
        return a


class Generate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    requestId: str = Field(pattern=r'^[a-f0-9-]{36}$')
    prompt: str = Field(min_length=3, max_length=3000)
    negative: str = Field(default='', max_length=1500)
    size: Literal['sq', 'wide', 'tall', 'cabinet'] = 'wide'
    count: int = Field(default=1, ge=1, le=4)
    engine: Literal['comfyui', 'grok_imagine'] = 'comfyui'


def task_folder(root, tenant):
    p = assets.workspace(root, tenant) / 'printfox' / 'tasks'
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_path(root, tenant, rid):
    if not re.fullmatch(r'[a-f0-9-]{36}', rid):
        raise BridgeError('無效生圖請求編號')
    return task_folder(root, tenant) / (rid + '.json')


def generate(root, tenant, client, body):
    d = Generate.model_validate(body)
    if not d.prompt.strip():
        raise BridgeError('請輸入圖案描述')
    path = task_path(root, tenant, d.requestId)
    with FileLock(str(path) + '.lock', timeout=30):
        old = read_json(path)
        fingerprint = stable_hash({'baseUrl': client.session.base_url, 'request': d.model_dump()})
        if old:
            if old['fingerprint'] != fingerprint:
                raise BridgeError('此請求編號已用於不同設定', 409)
            return old  # Never replay an uncertain POST.
        params = {'styles': [{'id': 'fox3d', 'name': 'Fox3D 圖案', 'desc': d.prompt, 'negative': d.negative}],
                  'style': 'Fox3D 圖案', 'sizes': [d.size], 'per_style': d.count,
                  'mode': 'design', 'continuous': False, 'cmyk': False,
                  'engine': d.engine, 'negative_prompt': d.negative, 'fox3d_request_id': d.requestId}
        record = {'requestId': d.requestId, 'fingerprint': fingerprint, 'baseUrl': client.session.base_url,
                  'params': params, 'state': 'submission_unknown', 'remoteJobId': None,
                  'liveMachineControl': False, 'physicalPrintValidated': False}
        atomic_json(path, record)  # Crash/timeout leaves an explicit uncertain state.
        try:
            job = client.request('POST', '/api/jobs', body={'type': 'generate', 'params': params}).get('job', {})
            if not isinstance(job, dict) or job.get('type') != 'generate' or job.get('params') != params:
                raise BridgeError('生圖回應內容不符', 502)
            record['remoteJobId'] = checked_id(job.get('id'))
            record['state'] = str(job.get('status') or 'pending')[:40]
            record['progress'] = 0
        except BridgeError as exc:
            if exc.status == 401:
                record.update(state='rejected', message='驗證失敗，請重新連接後送出新請求。')
            else:
                record['message'] = '送出結果不明，請按更新狀態核對；不要重複送出相同生圖。'
        atomic_json(path, record)
        return record


def update_task(root, tenant, client, rid, *, cancel=False):
    path = task_path(root, tenant, rid)
    with FileLock(str(path) + '.lock', timeout=30):
        record = read_json(path)
        if not record or record['baseUrl'] != client.session.base_url:
            raise BridgeError('找不到此工作區的生圖請求', 404)
        if record['state'] == 'rejected':
            return record
        jid = record.get('remoteJobId')
        if not jid:
            recent = client.request('GET', '/api/jobs?limit=500').get('jobs', [])
            matches = [j for j in recent if isinstance(j, dict) and j.get('type') == 'generate'
                       and isinstance(j.get('params'), dict) and j['params'].get('fox3d_request_id') == rid]
            if len(matches) != 1:
                return record  # No inference that a missing job was never submitted.
            jid = checked_id(matches[0]['id'])
        job = client.request('GET', '/api/jobs/' + checked_id(jid)).get('job', {})
        if not isinstance(job, dict) or job.get('id') != jid or job.get('type') != 'generate' or job.get('params') != record['params']:
            raise BridgeError('遠端任務內容不符，禁止操作', 409)
        if cancel and job.get('status') in ('pending', 'claimed', 'running'):
            client.request('POST', '/api/jobs/' + jid + '/cancel')
            job = client.request('GET', '/api/jobs/' + jid).get('job', {})
        record.update(remoteJobId=jid, state=str(job.get('status') or 'unknown')[:40],
                      progress=max(0, min(100, int(job.get('progress') or 0))))
        record.pop('message', None)
        atomic_json(path, record)
        return record
