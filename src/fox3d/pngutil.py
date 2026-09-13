"""Minimal PNG / EXR / GLB writers so tests and mock renders need no Pillow/bpy."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# Tiny 1x1 lossy WebP (VP8) — valid RIFF container.
MINIMAL_WEBP = (
    b"RIFF$\x00\x00\x00WEBPVP8 \x18\x00\x00\x00"
    b"\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x01\x40"
    b"\x26\x25\xa0\x02\xd7\x01\x80\x00\x00"
)

# OpenEXR magic.
EXR_MAGIC = b"\x76\x2f\x31\x01"


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    if len(rgb) != width * height * 3:
        raise ValueError("rgb buffer size mismatch")

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def color_from_hash(seed: str) -> tuple[int, int, int]:
    h = int(seed[:6], 16) if seed[:6] else 0x336699
    return (h >> 16) & 255, (h >> 8) & 255, h & 255


def write_solid_png(path: Path, seed: str, width: int = 64, height: int = 64) -> None:
    r, g, b = color_from_hash(seed)
    write_png(path, width, height, bytes([r, g, b]) * (width * height))


def write_exr_stub(path: Path, seed: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(EXR_MAGIC + seed.encode("ascii", "replace")[:64].ljust(64, b"\x00"))


def write_webp_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MINIMAL_WEBP)


def write_glb_stub(path: Path, name: str = "Product") -> None:
    """Minimal GLB 2.0 with an empty JSON scene (valid container, no mesh)."""
    json_chunk = (
        '{"asset":{"version":"2.0","generator":"fox3d-mock"},'
        '"scene":0,"scenes":[{"nodes":[0],"name":"%s"}],'
        '"nodes":[{"name":"%s"}]}' % (name, name)
    ).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "
    json_header = struct.pack("<II", len(json_chunk), 0x4E4F534A)  # JSON
    total = 12 + 8 + len(json_chunk)
    header = struct.pack("<4sII", b"glTF", 2, total)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + json_header + json_chunk)


def is_png(target: Path | str | bytes) -> bool:
    if isinstance(target, (bytes, bytearray)):
        return len(target) >= 8 and target[:8] == b"\x89PNG\r\n\x1a\n"
    p = Path(target)
    return p.is_file() and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def is_glb(target: Path | str | bytes) -> bool:
    if isinstance(target, (bytes, bytearray)):
        return len(target) >= 4 and target[:4] == b"glTF"
    p = Path(target)
    return p.is_file() and p.read_bytes()[:4] == b"glTF"
