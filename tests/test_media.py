import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from fox3d.infra import _MAX_ENCODED_COMPONENT_BYTES, safe_path_component
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
                                 "enc~Li4veA", "ENC~Li4veA",
                                 pytest.param("a" * 119 + "/", id="long-slash-sku")])
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
                                 "../x", "a/a", "a/G", "a/B", "a/\\",
                                 "enc~Li4veA", "ENC~Li4veA", "enc~+612f61",
                                 pytest.param("a" * 119 + "/", id="long-slash-sku")])
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
    ("../x", "enc~+2e2e2f78"),
    ("..", "enc~+2e2e"),
    ("a/b", "enc~+612f62"),
    ("a/a", "enc~+612f61"),
    ("a/G", "enc~+612f47"),
    ("D:escape", "enc~+443a657363617065"),
    ("CON", "enc~+434f4e"),
    ("NUL.txt", "enc~+4e554c2e747874"),
    ("name:stream", "enc~+6e616d653a73747265616d"),
    ("trailing.", "enc~+747261696c696e672e"),
    ("trailing ", "enc~+747261696c696e6720"),
    ("enc~Li4veA", "enc~~Li4veA"),
    ("ENC~Li4veA", "ENC~~Li4veA"),
    ("Enc~Li4veA", "Enc~~Li4veA"),
    ("enc~", "enc~~"),
    ("enc~+612f61", "enc~~+612f61"),
    ("enc~YS9h", "enc~~YS9h"),
])
def test_safe_path_component_preserves_existing_filenames(sku, expected):
    assert safe_path_component(sku) == expected


def test_literal_encoding_prefix_does_not_match_encoded_name():
    encoded = safe_path_component("../x")
    assert encoded == "enc~+2e2e2f78"
    for literal in ("enc~Li4veA", "ENC~Li4veA", "Enc~li4vea", "enc~", "ENC~",
                    "enc~+2e2e2f78", "ENC~+2E2E2F78"):
        assert safe_path_component(literal).casefold() != encoded.casefold()


