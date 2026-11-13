from io import BytesIO

import pytest
from PIL import Image

from fox3d.pngutil import color_from_hash, encode_png, write_exr_stub, write_solid_png, write_webp_stub


def test_encode_png_decodes_pixels():
    rgb = bytes([255, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 255])
    with Image.open(BytesIO(encode_png(2, 2, rgb))) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (2, 2)
        assert image.tobytes() == rgb


def test_encode_png_rejects_incorrect_buffer_size():
    with pytest.raises(ValueError, match="rgb buffer size mismatch"):
        encode_png(2, 2, b"too short")


@pytest.mark.parametrize(("seed", "expected"), [("123456abcdef", (18, 52, 86)), ("", (51, 102, 153)),
                                               ("ffffff", (255, 255, 255))])
def test_color_from_hash(seed, expected):
    result = color_from_hash(seed)
    assert result == color_from_hash(seed) == expected
    assert all(0 <= value <= 255 for value in result)


def test_write_solid_png(tmp_path):
    path = tmp_path / "nested" / "solid.png"
    write_solid_png(path, "123456", width=3, height=2)
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (3, 2)
        assert image.mode == "RGB"
        assert image.tobytes() == bytes([18, 52, 86]) * 6


def test_write_exr_stub(tmp_path):
    path = tmp_path / "nested" / "image.exr"
    write_exr_stub(path, "abc")
    assert path.read_bytes() == b"\x76\x2f\x31\x01abc" + b"\x00" * 61
    write_exr_stub(path, "x" * 65)
    assert path.read_bytes() == b"\x76\x2f\x31\x01" + b"x" * 64


def test_write_webp_stub(tmp_path):
    path = tmp_path / "nested" / "image.webp"
    write_webp_stub(path)
    assert path.read_bytes() == (
        b"RIFF$\x00\x00\x00WEBPVP8 \x18\x00\x00\x00"
        b"\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x01\x40"
        b"\x26\x25\xa0\x02\xd7\x01\x80\x00\x00"
    )
