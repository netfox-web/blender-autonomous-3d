import hashlib
import json
from pathlib import Path, PureWindowsPath

import pytest

from fox3d.infra import safe_path_component
from fox3d.media import (
    ARExporter,
    AssemblyAnimator,
    BlenderToVideo,
    Product360Engine,
    RetailEngine,
    SyntheticFactory,
)
from fox3d.pngutil import is_glb, is_png


@pytest.mark.parametrize("frames", [36, 72, 120])
def test_render_plan_supported_frames(frames):
    plan = Product360Engine().render_plan({"twinId": "twin"}, frames=frames)
    assert plan["frames"] == frames
    assert plan["twinId"] == "twin"
    assert len(plan["angles"]) == frames
    assert plan["angles"] == [round(i * 360 / frames, 4) for i in range(frames)]
    assert all(b - a == pytest.approx(360 / frames, abs=0.0001)
               for a, b in zip(plan["angles"], plan["angles"][1:]))


@pytest.mark.parametrize("frames", [0, 1, 37, -1])
def test_render_plan_invalid_frames_fall_back(frames):
    plan = Product360Engine().render_plan({}, frames=frames)
    assert plan["frames"] == 36
    assert plan["angles"] == list(range(0, 360, 10))


@pytest.mark.parametrize("frames,expected", [(36, 36), (72, 72), (120, 120), (5, 36)])
def test_render_mock_writes_frames(tmp_path, frames, expected):
    result = Product360Engine().render_mock(tmp_path, {"twinId": "twin"}, frames=frames)
    assert result["frames"] == expected
    assert result["truthLabel"] == "MOCK"
    assert len(result["images"]) == len(set(result["images"])) == expected
    assert result["viewerAssets"] == result["images"]
    assert all(is_png(path) for path in result["images"])
    assert Path(result["mp4"]).is_file()


@pytest.mark.parametrize("sku", ["../x", "a/b", "normal-sku", "..", "a\\b",
                                 "D:escape", "C:escape", "CON", "NUL.txt",
                                 "name:stream", "name?", "trailing.", "trailing ",
                                 "enc~Li4veA", "ENC~Li4veA"])
def test_ar_export_keeps_sku_filename_inside_destination(tmp_path, sku):
    dest = tmp_path / "destination"
    dest.mkdir()
    result = ARExporter().export({"sku": sku}, dest)
    glb = Path(result["glb"])
    assert glb == dest / f"{safe_path_component(sku)}.glb"
    assert glb.resolve().parent == dest.resolve()
    assert is_glb(glb)
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_file()} == {
        glb.relative_to(tmp_path), *(Path(lod["path"]).relative_to(tmp_path) for lod in result["lod"])
    }
    assert all(is_glb(lod["path"]) for lod in result["lod"])


@pytest.mark.parametrize("sku", ["D:escape", "C:escape", "D:/escape", r"\\server\share",
                                 r"\\?\C:\escape", "name:stream", "CON", "LPT¹.txt",
                                 "../x", "enc~Li4veA", "ENC~Li4veA"])
@pytest.mark.parametrize("dest", [PureWindowsPath("C:/exports"), PureWindowsPath("D:/other")])
def test_sku_filename_is_relative_under_windows_semantics(sku, dest):
    filename = f"{safe_path_component(sku)}.glb"
    path = dest / filename
    assert path.parent == dest
    assert path.drive == dest.drive
    assert ".." not in path.parts
    assert not PureWindowsPath(filename).drive
    assert not PureWindowsPath(filename).root