def _sku_glb_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("skus", [
    ("../x", "enc~Li4veA"),
    ("enc~Li4veA", "../x"),
    ("../x", "enc~Li4veA", "normal-sku", "a/b"),
    ("a/a", "a/G"),
    ("a/B", "a/\\"),
    ("a/a", "a/G", "enc~YS9h", "enc~+612f61"),
    pytest.param(("a" * 119 + "/", "A" * 119 + "/"), id="long-review-case-pair"),
    pytest.param(("a/a" + "bcd" * 39, "a/G" + "bcd" * 39), id="long-base64-casefold-pair"),
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
        assert glb.resolve().is_relative_to(dest.resolve())
        assert sku.encode("utf-8") in glb.read_bytes()
        exported.append((sku, glb, _sku_glb_sha256(glb)))

    paths = [glb for _, glb, _ in exported]
    names = [glb.name for glb in paths]
    assert len(set(paths)) == len(skus)
    assert len({name.casefold() for name in names}) == len(skus)
    if os.name == "nt":
        assert len({os.path.normcase(name) for name in names}) == len(skus)
        assert {glb.resolve().drive for glb in paths} == {dest.resolve().drive}
    for sku, glb, digest in exported:
        assert glb.is_file()
        assert _sku_glb_sha256(glb) == digest
        assert sku.encode("utf-8") in glb.read_bytes()
    if _directory_is_case_insensitive(dest):
        resolved = [glb.resolve() for glb in paths]
        for index, left in enumerate(resolved):
            for right in resolved[index + 1:]:
                assert not left.samefile(right)
        for sku, glb, digest in exported:
            alias = glb.with_name(glb.name.swapcase())
            assert alias.name.casefold() == glb.name.casefold()
            assert alias.samefile(glb)
            assert _sku_glb_sha256(alias) == digest
            assert sku.encode("utf-8") in alias.read_bytes()


def _legacy_base64_component(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    return f"enc~{encoded}"


def _directory_is_case_insensitive(directory: Path) -> bool:
    probe = directory / "FoxCaseProbe"
    probe.write_bytes(b"probe")
    try:
        alias = directory / "foxcaseprobe"
        return alias.exists() and alias.samefile(probe)
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)


def test_case_confusable_skus_encode_outside_legacy_base64_names():
    """``a/a`` and ``a/G`` used to share ``enc~YS9h`` after case folding."""
    pairs = (("a/a", "a/G"), ("a/B", "a/\\"))
    for left, right in pairs:
        assert _legacy_base64_component(left).casefold() == _legacy_base64_component(right).casefold()
        assert safe_path_component(left).casefold() != safe_path_component(right).casefold()
    samples = ["a/a", "a/G", "a/B", "a/\\", "../x", "..", "D:escape", "CON", "NUL.txt",
               "name:stream", "trailing.", "trailing ", "a\\b", "中/文"]
    folded = []
    for sku in samples:
        name = safe_path_component(sku)
        assert name == f"enc~+{sku.encode('utf-8').hex()}"
        assert name == name.casefold()
        assert name.casefold() != _legacy_base64_component(sku).casefold()
        assert safe_path_component(name).casefold() != name.casefold()
        folded.append(name.casefold())
    assert len(set(folded)) == len(samples)


def test_long_safe_sku_keeps_its_filename():
    sku = "a" * 119
    assert "/" not in sku
    assert safe_path_component(sku) == sku


def test_reversible_hex_stops_at_the_dam_filename_budget():
    """Hex stays while ``{uuid}_{component}.glb`` still fits in 255 bytes."""
    prefix_len = len("enc~+")
    max_payload = (_MAX_ENCODED_COMPONENT_BYTES - prefix_len) // 2
    fitting = "a" * (max_payload - 1) + "/"
    assert len(fitting.encode("utf-8")) == max_payload
    fitting_name = safe_path_component(fitting)
    assert fitting_name == "enc~+" + fitting.encode("utf-8").hex()
    assert len(fitting_name.encode("utf-8")) <= _MAX_ENCODED_COMPONENT_BYTES

    overflowing = "a" * max_payload + "/"
    overflowing_name = safe_path_component(overflowing)
    assert overflowing_name == "enc~=" + hashlib.sha256(overflowing.encode("utf-8")).hexdigest()
    assert len(overflowing_name.encode("utf-8")) <= _MAX_ENCODED_COMPONENT_BYTES
    assert len("enc~=") + 64 <= _MAX_ENCODED_COMPONENT_BYTES

    asset_id = "3" * 36
    for component in (fitting_name, overflowing_name):
        filename = f"{asset_id}_{component}.glb"
        assert len(filename.encode("utf-8")) <= 255


def test_review_long_sku_digest_fits_where_hex_does_not():
    """119 ``a``s plus ``/`` used to encode to 201 bytes and now must stay ≤ 255."""
    sku = "a" * 119 + "/"
    asset_id = "0123456789abcdef" * 2
    assert len(asset_id) == 32
    encoded = safe_path_component(sku)
    assert encoded == "enc~=" + hashlib.sha256(sku.encode("utf-8")).hexdigest()
    assert encoded == encoded.casefold()
    assert encoded.casefold() != _legacy_base64_component(sku).casefold()
    filename = f"{asset_id}_{encoded}.glb"
    legacy = f"{asset_id}_{_legacy_base64_component(sku)}.glb"
    hex_name = f"{asset_id}_enc~+{sku.encode('utf-8').hex()}.glb"
    assert len(legacy.encode("utf-8")) == 201
    assert len(hex_name.encode("utf-8")) > 255
    assert len(filename.encode("utf-8")) <= 255
    uuid_name = f"{'3' * 36}_{encoded}.glb"
    assert len(uuid_name.encode("utf-8")) <= 255
    assert len(f"{'3' * 36}_enc~+{sku.encode('utf-8').hex()}.glb".encode("utf-8")) > 255
    escaped = safe_path_component(encoded)
    assert escaped == encoded[:len("enc~")] + "~" + encoded[len("enc~"):]
    assert escaped.casefold() != encoded.casefold()
    upper = "ENC~=" + encoded[len("enc~="):]
    assert safe_path_component(upper) == "ENC~~=" + encoded[len("enc~="):]
    assert safe_path_component(upper).casefold() != encoded.casefold()


def test_long_base64_casefold_pair_stays_distinct():
    suffix = "bcd" * 39
    left, right = "a/a" + suffix, "a/G" + suffix
    assert len(left.encode("utf-8")) == len(right.encode("utf-8")) == 120
    assert _legacy_base64_component(left).casefold() == _legacy_base64_component(right).casefold()
    assert safe_path_component(left).startswith("enc~=")
    assert safe_path_component(right).startswith("enc~=")
    assert safe_path_component(left).casefold() != safe_path_component(right).casefold()


def test_long_utf8_sku_is_bounded_by_bytes_not_characters():
    sku = "測" * 40 + "/"
    assert len(sku) < _MAX_ENCODED_COMPONENT_BYTES
    assert len(sku.encode("utf-8")) > (_MAX_ENCODED_COMPONENT_BYTES - len("enc~+")) // 2
    encoded = safe_path_component(sku)
    assert encoded == "enc~=" + hashlib.sha256(sku.encode("utf-8")).hexdigest()
    assert len(f"{'3' * 36}_{encoded}.glb".encode("utf-8")) <= 255


def test_export_write_stays_on_destination_volume(tmp_path):
    dest = tmp_path / "destination"
    dest.mkdir()
    skus = ["a/a", "a/G", "D:escape", "C:escape", "D:/escape", r"\\server\share",
            r"\\?\C:\escape", "../x", "a" * 119 + "/"]
    for sku in skus:
        result = ARExporter().export({"sku": sku}, dest)
        glb = Path(result["glb"])
        resolved = glb.resolve()
        assert resolved.is_relative_to(dest.resolve())
        assert resolved.parent == dest.resolve()
        assert len(glb.name.encode("utf-8")) <= 255
        assert sku.encode("utf-8") in glb.read_bytes()
        if os.name == "nt":
            assert resolved.drive == dest.resolve().drive
            assert resolved.anchor == dest.resolve().anchor
    for drive in (PureWindowsPath("C:/exports"), PureWindowsPath("D:/other")):
        for sku in skus:
            filename = f"{safe_path_component(sku)}.glb"
            path = drive / filename
            assert path.parent == drive
            assert path.drive == drive.drive
            assert ".." not in path.parts
            assert not PureWindowsPath(filename).drive
            assert not PureWindowsPath(filename).root


def _free_windows_drive_letter() -> str | None:
    for letter in "ZYXWVUTSRQPONMLKJIHGFED":
        if not Path(f"{letter}:\\").exists():
            return letter
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="subst creates a second Windows volume")
def test_export_on_subst_drive_does_not_cross_volumes(tmp_path):
    letter = _free_windows_drive_letter()
    if letter is None:
        pytest.skip("no free drive letter")
    volume = tmp_path / "subst-volume"
    volume.mkdir()
    created = subprocess.run(["subst", f"{letter}:", str(volume)], capture_output=True, text=True)
    if created.returncode != 0:
        pytest.skip(created.stderr.strip() or created.stdout.strip() or "subst failed")
    try:
        primary = tmp_path / "primary"
        primary.mkdir()
        other = Path(f"{letter}:/") / "exports"
        other.mkdir()
        long_left = "a" * 119 + "/"
        long_right = "A" * 119 + "/"
        skus = ("a/a", "a/G", "D:escape", "C:escape", r"\\server\share", long_left, long_right)
        primary_bytes: dict[str, bytes] = {}
        for sku in skus:
            # Compare drives before resolve: resolve() expands a subst drive
            # back to the host path, which would hide the volume boundary.
            raw = Path(ARExporter().export({"sku": sku}, primary)["glb"])
            assert raw.parent == primary
            assert raw.drive == primary.drive
            assert raw.drive != other.drive
            assert not PureWindowsPath(raw.name).drive
            assert len(raw.name.encode("utf-8")) <= 255
            assert raw.resolve().is_relative_to(primary.resolve())
            primary_bytes[raw.name] = raw.read_bytes()
        assert not any(other.rglob("*.glb"))
        other_bytes: dict[str, bytes] = {}
        for sku in skus:
            raw = Path(ARExporter().export({"sku": sku}, other)["glb"])
            assert raw.parent == other
            assert raw.drive == other.drive
            assert raw.drive != primary.drive
            assert not PureWindowsPath(raw.name).drive
            assert len(raw.name.encode("utf-8")) <= 255
            assert raw.resolve().is_relative_to(other.resolve())
            other_bytes[sku] = raw.read_bytes()
            assert sku.encode("utf-8") in other_bytes[sku]
        assert other_bytes["a/a"] != other_bytes["a/G"]
        assert other_bytes[long_left] != other_bytes[long_right]
        assert safe_path_component(long_left).casefold() != safe_path_component(long_right).casefold()
        for name, data in primary_bytes.items():
            assert (primary / name).read_bytes() == data
        left = Path(ARExporter().export({"sku": "a/a"}, other)["glb"])
        right = Path(ARExporter().export({"sku": "a/G"}, other)["glb"])
        assert not left.resolve().samefile(right.resolve())
        assert b"a/a" in left.read_bytes() and b"a/G" in right.read_bytes()
    finally:
        subprocess.run(["subst", f"{letter}:", "/d"], capture_output=True, text=True)


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
