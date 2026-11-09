"""Optional HEIC -> JPG conversion (NOT lossless; off by default)."""
from __future__ import annotations

import os
from pathlib import Path

HEIC_EXT = {"heic", "heif"}
_registered = False


def heic_to_jpg(src: Path, dst: Path, quality: int = 95) -> None:
    """Convert src (HEIC) to dst (JPG), keeping EXIF (date, GPS, camera) and colour profile.
    src is deleted afterwards."""
    global _registered
    import pillow_heif
    from PIL import Image
    if not _registered:
        pillow_heif.register_heif_opener()
        _registered = True
    tmp = dst.with_name(dst.name + ".part")
    with Image.open(src) as im:
        exif = im.info.get("exif") or b""
        icc = im.info.get("icc_profile")
        kw = {"quality": quality, "exif": exif}
        if icc:
            kw["icc_profile"] = icc
        im.convert("RGB").save(tmp, "JPEG", **kw)
    os.replace(tmp, dst)
    try:
        src.unlink()
    except OSError:
        pass
