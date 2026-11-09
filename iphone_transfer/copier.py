"""Async copy engine: phone (AFC) -> PC.

Speed notes
  * Several files are copied at once (default 4) over 2 AFC connections, so
    the USB link is never idle waiting for a round trip.
  * Each file is read in 4 MB chunks and written by a worker thread while the
    next chunk is already being requested.
  * Files already in the destination with the same size are skipped without
    touching the phone, so re-running a backup only copies what is new.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import datetime as dt
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pymobiledevice3.exceptions import AfcException, AfcFileNotFoundError, ConnectionTerminatedError

from .device import DeviceHub
from .convert import HEIC_EXT, heic_to_jpg
from .planner import KIND_EDITED, KIND_LIVE, KIND_ORIGINAL, CopyJob

log = logging.getLogger(__name__)

CHUNK = 4 * 1024 * 1024


def file_sha256(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return d.hexdigest()
            d.update(b)


def set_created_time(path: Path, ts: float) -> None:
    """Set the Windows 'Created' time (os.utime only sets Modified/Accessed)."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    FILE_WRITE_ATTRIBUTES, OPEN_EXISTING = 0x100, 3
    h = k32.CreateFileW(str(path), FILE_WRITE_ATTRIBUTES, 0x7, None, OPEN_EXISTING, 0x80, None)
    if h in (None, wintypes.HANDLE(-1).value):
        return
    try:
        ft = int(ts * 10_000_000) + 116444736000000000   # 100 ns ticks since 1601
        v = ctypes.c_ulonglong(ft)
        k32.SetFileTime(h, ctypes.byref(v), None, None)
    finally:
        k32.CloseHandle(h)


@dataclass
class Progress:
    total_files: int = 0
    total_bytes: int = 0          # estimate
    done_files: int = 0           # copied + skipped + missing + failed
    copied_files: int = 0
    copied_bytes: int = 0
    skipped_files: int = 0
    skipped_bytes: int = 0
    copied_edited: int = 0        # extra files, not counted in copied_files
    copied_live: int = 0
    skipped_extra: int = 0
    verified_files: int = 0
    converted_files: int = 0
    missing: list[str] = field(default_factory=list)     # not on the phone (iCloud only)
    failed: list[tuple[str, str]] = field(default_factory=list)
    speed: float = 0.0            # bytes/s over the last few seconds
    eta: Optional[float] = None   # seconds
    current: str = ""
    finished: bool = False
    cancelled: bool = False
    fatal: str = ""
    elapsed: float = 0.0

    def snapshot(self) -> "Progress":
        p = Progress(**{k: getattr(self, k) for k in self.__dataclass_fields__})
        p.missing = list(self.missing)
        p.failed = list(self.failed)
        return p


class Disconnected(Exception):
    pass


