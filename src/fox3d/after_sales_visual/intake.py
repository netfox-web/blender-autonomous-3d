from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .models import PhotoEvidence


class PhotoIntakeError(ValueError):
    pass


MAX_BYTES = 12_000_000
MAX_PIXELS = 24_000_000
ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}


def intake_photo_bytes(data: bytes, *, source_class: str) -> tuple[PhotoEvidence, bytes]:
    if not data or len(data) > MAX_BYTES:
        raise PhotoIntakeError("photo size is outside the isolated intake limit")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            media_type = ALLOWED_FORMATS.get(probe.format or "")
            if media_type is None:
                raise PhotoIntakeError("only PNG and JPEG are accepted")
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise PhotoIntakeError("decoded image exceeds the pixel limit")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            clean = image.convert("RGB")
            out = io.BytesIO()
            clean.save(out, format="PNG", optimize=False)
            derived = out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PhotoIntakeError("photo cannot be decoded safely") from exc
    evidence = PhotoEvidence(
        original_sha256=hashlib.sha256(data).hexdigest(),
        derived_sha256=hashlib.sha256(derived).hexdigest(),
        media_type=media_type,
        size_bytes=len(data),
        width=width,
        height=height,
        exif_removed=True,
        source_class=source_class,
    )
    return evidence, derived


def read_local_fixture(path: Path, *, fixture_root: Path) -> bytes:
    root = fixture_root.resolve(strict=True)
    if path.is_symlink():
        raise PhotoIntakeError("fixture symlinks are not accepted")
    candidate = path.resolve(strict=True)
    if candidate != root and root not in candidate.parents:
        raise PhotoIntakeError("fixture path escapes the approved root")
    if not candidate.is_file():
        raise PhotoIntakeError("fixture must be a regular local file")
    return candidate.read_bytes()
