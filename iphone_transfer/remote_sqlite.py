"""Read-only SQLite access to a database that lives on the iPhone.

The Photos database on a big library can be 10 GB, but the tables we need
(ZASSET, ZADDITIONALASSETATTRIBUTES, albums) are a few hundred MB. Instead of
downloading the whole file, we register an apsw VFS whose reads are served by
ranged AFC reads, so SQLite only pulls the pages the queries actually touch.

The database is in WAL mode. Recent changes live in Photos.sqlite-wal, which is
small, so we download it, parse the committed frames and overlay those pages on
top of the main file. Page 1 is patched to say "legacy journal mode" so SQLite
opens it without needing a -shm file.
"""
from __future__ import annotations

import logging
import struct
import threading
from collections import OrderedDict
from typing import Callable, Optional

import apsw

log = logging.getLogger(__name__)

# reader(offset, size) -> bytes ; reader_many([(offset, size), ...]) -> [bytes]
ReadMany = Callable[[list[tuple[int, int]]], list[bytes]]


# --------------------------------------------------------------------------- WAL
def parse_wal(wal: bytes) -> tuple[dict[int, bytes], int, int]:
    """Return ({page_no: page_bytes}, db_size_in_pages_or_0, page_size).

    Only frames belonging to fully committed transactions with valid salts and
    checksums are used, which is exactly what SQLite itself would apply.
    """
    if len(wal) < 32:
        return {}, 0, 0
    magic, version, page_size, _ckpt, salt1, salt2, c1, c2 = struct.unpack(">IIIIIIII", wal[:32])
    if magic not in (0x377F0682, 0x377F0683):
        return {}, 0, 0
    big_endian = magic & 1
    fmt = ">" if big_endian else "<"

    def checksum(data: bytes, s0: int, s1: int) -> tuple[int, int]:
        n = len(data) // 4
        words = struct.unpack(f"{fmt}{n}I", data)
        for i in range(0, n, 2):
            s0 = (s0 + words[i] + s1) & 0xFFFFFFFF
            s1 = (s1 + words[i + 1] + s0) & 0xFFFFFFFF
        return s0, s1

    s0, s1 = checksum(wal[:24], 0, 0)
    if (s0, s1) != (c1, c2):
        return {}, 0, page_size

    pages: dict[int, bytes] = {}
    pending: dict[int, bytes] = {}
    db_pages = 0
    frame_size = 24 + page_size
    pos = 32
    while pos + frame_size <= len(wal):
        hdr = wal[pos:pos + 24]
        pgno, commit_size, fs1, fs2, fc1, fc2 = struct.unpack(">IIIIII", hdr)
        if (fs1, fs2) != (salt1, salt2):
            break
        data = wal[pos + 24:pos + frame_size]
        s0, s1 = checksum(hdr[:8], s0, s1)
        s0, s1 = checksum(data, s0, s1)
        if (s0, s1) != (fc1, fc2):
            break
        pending[pgno] = data
        if commit_size:
            pages.update(pending)
            pending.clear()
            db_pages = commit_size
        pos += frame_size
    return pages, db_pages, page_size


# --------------------------------------------------------------------------- VFS
class _RemoteFile:
    def __init__(self, src: "RemoteDB"):
        self.src = src

    # reads ---------------------------------------------------------------
    def xRead(self, amount: int, offset: int) -> bytes:
        return self.src.read(offset, amount)

    def xFileSize(self) -> int:
        return self.src.size

    # read-only / no-op stubs --------------------------------------------
    def xWrite(self, data, offset):
        raise apsw.ReadOnlyError("remote database is read-only")

    def xTruncate(self, newsize):
        raise apsw.ReadOnlyError("remote database is read-only")

    def xSync(self, flags):
        return None

    def xLock(self, level):
        return None

    def xUnlock(self, level):
        return None

    def xCheckReservedLock(self):
        return False

    def xFileControl(self, op, ptr):
        return False

    def xSectorSize(self):
        return 4096

    def xDeviceCharacteristics(self):
        return 0

    def xClose(self):
        return None


