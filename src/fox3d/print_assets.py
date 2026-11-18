"""Local artwork inventory. Configured sources are read-only; originals stay local."""
from __future__ import annotations

import io
import math
import os
import re
import warnings
from pathlib import Path
from threading import RLock

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from fox3d.ids import sha256_bytes, stable_hash
from fox3d.recipe_3d import atomic_json, read_json

MAX_BYTES = 150 * 1024 * 1024
MAX_PIXELS = 40_000_000
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.pdf', '.ai'}
PDF_LOCK = RLock()


class NotFoundError(ValueError):
    """Raised when a requested asset, job, bundle, or source item does not exist."""


def workspace(root, tenant):
    if not tenant or tenant != tenant.strip() or tenant == 'system' or len(tenant) > 120:
        raise ValueError('請提供有效工作區')
    return Path(root) / 'print-workspaces' / stable_hash({'tenant': tenant})[:24]


def checked_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise NotFoundError('找不到指定資料')
    return value


def source_catalog(root):
    """The administrator supplies this local config, never an API file path."""
    config = read_json(Path(root) / 'print-source-config.json')
    return config, read_json(Path(root) / 'print-source-index.json').get('items', [])


def scan_source(root, source_root):
    source = Path(source_root).resolve(strict=True)
    items = []
    pending=[source]
    while pending:
        # scandir reuses directory metadata on SMB instead of resolving each ancestor
        # of every file. Source bytes are independently resolved before each import.
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_symlink():continue
                f=Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if not f.is_junction():pending.append(f)
                    continue
                if not entry.is_file(follow_symlinks=False) or f.suffix.lower() not in EXTENSIONS:continue
                rel = f.relative_to(source)
                sku = next((m.group() for s in reversed(rel.parts) if (m := re.search(r'\b[A-Z]{2}\d{4,8}', s))), '')
                items.append({'id': stable_hash({'path': rel.as_posix()}), 'path': rel.as_posix(),
                              'name': f.name, 'family': rel.parts[0] if len(rel.parts)>1 else '',
                              'product': rel.parts[-2] if len(rel.parts)>1 else '', 'sku': sku,
                              'kind': f.suffix.lower()[1:], 'sizeBytes': entry.stat(follow_symlinks=False).st_size})
    atomic_json(Path(root) / 'print-source-config.json', {'sourceRoot': str(source), 'mode': 'READ_ONLY'})
    atomic_json(Path(root) / 'print-source-index.json', {'items': sorted(items,key=lambda x:x['path'])})
    return len(items)


def source_bytes(root, source_id):
    config, items = source_catalog(root)
    sid = checked_id(source_id)
    item = next((i for i in items if isinstance(i, dict) and i.get('id') == sid), None)
    if not item or not config or not config.get('sourceRoot'):
        raise NotFoundError('找不到來源檔案，請重新整理來源清單')
    try:
        base = Path(config['sourceRoot']).resolve(strict=True)
    except OSError as exc:
        raise NotFoundError('找不到來源檔案，請重新整理來源清單') from exc
    candidate = (base / str(item.get('path', ''))).resolve(strict=False)
    if not candidate.is_relative_to(base):
        raise ValueError('來源檔案超出設定範圍')
    try:
        target = (base / str(item['path'])).resolve(strict=True)
    except OSError as exc:
        raise NotFoundError('找不到來源檔案，請重新整理來源清單') from exc
    if not target.is_relative_to(base) or not target.is_file() or target.suffix.lower() not in EXTENSIONS:
        raise ValueError('來源檔案超出設定範圍')
    with target.open('rb') as f:
        raw = f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        raise ValueError('原稿超過 150 MB，請先拆成個別商品')
    return raw, item