@pytest.mark.parametrize("sku,expected", [
    ("normal-sku", "normal-sku"),
    ("product", "product"),
    ("../x", "enc~Li4veA"),
    ("..", "enc~Li4"),
    ("a/b", "enc~YS9i"),
    ("D:escape", "enc~RDplc2NhcGU"),
    ("CON", "enc~Q09O"),
    ("NUL.txt", "enc~TlVMLnR4dA"),
    ("name:stream", "enc~bmFtZTpzdHJlYW0"),
    ("trailing.", "enc~dHJhaWxpbmcu"),
    ("trailing ", "enc~dHJhaWxpbmcg"),
    ("enc~Li4veA", "enc~~Li4veA"),
    ("ENC~Li4veA", "ENC~~Li4veA"),
    ("Enc~Li4veA", "Enc~~Li4veA"),
    ("enc~", "enc~~"),
])
def test_safe_path_component_preserves_existing_filenames(sku, expected):
    assert safe_path_component(sku) == expected


def test_literal_encoding_prefix_does_not_match_encoded_name():
    encoded = safe_path_component("../x")
    assert encoded == "enc~Li4veA"
    for literal in ("enc~Li4veA", "ENC~Li4veA", "Enc~li4vea", "enc~", "ENC~"):
        assert safe_path_component(literal).casefold() != encoded.casefold()


def _sku_glb_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("skus", [
    ("../x", "enc~Li4veA"),
    ("enc~Li4veA", "../x"),
    ("../x", "enc~Li4veA", "normal-sku", "a/b"),
])
def test_distinct_skus_keep_their_own_glb_in_one_directory(tmp_path, skus):
    dest = tmp_path / "destination"
    dest.mkdir()
    exported = []
    for sku in skus:
        result = ARExporter().export({"sku": sku}, dest)
        glb = Path(result["glb"])
        assert glb == dest / f"{safe_path_component(sku)}.glb"
        assert glb.resolve().parent == dest.resolve()
        assert sku.encode("utf-8") in glb.read_bytes()
        exported.append((sku, glb, _sku_glb_sha256(glb)))

    paths = [glb for _, glb, _ in exported]
    assert len(set(paths)) == len(skus)
    for sku, glb, digest in exported:
        assert glb.is_file()
        assert _sku_glb_sha256(glb) == digest
        assert sku.encode("utf-8") in glb.read_bytes()


def test_ar_export_defaults_missing_sku(tmp_path):
    result = ARExporter().export({}, tmp_path)
    assert Path(result["glb"]) == tmp_path / "product.glb"


@pytest.mark.parametrize("frames", [0, 1, 3])
def test_synthetic_generate_files_and_manifest(tmp_path, frames):
    result = SyntheticFactory().generate(tmp_path, job_id="job", twin_id="twin", frames=frames)
    assert set(result["files"]) == {"rgb", "mask", "depth", "normal", "seg"}
    for paths in result["files"].values():
        assert len(paths) == len(set(paths)) == frames
        assert all(is_png(path) for path in paths)
    assert len(result["boundingBoxes"]) == len(result["cameraPoses"]) == frames
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == result


def test_assembly_reverses_explode_order():
    result = AssemblyAnimator().from_component_graph({"components": [
        {"partName": "base"}, {"partName": "bolt"}, {"partName": "cover"}
    ]})
    assert [part["part"] for part in result["explode"]] == ["base", "bolt", "cover"]
    assert result["assembly"] == list(reversed(result["explode"]))
    assert result["disassembly"] == result["explode"]


@pytest.mark.parametrize("objects", [[], [{"type": "camera"}], [{"name": "Product"}]])
def test_keyframes_tolerates_missing_camera_or_product(objects):
    result = BlenderToVideo().keyframes({"objects": objects})
    assert len(result["keyframes"]) == 3
    assert all(frame["camera"] == next((o for o in objects if o.get("type") == "camera"), {})
               and frame["productLocation"] is None for frame in result["keyframes"])


@pytest.mark.parametrize("kind", ["unknown", "", None])
def test_retail_unknown_kind_defaults_to_store(kind):
    result = RetailEngine().propose(space={"kind": kind}, brand="brand", skus=[], count=1)
    assert result["kind"] == "STORE"
