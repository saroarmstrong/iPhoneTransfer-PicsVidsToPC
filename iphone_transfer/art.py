"""Access to the app's artwork (background, watercolour buttons and cards, icons).

The artwork is NOT part of the open-source code and is not covered by the GPL: see ARTWORK-LICENSE.md.
Release builds carry it in one packed, scrambled file (assets/art.pak) that is unpacked in memory only.
Without the artwork the app still works, with a plain look.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFile, QIODevice, QResource

log = logging.getLogger(__name__)

MAGIC = b"IPTART1\0"
_TAG = b"iPhoneTransfer artwork (c) saroarmstrong - all rights reserved - not covered by the GPL"

_root: Optional[str] = None
_keep: bytes = b""          # Qt reads registered resource data in place, so it must stay alive


def _xor(body: bytes, nonce: bytes) -> bytes:
    key = hashlib.shake_256(nonce + _TAG).digest(len(body))
    return (int.from_bytes(body, "little") ^ int.from_bytes(key, "little")).to_bytes(len(body), "little")


def scramble(data: bytes) -> bytes:
    nonce = os.urandom(16)
    return MAGIC + nonce + _xor(data, nonce)


def unscramble(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not an artwork pack")
    return _xor(blob[24:], blob[8:24])


def init(asset_dir: Path) -> None:
    """Use assets/art.pak if present (release build), else loose files (developer copy), else nothing."""
    global _root, _keep
    pak = asset_dir / "art.pak"
    if pak.exists():
        try:
            data = unscramble(pak.read_bytes())
            if QResource.registerResourceData(data):
                _keep, _root = data, ":/art"
                return
            log.warning("artwork pack could not be registered")
        except Exception:
            log.exception("artwork pack")
    if (asset_dir / "ui" / "skin").is_dir():
        _root = asset_dir.as_posix()


def available() -> bool:
    return _root is not None


def path(rel: str) -> Optional[str]:
    return f"{_root}/{rel}" if _root else None


def exists(rel: str) -> bool:
    p = path(rel)
    return bool(p) and QFile.exists(p)


def read(rel: str) -> bytes:
    f = QFile(path(rel) or "")
    if not f.open(QIODevice.ReadOnly):
        return b""
    try:
        return bytes(f.readAll())
    finally:
        f.close()