def inspect_bytes(raw):
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError('原稿為空或超過 150 MB')
    if raw.startswith(b'%PDF-'):
        try:
            r = PdfReader(io.BytesIO(raw))
            if r.is_encrypted or not 1 <= len(r.pages) <= 100:
                raise ValueError('PDF 需未加密且不超過 100 頁')
            pages=[]
            for pg in r.pages:
                media=list(map(float,pg.mediabox));trim=list(map(float,pg.trimbox))
                # /UserUnit scales PDF coordinates; avoid silent physical-size errors.
                if float(pg.get('/UserUnit',1))!=1 or pg.rotation not in (0,90,180,270):
                    raise ValueError('PDF 單位或旋轉不支援，請另存標準 PDF')
                if not (media[0]<=trim[0]<trim[2]<=media[2] and media[1]<=trim[1]<trim[3]<=media[3]):
                    raise ValueError('PDF 裁切框不在版面內')
                w,h=(media[2]-media[0])*25.4/72,(media[3]-media[1])*25.4/72
                if not 1<=min(w,h) or max(w,h)>5000:
                    raise ValueError('PDF 版面超出 1–5000 mm')
                pages.append({'mediaBoxPt':media,'trimBoxPt':trim,'rotation':pg.rotation,
                              'widthMm':w,'heightMm':h,
                              'trimWidthMm':(trim[2]-trim[0])*25.4/72,'trimHeightMm':(trim[3]-trim[1])*25.4/72})
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 原稿格式無效或已損毀') from exc
        return {'type':'PDF','pages':pages,'color':'SOURCE_PDF_PRESERVED','sizeAuthority':'PDF_BOXES_NOT_PHYSICAL_MEASUREMENT'}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('JPEG','PNG','TIFF') or getattr(im,'n_frames',1)!=1 or im.width*im.height>MAX_PIXELS:
                    raise ValueError('圖片需單頁 JPG／PNG／TIFF，且不超過 4000 萬像素')
                if im.getexif().get(274,1)!=1:
                    raise ValueError('圖片含 EXIF 旋轉，請先套用旋轉另存後匯入')
                if im.mode not in ('RGB','RGBA','CMYK','L'):
                    raise ValueError('請使用 RGB、CMYK 或灰階圖片')
                im.load()
                dpi=im.info.get('dpi')
                if dpi is not None:
                    # EXIF/TIFF resolution may contain Pillow IFDRational objects.
                    # Preserve existing JSON int/float identities for saved assets.
                    dpi=[v if type(v) in (int,float) else float(v) for v in dpi]
                    if not all(math.isfinite(v) for v in dpi):
                        raise ValueError('圖片解析度資料無效')
                return {'type':'IMAGE','pages':[{'widthPx':im.width,'heightPx':im.height}],
                        'color':im.mode,'iccEmbedded':bool(im.info.get('icc_profile')),
                        'dpi':dpi,'sizeAuthority':'REQUIRES_MM_CONFIRMATION'}
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('圖片像素超過安全上限') from exc
    except Exception as exc:
        raise ValueError('圖片原稿格式無效或已損毀') from exc


def import_asset(root, tenant, raw, name, provenance=None):
    info=inspect_bytes(raw);aid=sha256_bytes(raw)
    folder=workspace(root,tenant)/'assets'/aid
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'original.bin'
    if path.exists() and sha256_bytes(path.read_bytes())!=aid:
        raise ValueError('已存原稿雜湊不符')
    if not path.exists():
        path.write_bytes(raw)
    meta={'id':aid,'name':Path(name).name,'sizeBytes':len(raw),'info':info,
          'provenance':provenance or {'type':'USER_UPLOAD'},'truth':'USER_PROVIDED_SOURCE'}
    if not (folder/'asset.json').exists():
        atomic_json(folder/'asset.json',meta)
    return read_json(folder/'asset.json')


def asset(root,tenant,aid):
    folder=workspace(root,tenant)/'assets'/checked_id(aid)
    asset_path=folder/'asset.json'
    bin_path=folder/'original.bin'
    if not folder.is_dir() or not asset_path.is_file() or not bin_path.is_file():
        raise NotFoundError('找不到指定原稿')
    meta=read_json(asset_path)
    try:
        raw=bin_path.read_bytes()
    except OSError as exc:
        raise NotFoundError('找不到指定原稿') from exc
    if not isinstance(meta,dict) or meta.get('id')!=aid or sha256_bytes(raw)!=aid:
        raise ValueError('原稿驗證失敗，請重新匯入')
    info=meta.get('info')
    if not isinstance(info,dict) or stable_hash(info) != stable_hash(inspect_bytes(raw)):
        raise ValueError('原稿尺寸或色彩紀錄已變更，請重新匯入')
    return meta,raw


def thumbnail(root,tenant,aid,page=0):
    meta,raw=asset(root,tenant,aid)
    if not 0<=page<len(meta['info']['pages']):
        raise ValueError('找不到圖稿頁面')
    if meta['info']['type']=='PDF':
        import pypdfium2 as pdfium
        reader=PdfReader(io.BytesIO(raw));pg=reader.pages[page]
        pg.cropbox=RectangleObject(pg.mediabox)
        writer=PdfWriter();writer.add_page(pg);full=io.BytesIO();writer.write(full)
        # PDFium is not thread-safe. Isolated lock covers the document lifetime.
        with PDF_LOCK:
            doc=pdfium.PdfDocument(full.getvalue())
            try:
                pg=doc[0]
                try:
                    bitmap=pg.render(scale=1000/max(pg.get_size()))
                    try:im=bitmap.to_pil().convert('RGB').copy()
                    finally:bitmap.close()
                finally:pg.close()
            finally:doc.close()
    else:
        with Image.open(io.BytesIO(raw)) as original:
            im=original.convert('RGB');im.thumbnail((1000,1000))
    out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