class _VFS(apsw.VFS):
    def __init__(self, name: str, registry: dict[str, "RemoteDB"]):
        self.registry = registry
        super().__init__(name, base="")

    def xOpen(self, name, flags):
        fname = name.filename() if isinstance(name, apsw.URIFilename) else name
        if fname in self.registry:
            return _RemoteFile(self.registry[fname])
        raise apsw.CantOpenError(f"no such remote db {fname!r}")

    def xAccess(self, pathname, flags):
        return pathname in self.registry

    def xFullPathname(self, name):
        return name

    def xDelete(self, filename, syncdir):
        return None


_VFS_NAME = "iphone-remote"
_registry: dict[str, "RemoteDB"] = {}
_vfs: Optional[_VFS] = None
_vfs_lock = threading.Lock()


def _ensure_vfs() -> None:
    global _vfs
    with _vfs_lock:
        if _vfs is None:
            _vfs = _VFS(_VFS_NAME, _registry)


class RemoteDB:
    """A remote SQLite file with block cache, read-ahead and WAL overlay."""

    BLOCK = 4096                       # == page size of Photos.sqlite
    READ_AHEAD = 1                     # pages of one table are scattered, read-ahead wastes bandwidth
    MAX_CACHE_BYTES = 1024 * 1024 * 1024
    PREFETCH_BATCH = 2048

    def __init__(self, key: str, size: int, read_many: ReadMany, wal: bytes = b""):
        self.key = key
        self.read_many = read_many
        self.cache: "OrderedDict[int, bytes]" = OrderedDict()
        self.lock = threading.Lock()
        self.bytes_fetched = 0
        self.wal_pages, wal_db_pages, wal_page_size = parse_wal(wal)
        self.page_size = wal_page_size or 4096
        self.size = max(size, wal_db_pages * self.page_size)
        if wal_db_pages:
            # after a commit, the db is exactly this many pages long
            self.size = wal_db_pages * self.page_size
        log.info("RemoteDB %s: %d bytes, %d WAL pages", key, self.size, len(self.wal_pages))

    # -- block cache ------------------------------------------------------
    def _blocks(self, first: int, last: int) -> dict[int, bytes]:
        out: dict[int, bytes] = {}
        missing = []
        with self.lock:
            for b in range(first, last + 1):
                if b in self.cache:
                    self.cache.move_to_end(b)
                    out[b] = self.cache[b]
                else:
                    missing.append(b)
        if missing:
            # read-ahead after the last missing block
            max_block = (self.size - 1) // self.BLOCK
            extra = []
            nxt = missing[-1] + 1
            while len(missing) + len(extra) < max(self.READ_AHEAD, len(missing)) and nxt <= max_block:
                with self.lock:
                    if nxt not in self.cache:
                        extra.append(nxt)
                nxt += 1
            want = missing + extra
            reqs = [(b * self.BLOCK, min(self.BLOCK, self.size - b * self.BLOCK)) for b in want]
            datas = self.read_many(reqs)
            with self.lock:
                for b, d in zip(want, datas):
                    self.cache[b] = d
                    self.bytes_fetched += len(d)
                    if b in missing:
                        out[b] = d
                while len(self.cache) * self.BLOCK > self.MAX_CACHE_BYTES:
                    self.cache.popitem(last=False)
        return out

    def _read_main(self, offset: int, amount: int) -> bytes:
        if offset >= self.size:
            return b""
        end = min(offset + amount, self.size)
        first, last = offset // self.BLOCK, (end - 1) // self.BLOCK
        blocks = self._blocks(first, last)
        buf = b"".join(blocks[b] for b in range(first, last + 1))
        start = offset - first * self.BLOCK
        return buf[start:start + (end - offset)]

    def read(self, offset: int, amount: int) -> bytes:
        ps = self.page_size
        if self.wal_pages and offset % ps == 0 and amount == ps and (offset // ps + 1) in self.wal_pages:
            data = self.wal_pages[offset // ps + 1]
        elif self.wal_pages:
            # generic path: assemble from pages (handles odd reads like the 100-byte header)
            out = bytearray()
            pos, end = offset, offset + amount
            while pos < end:
                pg = pos // ps + 1
                pstart = (pg - 1) * ps
                take = min(end, pstart + ps) - pos
                if pg in self.wal_pages:
                    out += self.wal_pages[pg][pos - pstart:pos - pstart + take]
                else:
                    out += self._read_main(pos, take)
                pos += take
            data = bytes(out)
        else:
            data = self._read_main(offset, amount)
        if offset <= 19 < offset + len(data):
            # bytes 18/19: file format write/read version. 2 = WAL, 1 = legacy.
            b = bytearray(data)
            for i in (18, 19):
                if offset <= i < offset + len(b):
                    b[i - offset] = 1
            data = bytes(b)
        if len(data) < amount:
            data = data + b"\x00" * (amount - len(data))
        return data

    # -- B-tree prefetch --------------------------------------------------
    def prefetch_btrees(self, roots: list[int], progress: Optional[Callable[[int], None]] = None) -> int:
        """Pull every interior and leaf page of the given B-trees into the cache.

        SQLite reads pages one at a time, and on this database the pages of one
        table are spread all over a 10 GB file, so a plain table scan would be
        tens of thousands of sequential round trips. Walking the tree level by
        level lets us request each whole level concurrently instead.
        """
        ps = self.page_size
        frontier = sorted(set(r for r in roots if r and r > 0))
        seen: set[int] = set()
        total = 0
        while frontier:
            frontier = [p for p in frontier if p not in seen and (p - 1) * ps < self.size]
            seen.update(frontier)
            need = []
            with self.lock:
                need = [p for p in frontier if p not in self.wal_pages and (p - 1) not in self.cache]
            for i in range(0, len(need), self.PREFETCH_BATCH):
                chunk = need[i:i + self.PREFETCH_BATCH]
                datas = self.read_many([((p - 1) * ps, ps) for p in chunk])
                with self.lock:
                    for p, d in zip(chunk, datas):
                        self.cache[p - 1] = d
                        self.bytes_fetched += len(d)
                total += len(chunk)
                if progress:
                    progress(total)
            nxt: list[int] = []
            for p in frontier:
                nxt.extend(self._children(p, self.read((p - 1) * ps, ps)))
            frontier = nxt
        return total

    @staticmethod
    def _varint(b: bytes, i: int) -> tuple[int, int]:
        v = 0
        for k in range(9):
            c = b[i + k]
            if k == 8:
                return (v << 8) | c, i + 9
            v = (v << 7) | (c & 0x7F)
            if not c & 0x80:
                return v, i + k + 1
        return v, i + 9

    def _children(self, pgno: int, page: bytes) -> list[int]:
        """Child pages of an interior page, or overflow pages of a table leaf / overflow page."""
        if getattr(self, "_overflow_pages", None) is not None and pgno in self._overflow_pages:
            nxt = struct.unpack_from(">I", page, 0)[0]
            if nxt:
                self._overflow_pages.add(nxt)
                return [nxt]
            return []
        off = 100 if pgno == 1 else 0
        kind = page[off]
        n = struct.unpack_from(">H", page, off + 3)[0]
        if kind == 0x0D:                      # table leaf: follow overflow chains
            usable = len(page)
            x = usable - 35
            m = ((usable - 12) * 32 // 255) - 23
            out = []
            for i in range(n):
                ptr = struct.unpack_from(">H", page, off + 8 + 2 * i)[0]
                try:
                    psize, j = self._varint(page, ptr)
                    _rowid, j = self._varint(page, j)
                except IndexError:
                    continue
                if psize <= x:
                    continue
                k = m + ((psize - m) % (usable - 4))
                local = k if k <= x else m
                if j + local + 4 <= len(page):
                    out.append(struct.unpack_from(">I", page, j + local)[0])
            if out:
                if getattr(self, "_overflow_pages", None) is None:
                    self._overflow_pages = set()
                self._overflow_pages.update(out)
            return out
        if kind not in (0x02, 0x05):          # interior index / interior table
            return []
        right = struct.unpack_from(">I", page, off + 8)[0]
        kids = []
        for i in range(n):
            ptr = struct.unpack_from(">H", page, off + 12 + 2 * i)[0]
            if ptr + 4 <= len(page):
                kids.append(struct.unpack_from(">I", page, ptr)[0])
        kids.append(right)
        return kids

    # -- connection -------------------------------------------------------
    def connect(self) -> apsw.Connection:
        _ensure_vfs()
        _registry[self.key] = self
        return apsw.Connection(
            f"file:{self.key}?immutable=1",
            flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI,
            vfs=_VFS_NAME,
        )

    def close(self) -> None:
        _registry.pop(self.key, None)
        self.cache.clear()
