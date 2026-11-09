"""High-level operations used by the GUI (and by the headless test script)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

from .device import DeviceHub, make_read_many
from .library import Library, load_library
from .remote_sqlite import RemoteDB

log = logging.getLogger(__name__)

DB_PATH = "/PhotoData/Photos.sqlite"


def read_library(hub: DeviceHub, progress: Optional[Callable[[str], None]] = None) -> Library:
    """Blocking. Call from a worker thread (not the device loop thread)."""
    say = progress or (lambda m: None)
    t0 = time.monotonic()
    size = hub.call(hub.stat_size(DB_PATH), timeout=60)
    try:
        wal = hub.call(hub.read_file(DB_PATH + "-wal"), timeout=300)
    except Exception:
        log.warning("no WAL file", exc_info=True)
        wal = b""
    db = RemoteDB("photos", size, make_read_many(hub, DB_PATH), wal)
    try:
        conn = db.connect()

        def prefetch(roots):
            db.prefetch_btrees(roots, progress=lambda n: say(f"Reading Photos library from iPhone… {n * db.page_size / 1e6:,.0f} MB"))

        lib = load_library(conn, progress=say, prefetch=prefetch)
        conn.close()
    finally:
        db.close()
    log.info("library read in %.1fs, %.0f MB fetched", time.monotonic() - t0, db.bytes_fetched / 1e6)
    return lib
