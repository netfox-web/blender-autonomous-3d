"""Product Digital Twin — DAM-backed, reused by stills / 360 / AR / video / catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fox3d.ids import new_id, stable_hash
from fox3d.infra import DAM
from fox3d.pngutil import write_glb_stub


class ProductDigitalTwin(BaseModel):
    twinId: str = Field(default_factory=new_id)
    tenantId: str
    sku: str
    glb: str | None = None
    fbx: str | None = None
    obj: str | None = None
    usd: str | None = None
    textures: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)  # mm
    weight: float | None = None
    boundingBox: dict[str, float] = Field(default_factory=dict)
    productMetadata: dict[str, Any] = Field(default_factory=dict)
    packagingArtwork: list[str] = Field(default_factory=list)
    animationPresets: list[str] = Field(default_factory=list)
    compatibleRecipes: list[str] = Field(default_factory=list)
    version: int = 1
    damAssetId: str | None = None
    previewAssetId: str | None = None
    previewPath: str | None = None
    contentHash: str | None = None

    def compute_hash(self) -> str:
        return stable_hash(self.model_dump(exclude={"contentHash", "damAssetId", "version"}))


class TwinStore:
    def __init__(self, dam: DAM) -> None:
        self.dam = dam
        self._items: dict[str, ProductDigitalTwin] = {}

    def create(self, twin: ProductDigitalTwin, *, glb_bytes: bytes | None = None) -> ProductDigitalTwin:
        if not twin.glb and glb_bytes is None:
            from pathlib import Path

            tmp = Path(self.dam.root) / twin.tenantId / "twins" / f"{twin.twinId}.glb"
            write_glb_stub(tmp, twin.sku)
            glb_bytes = tmp.read_bytes()
            twin.glb = str(tmp)
        if glb_bytes is not None:
            obj = self.dam.put(
                tenant_id=twin.tenantId,
                kind="digital_twin",
                name=f"{twin.sku}.glb",
                data=glb_bytes,
                metadata={"sku": twin.sku, "twinId": twin.twinId},
                asset_id=twin.twinId,
            )
            twin.damAssetId = obj.asset_id
            twin.glb = obj.path
        if not twin.boundingBox and twin.dimensions:
            twin.boundingBox = {
                "minX": 0,
                "minY": 0,
                "minZ": 0,
                "maxX": twin.dimensions.get("width", 0),
                "maxY": twin.dimensions.get("depth", 0),
                "maxZ": twin.dimensions.get("height", 0),
            }
        twin.contentHash = twin.compute_hash()
        self._items[twin.twinId] = twin
        return twin

    def get(self, twin_id: str, *, tenant_id: str) -> ProductDigitalTwin:
        twin = self._items[twin_id]
        if twin.tenantId != tenant_id:
            raise PermissionError("tenant isolation: digital twin leakage blocked")
        self.dam.get(twin.damAssetId or twin_id, tenant_id=tenant_id)
        return twin

    def list(self, *, tenant_id: str) -> list[ProductDigitalTwin]:
        return [t for t in self._items.values() if t.tenantId == tenant_id]

    def new_version(self, twin_id: str, *, tenant_id: str, **changes: Any) -> ProductDigitalTwin:
        current = self.get(twin_id, tenant_id=tenant_id)
        data = current.model_dump()
        data.update(changes)
        data["twinId"] = new_id()
        data["version"] = current.version + 1
        data["damAssetId"] = None
        nxt = ProductDigitalTwin.model_validate(data)
        return self.create(nxt)
