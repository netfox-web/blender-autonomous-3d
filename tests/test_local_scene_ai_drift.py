"""Composition guard: product bbox pinning for FLUX 3 layout boxes, template-matching drift detection, auto retry."""
from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from fox3d.fleet_image_client import FleetImageClient
from fox3d.local_scene_ai import drift_score, product_bbox_1000, product_layout_box, run_local_scene_variants

SIZE = 160
BOX = (60, 50, 120, 130)  # x0, y0, x1, y1 of the "cabinet"


def _scene(shift: int = 0, scale: float = 1.0) -> Image.Image:
    """Grey room with a textured floor line and a dark 'cabinet' rectangle (optionally shifted / scaled)."""
    img = Image.new("RGB", (SIZE, SIZE), (200, 190, 175))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 125, SIZE, SIZE), fill=(150, 110, 70))
    for x in range(0, SIZE, 12):
        d.line((x, 125, x, SIZE), fill=(120, 85, 50))
    x0, y0, x1, y1 = BOX
    w, h = (x1 - x0) * scale, (y1 - y0) * scale
    cx, cy = (x0 + x1) / 2 + shift, (y0 + y1) / 2
    bx0, by0, bx1, by1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.rectangle((bx0, by0, bx1, by1), fill=(60, 45, 30), outline=(240, 240, 240), width=2)
    d.line((cx, by0, cx, by1), fill=(240, 240, 240), width=2)
    d.line((bx0, cy, bx1, cy), fill=(240, 240, 240), width=2)
    return img


def _cutout() -> Image.Image:
    cut = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(cut)
    d.rectangle(BOX, fill=(60, 45, 30, 255))
    return cut


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_product_bbox_and_layout_box():
    bbox = product_bbox_1000(_cutout())
    # ImageDraw rectangles are inclusive: rows 50..130 / cols 60..120
    assert bbox == [int(50 / SIZE * 1000), int(60 / SIZE * 1000), int(131 / SIZE * 1000), int(121 / SIZE * 1000)]
    box = product_layout_box(_cutout(), "2-column cube cabinet")
    assert box and box["id"] == "product" and box["bbox"] == bbox and "2-column cube cabinet" in box["desc"]
    assert product_bbox_1000(Image.new("RGBA", (10, 10), (0, 0, 0, 0))) is None


def test_drift_score_detects_shifted_product():
    ref, cut = _scene(), _cutout()
    same = drift_score(ref, _scene(), cut)
    assert same and same["drift"] is False and same["outside"] < 0.04 and abs(same["dx"]) < 0.02
    shifted = drift_score(ref, _scene(shift=14), cut)  # ~9% of the image to the right, like the bedroom ghost
    assert shifted and shifted["drift"] is True and shifted["dx"] >= 0.05 and shifted["outside"] >= 0.1
    bigger = drift_score(ref, _scene(scale=1.18), cut)
    assert bigger and bigger["drift"] is True
    flat = drift_score(Image.new("RGB", (64, 64), (128, 128, 128)), Image.new("RGB", (64, 64), (128, 128, 128)), Image.new("RGBA", (64, 64), (0, 0, 0, 0)))
    assert flat is None


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DriftingFleet:
    """First task per variant returns the shifted image, the retry returns the aligned one."""

    def __init__(self):
        self.submitted: list[dict] = []
        self.tasks: dict[str, dict] = {}

    def opener(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        if url.endswith("/api/fleet/tasks") and method == "POST":
            body = json.loads(req.data.decode("utf-8"))
            self.submitted.append(body["inputPayload"])
            tid = f"t{len(self.submitted)}"
            self.tasks[tid] = {"id": tid, "status": "success", "nodeHostname": "5090-3", "outputPayload": {"data": {"image": {"url": f"http://fleet.test/api/fleet/tasks/{tid}/artifacts/0"}, "caption": f"cap {tid}"}}}
            return _Resp({"task": self.tasks[tid]})
        if url.endswith("/artifacts/0"):
            tid = url.split("/tasks/")[1].split("/")[0]
            n = int(tid[1:])
            return _Resp(_png(_scene(shift=14) if n == 1 else _scene()))
        if "/api/fleet/tasks/" in url:
            tid = url.rsplit("/", 1)[-1]
            return _Resp({"task": self.tasks[tid]})
        raise AssertionError(f"unexpected {method} {url}")


def test_runner_pins_product_and_retries_once_on_drift(tmp_path: Path):
    fleet = DriftingFleet()
    client = FleetImageClient(base_url="http://fleet.test", token="tok", _opener=fleet.opener)
    (tmp_path / "beauty.png").write_bytes(_png(_scene()))
    (tmp_path / "product_cutout.png").write_bytes(_png(_cutout()))
    records = run_local_scene_variants(
        client,
        item_dir=tmp_path,
        reference_url="http://me/ref.png",
        cutout_path=tmp_path / "product_cutout.png",
        reference_path=tmp_path / "beauty.png",
        product_description="cube cabinet",
        prompt="photo",
        variants=1,
        seed=5,
        sleep=lambda s: None,
    )
    rec = records[0]
    assert rec["state"] == "succeeded"
    assert rec["pinned"] is True
    assert rec["retries"] == 1 and rec["drift"] is False, rec
    assert rec["seed"] == 1005
    assert rec["caption"] == "cap t2"
    assert len(fleet.submitted) == 2
    for payload in fleet.submitted:
        assert payload["boxes"][0]["id"] == "product" and "cube cabinet" in payload["boxes"][0]["desc"]
        assert payload["boxes"][0]["bbox"] == product_bbox_1000(_cutout())
    manifest = json.loads((tmp_path / "ai_local.json").read_text(encoding="utf-8"))
    assert manifest["boxes"][0]["bbox"] == product_bbox_1000(_cutout())
    assert manifest["variants"][0]["driftDetail"]["drift"] is False
    assert (tmp_path / "ai_local_01.png").exists() and (tmp_path / "ai_local_01_raw.png").exists()


def test_runner_can_skip_pinning(tmp_path: Path):
    fleet = DriftingFleet()
    client = FleetImageClient(base_url="http://fleet.test", token="tok", _opener=fleet.opener)
    (tmp_path / "product_cutout.png").write_bytes(_png(_cutout()))
    records = run_local_scene_variants(client, item_dir=tmp_path, reference_url="http://me/ref.png", cutout_path=tmp_path / "product_cutout.png", prompt="p", variants=1, pin_product=False, sleep=lambda s: None)
    assert records[0]["pinned"] is False and "boxes" not in fleet.submitted[0]
    assert records[0]["retries"] == 0  # no reference → no drift scoring
