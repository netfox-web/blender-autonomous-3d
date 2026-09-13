"""Durable, tenant-scoped editing of supplier-reference drafts.

The checked-in supplier catalog remains immutable. Drafts never become
Engineering or render-ready by editing fields or importing a JSON file.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator

from fox3d.catalog_recipes import FAMILIES, StrictRecord, load_library
from fox3d.ids import sha256_bytes, stable_hash

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "data/recipe_library/sonaqueen/catalog.json"
CORE_FIELDS = ("widthMm", "depthMm", "heightMm", "material", "doorCount", "rowCount", "compartmentCount")
FIELD_LABELS = {
    "widthMm": "寬度", "depthMm": "深度", "heightMm": "高度", "material": "主要材質",
    "doorCount": "門片數", "rowCount": "上下行數", "compartmentCount": "格位數", "handles": "有把手",
    "panelThicknessMm": "板件厚度", "sidePanelThicknessMm": "側板厚度", "backThicknessMm": "背板厚度",
    "doorThicknessMm": "門板厚度", "doorGapsMm": "門片間隙", "fixedPanelThicknessMm": "固定板厚度",
    "panelJoinery": "板件接合方式", "rowDividerCoordinates": "各行隔板座標",
    "hingeSpecification": "鉸鏈規格與位置", "trackSpecification": "滑軌規格", "slideTravelMm": "滑門行程",
    "labelledOpeningHeightMm": "圖示開口高度", "labelledNarrowOpeningWidthMm": "圖示窄格內寬",
    "labelledWideOpeningWidthMm": "圖示寬格內寬", "labelledInnerWidthMm": "圖示內寬",
    "labelledInnerHeightMm": "圖示內高", "labelledInnerDepthMm": "圖示內深",
}


def field_unit(key: str) -> str:
    return "mm" if key.endswith("Mm") else "count" if key.endswith("Count") else "boolean" if key == "handles" else "text"


class DraftValue(StrictRecord):
    value: str | int | float | bool | None = None
    evidence: str = Field(default="", max_length=2000)


class ProductDraft(StrictRecord):
    sku: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    family: Literal["STAGGERED_OPEN_CUBBY", "STACKED_HINGED_CABINET", "ROW_SLIDING_CABINET"]
    pageUrl: str = Field(default="", max_length=2000)
    values: dict[str, DraftValue] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def check_values(self) -> ProductDraft:
        if not self.sku.strip() or self.sku != self.sku.strip() or any(c in self.sku for c in "/\\\x00"):
            raise ValueError("商品編號不可空白或包含斜線")
        if not self.name.strip():
            raise ValueError("請填寫商品名稱")
        if self.pageUrl:
            url = urlparse(self.pageUrl)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("商品來源須為 HTTPS 網址")
        for key, entry in self.values.items():
            if key not in FIELD_LABELS:
                raise ValueError(f"不支援的欄位：{key}")
            value = entry.value
            if value is None:
                continue
            unit = field_unit(key)
            if unit in {"mm", "count"}:
                if type(value) not in {int, float} or not math.isfinite(value):
                    raise ValueError(f"{FIELD_LABELS[key]}須填有限數值")
                if value < 0 or (key != "doorCount" and value == 0):
                    raise ValueError(f"{FIELD_LABELS[key]}須大於零（門片數可為零）")
                if unit == "count" and type(value) is not int:
                    raise ValueError(f"{FIELD_LABELS[key]}須填整數")
            elif unit == "boolean" and type(value) is not bool:
                raise ValueError("把手欄位須為是或否")
            elif unit == "text" and (not isinstance(value, str) or len(value) > 4000):
                raise ValueError(f"{FIELD_LABELS[key]}須填文字，最多 4000 字")
        return self


class SaveDraft(StrictRecord):
    expectedRevision: int = Field(ge=0)
    draft: ProductDraft


class DraftConflict(ValueError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class RecipeWorkbench:
    def __init__(self, root: Path, catalog: Path = DEFAULT_CATALOG):
        self.root = root / "recipe-workbench"
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = catalog
        self.db = self.root / "drafts.sqlite3"
        with self.connection() as con:
            con.execute("CREATE TABLE IF NOT EXISTS drafts (tenant TEXT, sku TEXT, revision INTEGER, payload TEXT, updated TEXT, PRIMARY KEY(tenant,sku))")
            con.execute("CREATE TABLE IF NOT EXISTS revisions (tenant TEXT, sku TEXT, revision INTEGER, payload TEXT, updated TEXT, PRIMARY KEY(tenant,sku,revision))")
            con.execute("CREATE TABLE IF NOT EXISTS images (tenant TEXT, sku TEXT, digest TEXT, mime TEXT, name TEXT, PRIMARY KEY(tenant,sku,digest))")

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def seeds(self):
        return {p.sku: p for p in load_library(self.catalog).products}

    @staticmethod
    def seed_draft(seed) -> ProductDraft:
        return ProductDraft(sku=seed.sku, name=seed.name, family=seed.family, pageUrl=seed.pageUrl,
                            values={k: DraftValue(value=f.value, evidence=f.observation) for k, f in seed.facts.items()},
                            notes="\n".join(seed.notes))

    def _read(self, con, tid, sku):
        return con.execute("SELECT * FROM drafts WHERE tenant=? AND sku=?", (tid, sku)).fetchone()

    def _record(self, tid, sku, seeds, row=None):
        seed = seeds.get(sku)
        if row is None and seed is None:
            raise KeyError("找不到商品")
        draft = ProductDraft.model_validate(json.loads(row["payload"])) if row else self.seed_draft(seed)
        validation = self.validate(draft, seed)
        sources = [s.model_dump() for s in seed.sources] if seed else []
        with self.connection() as con:
            uploads = [dict(r) for r in con.execute("SELECT digest,mime,name FROM images WHERE tenant=? AND sku=?", (tid, sku))]
        image_sources = [s for s in sources if s["mediaType"] == "image/jpeg"]
        preview = next((s["sourceId"] for s in image_sources if "-detail-" not in s["path"]), image_sources[0]["sourceId"] if image_sources else None)
        return {"draft": draft.model_dump(), "revision": row["revision"] if row else 0,
                "updatedAt": row["updated"] if row else None, "status": "DRAFT" if row else "SUPPLIER_REFERENCE",
                "validation": validation, "sources": sources, "uploads": uploads, "previewSourceId": preview,
                "originalReference": seed.model_dump() if seed else None,
                "renderReady": False, "engineeringReady": False, "productionReady": False}

    def list(self, tid):
        seeds = self.seeds()
        with self.connection() as con:
            rows = {r["sku"]: r for r in con.execute("SELECT * FROM drafts WHERE tenant=?", (tid,))}
        return [self._record(tid, sku, seeds, rows.get(sku)) for sku in sorted(set(seeds) | set(rows))]

    def get(self, tid, sku):
        seeds = self.seeds()
        with self.connection() as con:
            row = self._read(con, tid, sku)
        return self._record(tid, sku, seeds, row)

    @staticmethod
    def validate(draft, seed):
        def present(key):
            entry = draft.values.get(key)
            return entry is not None and entry.value is not None and entry.value != ""
        required = list(CORE_FIELDS) + FAMILIES[draft.family]["missing"]
        missing = [k for k in required if not present(k)]
        unreferenced = [k for k, v in draft.values.items() if present(k) and not v.evidence.strip()]
        issues = []
        values = {k: v.value for k, v in draft.values.items()}
        doors, rows, cells = [values.get(k) for k in ("doorCount", "rowCount", "compartmentCount")]
        if draft.family == "STAGGERED_OPEN_CUBBY" and doors not in {None, 0}:
            issues.append("開放格櫃的門片數應為 0")
        if draft.family == "STACKED_HINGED_CABINET" and None not in (doors, rows, cells) and not doors == rows == cells:
            issues.append("上下門櫃每行應有一片門與一格，請核對數量")
        if draft.family == "ROW_SLIDING_CABINET" and None not in (doors, rows, cells) and not (doors == rows and cells == rows * 2):
            issues.append("此滑門母配方每行一片門、兩格，請核對數量")
        changed = []
        if seed:
            original = RecipeWorkbench.seed_draft(seed)
            changed = [k for k, v in draft.values.items() if k not in original.values or v != original.values[k]]
            changed += [k for k in original.values if k not in draft.values]
        return {"sourceIntegrityVerified": seed is not None, "missingFields": missing,
                "unreferencedFields": unreferenced, "issues": issues, "changedFields": sorted(set(changed)),
                "dataComplete": not (missing or unreferenced or issues), "renderReady": False,
                "nextStep": "補齊資料後仍須驗證幾何與機構，才可建立商品模型。"}

    def save(self, tid, request: SaveDraft, *, create=False):
        seeds = self.seeds()
        draft = request.draft
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            old = self._read(con, tid, draft.sku)
            if create and (old or draft.sku in seeds):
                raise DraftConflict("商品編號已存在，請從商品列表開啟編輯")
            if not create and old is None and draft.sku not in seeds:
                raise KeyError("找不到商品")
            actual = old["revision"] if old else 0
            if actual != request.expectedRevision:
                raise DraftConflict("商品已被其他視窗更新，請重新載入後再儲存")
            body = draft.model_dump_json()
            rev, now = actual + 1, timestamp()
            con.execute("INSERT OR REPLACE INTO drafts VALUES (?,?,?,?,?)", (tid, draft.sku, rev, body, now))
            con.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (tid, draft.sku, rev, body, now))
        return self.get(tid, draft.sku)

    def export(self, tid, sku=None):
        records = [self.get(tid, sku)] if sku else self.list(tid)
        bundle = {"format": "fox3d.recipe-workbench.v1", "tenantId": tid, "exportedAt": timestamp(),
                  "scope": "PRODUCT_REFERENCE_DRAFT", "products": records,
                  "engineeringReady": False, "renderReady": False, "productionReady": False}
        bundle["contentHash"] = stable_hash(bundle)
        return bundle

    def import_drafts(self, tid, payload):
        if not isinstance(payload, dict) or payload.get("format") != "fox3d.recipe-workbench.v1":
            raise ValueError("請選擇由本後台匯出的 Recipe JSON")
        rows = payload.get("products")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("每次匯入須為 1 至 100 款商品")
        if any(not isinstance(r, dict) or not isinstance(r.get("draft"), dict) for r in rows):
            raise ValueError("匯入檔缺少商品草稿資料")
        drafts = [ProductDraft.model_validate(r["draft"]) for r in rows]
        if len({d.sku for d in drafts}) != len(drafts):
            raise DraftConflict("匯入檔中有重複的商品編號")
        self.seeds()  # refuse a corrupted checked-in reference catalog
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            if any(self._read(con, tid, d.sku) for d in drafts):
                raise DraftConflict("部分商品已有草稿；匯入只新增，不覆寫現有草稿")
            for draft in drafts:
                body, now = draft.model_dump_json(), timestamp()
                con.execute("INSERT INTO drafts VALUES (?,?,?,?,?)", (tid, draft.sku, 1, body, now))
                con.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (tid, draft.sku, 1, body, now))
        return [self.get(tid, d.sku) for d in drafts]

    def add_image(self, tid, sku, data, name):
        self.get(tid, sku)
        if not data or len(data) > 8 * 1024 * 1024:
            raise ValueError("圖片大小須為 1 byte 至 8 MB")
        mime = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9") else None
        if mime is None:
            raise ValueError("只接受 PNG 或 JPEG 商品圖片")
        digest = sha256_bytes(data)
        folder = self.root / "images" / stable_hash(tid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / digest
        if not path.exists():
            path.write_bytes(data)
        with self.connection() as con:
            con.execute("INSERT OR IGNORE INTO images VALUES (?,?,?,?,?)", (tid, sku, digest, mime, name[:240]))
        return {"digest": digest, "mime": mime, "name": name[:240]}

    def image(self, tid, sku, digest):
        with self.connection() as con:
            row = con.execute("SELECT * FROM images WHERE tenant=? AND sku=? AND digest=?", (tid, sku, digest)).fetchone()
        if row is None:
            raise KeyError("找不到圖片")
        path = self.root / "images" / stable_hash(tid) / row["digest"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != row["digest"]:
            raise ValueError("圖片檔案遺失或已變動")
        return path, row["mime"]