class CopyEngine:
    def __init__(self, hub: DeviceHub, jobs: list[CopyJob], workers: int = 4,
                 on_progress: Optional[Callable[[Progress], None]] = None,
                 verify: bool = False, convert_heic: bool = False):
        self.hub = hub
        self.verify = verify
        self.convert_heic = convert_heic
        self.jobs = jobs
        self.workers = max(1, workers)
        self.on_progress = on_progress
        self.p = Progress(total_files=sum(1 for j in jobs if j.kind == KIND_ORIGINAL),
                          total_bytes=sum(j.size for j in jobs))
        self._cancel = asyncio.Event()
        self._samples: collections.deque = collections.deque()
        self._start = 0.0
        self._bytes_in_flight = 0
        self._aux_total = sum(1 for j in jobs if j.kind != KIND_ORIGINAL)

    def cancel(self) -> None:
        self.hub.loop.call_soon_threadsafe(self._cancel.set)

    # ------------------------------------------------------------------ run
    async def run(self) -> Progress:
        self._start = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue()
        for j in self.jobs:
            queue.put_nowait(j)
        conns = await self.hub.afc_pool(min(2, self.workers))
        reporter = asyncio.create_task(self._report_loop())
        try:
            results = await asyncio.gather(
                *[self._worker(conns[i % len(conns)], queue) for i in range(self.workers)],
                return_exceptions=True)
            for r in results:
                if isinstance(r, Disconnected):
                    self.p.fatal = str(r)
                elif isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                    self.p.fatal = f"{type(r).__name__}: {r}"
        finally:
            self.p.cancelled = self._cancel.is_set() and not self.p.fatal
            self.p.finished = True
            self.p.elapsed = time.monotonic() - self._start
            reporter.cancel()
            self._emit()
        return self.p

    async def _worker(self, afc, queue: asyncio.Queue) -> None:
        while not self._cancel.is_set():
            try:
                job: CopyJob = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if job.kind == KIND_EDITED:
                    await self._copy_edited(afc, job)
                else:
                    await self._copy_one(afc, job, job.src, job.dest, optional=(job.kind == KIND_LIVE))
            except Disconnected:
                self._cancel.set()
                raise
            except Exception as e:  # never let one file stop the whole run
                log.exception("failed %s", job.src)
                self.p.failed.append((job.label or job.src, f"{type(e).__name__}: {e}"))
            finally:
                if job.kind == KIND_ORIGINAL:
                    self.p.done_files += 1

    # --------------------------------------------------------------- copy
    async def _copy_edited(self, afc, job: CopyJob) -> None:
        try:
            names = await afc.listdir(job.src)
        except AfcFileNotFoundError:
            return
        except (ConnectionTerminatedError, ConnectionError) as e:
            raise Disconnected("The iPhone was disconnected.") from e
        video_ext = ("mov", "mp4", "m4v")
        renders = []
        for n in names:
            if not n.lower().startswith("fullsizerender."):
                continue
            is_video_file = n.rsplit(".", 1)[-1].lower() in video_ext
            # videos: only the edited video (skip the poster frame)
            # photos: the edited image, plus the edited motion part only for Live Photos
            if job.is_video and not is_video_file:
                continue
            if not job.is_video and is_video_file and not job.live:
                continue
            renders.append(n)
        for n in renders:
            ext = n.rsplit(".", 1)[-1].upper()
            dest = Path(str(job.dest).replace("{ext}", ext))
            await self._copy_one(afc, job, f"{job.src}/{n}", dest, optional=True)

    async def _copy_one(self, afc, job: CopyJob, src: str, dest: Path, optional: bool) -> None:
        if self._cancel.is_set():
            return
        convert = self.convert_heic and dest.suffix.lower().lstrip(".") in HEIC_EXT
        final = dest.with_suffix(".JPG") if convert else dest
        self.p.current = final.name
        # ---- skip if already there (same name + size; converted files: same name)
        try:
            existing = final.stat().st_size
        except FileNotFoundError:
            existing = -1
        if existing >= 0:
            if convert:
                same = existing > 0
            else:
                remote = job.size if (job.kind == KIND_ORIGINAL and job.size > 0) else -1
                if remote != existing:
                    try:
                        remote = int((await afc.stat(src)).get("st_size", -1))
                    except AfcFileNotFoundError:
                        remote = -2
                    except (ConnectionTerminatedError, ConnectionError) as e:
                        raise Disconnected("The iPhone was disconnected.") from e
                same = remote == existing
            if same:
                if job.when is not None:   # also fixes files copied by older versions
                    await asyncio.to_thread(self._set_times, final, job.when)
                if job.kind == KIND_ORIGINAL:
                    self.p.skipped_files += 1
                    self.p.skipped_bytes += job.size if convert else existing
                else:
                    self.p.skipped_extra += 1
                return

        # ---- copy to .part, then rename
        tmp = dest.with_name(dest.name + ".part")
        try:
            h = await afc.fopen(src)
        except AfcFileNotFoundError:
            if not optional:
                self.p.missing.append(job.label or src)
            return
        except (ConnectionTerminatedError, ConnectionError) as e:
            raise Disconnected("The iPhone was disconnected.") from e

        written = 0
        ok = False
        digest = hashlib.sha256()
        try:
            await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
            f = await asyncio.to_thread(open, tmp, "wb")
            try:
                pending_write: Optional[asyncio.Future] = None
                while True:
                    if self._cancel.is_set():
                        break
                    try:
                        data = await afc.fread(h, CHUNK)
                    except (ConnectionTerminatedError, ConnectionError) as e:
                        raise Disconnected("The iPhone was disconnected.") from e
                    if pending_write is not None:
                        await pending_write
                    if not data:
                        ok = True
                        break
                    pending_write = asyncio.ensure_future(asyncio.to_thread(self._write, f, data, digest))
                    written += len(data)
                    self.p.copied_bytes += len(data)
                    self._sample(len(data))
                if pending_write is not None:
                    await pending_write
            finally:
                await asyncio.to_thread(f.close)
        finally:
            try:
                await afc.fclose(h)
            except Exception:
                pass
            if not ok:
                self.p.copied_bytes -= written
                try:
                    tmp.unlink()
                except OSError:
                    pass
        if not ok:
            return

        if self.verify:
            self.p.current = f"verifying {final.name}"
            remote_hash = await self._remote_hash(afc, src)
            if remote_hash is None:          # cancelled while verifying
                await asyncio.to_thread(self._unlink, tmp)
                self.p.copied_bytes -= written
                return
            local_hash = await asyncio.to_thread(file_sha256, tmp)
            if remote_hash != digest.hexdigest() or local_hash != digest.hexdigest():
                await asyncio.to_thread(self._unlink, tmp)
                self.p.copied_bytes -= written
                self.p.failed.append((job.label or src,
                                      "verification failed (file differs) - press Start Copy again"))
                return
            self.p.verified_files += 1

        if convert:
            try:
                await asyncio.to_thread(heic_to_jpg, tmp, final)
            except Exception as e:
                log.exception("convert %s", src)
                # keep the original HEIC rather than losing the file
                await asyncio.to_thread(self._finish_file, tmp, dest, job.when)
                self.p.failed.append((job.label or src, f"could not convert to JPG, kept HEIC ({type(e).__name__})"))
            else:
                self.p.converted_files += 1
                if job.when is not None:
                    await asyncio.to_thread(self._set_times, final, job.when)
        else:
            await asyncio.to_thread(self._finish_file, tmp, dest, job.when)
        if job.kind == KIND_ORIGINAL:
            self.p.copied_files += 1
            # replace the estimate with the real size
            self.p.total_bytes += written - job.size
        else:
            self.p.total_bytes += written
            if job.kind == KIND_EDITED:
                self.p.copied_edited += 1
            else:
                self.p.copied_live += 1

    async def _remote_hash(self, afc, src: str) -> Optional[str]:
        """Read the file from the phone a second time and hash it."""
        d = hashlib.sha256()
        try:
            h = await afc.fopen(src)
        except (ConnectionTerminatedError, ConnectionError) as e:
            raise Disconnected("The iPhone was disconnected.") from e
        try:
            while True:
                if self._cancel.is_set():
                    return None
                try:
                    data = await afc.fread(h, CHUNK)
                except (ConnectionTerminatedError, ConnectionError) as e:
                    raise Disconnected("The iPhone was disconnected.") from e
                if not data:
                    return d.hexdigest()
                await asyncio.to_thread(d.update, data)
        finally:
            try:
                await afc.fclose(h)
            except Exception:
                pass

    @staticmethod
    def _write(f, data: bytes, digest) -> None:
        f.write(data)
        digest.update(data)

    @staticmethod
    def _unlink(p: Path) -> None:
        try:
            p.unlink()
        except OSError:
            pass

    @staticmethod
    def _finish_file(tmp: Path, dest: Path, when: Optional[dt.datetime]) -> None:
        os.replace(tmp, dest)
        if when is not None:
            CopyEngine._set_times(dest, when)

    @staticmethod
    def _set_times(dest: Path, when: dt.datetime) -> None:
        """Created + Modified = the date used in the file name."""
        try:
            ts = when.timestamp()
            os.utime(dest, (ts, ts))
            set_created_time(dest, ts)
        except (OverflowError, OSError, ValueError):
            pass

    # ----------------------------------------------------------- progress
    def _sample(self, n: int) -> None:
        now = time.monotonic()
        self._samples.append((now, n))
        while self._samples and now - self._samples[0][0] > 5.0:
            self._samples.popleft()

    def _update_rates(self) -> None:
        now = time.monotonic()
        while self._samples and now - self._samples[0][0] > 5.0:
            self._samples.popleft()
        window = min(5.0, max(0.5, now - self._start))
        self.p.speed = sum(n for _, n in self._samples) / window
        self.p.elapsed = now - self._start
        remaining = max(0, self.p.total_bytes - self.p.copied_bytes - self.p.skipped_bytes)
        overall = self.p.copied_bytes / max(0.001, self.p.elapsed)
        rate = self.p.speed or overall
        self.p.eta = remaining / rate if rate > 0 else None

    def _emit(self) -> None:
        self._update_rates()
        if self.on_progress:
            try:
                self.on_progress(self.p.snapshot())
            except Exception:
                log.exception("progress callback")

    async def _report_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            self._emit()
