"""iPhone connection over Apple Mobile Device Service (usbmux) using pymobiledevice3.

All device I/O is asyncio. A single background thread owns the event loop;
other threads submit coroutines with DeviceHub.call()/submit().
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3 import usbmux

log = logging.getLogger(__name__)


class DeviceError(Exception):
    """Human readable problem with the device connection (+ steps to fix it)."""

    def __init__(self, problem: str, steps: Optional[list[str]] = None):
        super().__init__(problem)
        self.problem = problem
        self.steps = steps or []


class _NoDevice(Exception):
    pass


_NoDevice.__name__ = "NoDeviceConnectedError"


@dataclass
class DeviceInfo:
    name: str
    model: str
    ios: str
    serial: str
    connection: str          # "USB" or "Network"


class DeviceHub:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="device-loop", daemon=True)
        self.thread.start()
        self.lockdown = None
        self.info: Optional[DeviceInfo] = None
        self._afc_pool: list[AfcService] = []

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # -- thread bridge ----------------------------------------------------
    def submit(self, coro: Awaitable) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call(self, coro: Awaitable, timeout: Optional[float] = None) -> Any:
        return self.submit(coro).result(timeout)

    # -- connection -------------------------------------------------------
    async def connect(self, on_status: Optional[Callable[[str], None]] = None) -> DeviceInfo:
        from .doctor import explain_connect_error
        await self.disconnect()
        try:
            devices = await usbmux.list_devices()
        except Exception as e:  # usbmux service not reachable
            problem, steps = explain_connect_error(ConnectionRefusedError())
            raise DeviceError(problem, steps) from e
        if not devices:
            problem, steps = explain_connect_error(_NoDevice())
            raise DeviceError(problem, steps)
        usb = [d for d in devices if d.connection_type == "USB"]
        dev = usb[0] if usb else devices[0]

        async def hint():
            await asyncio.sleep(3)
            if on_status:
                on_status("Waiting for the iPhone… If it asks 'Trust This Computer?', tap Trust and enter your passcode.")
        hint_task = asyncio.ensure_future(hint())
        try:
            ld = await create_using_usbmux(serial=dev.serial, connection_type=dev.connection_type,
                                           pair_timeout=90)
        except Exception as e:
            problem, steps = explain_connect_error(e)
            raise DeviceError(problem, steps) from e
        finally:
            hint_task.cancel()
        self.lockdown = ld
        v = ld.all_values
        self.info = DeviceInfo(
            name=v.get("DeviceName", "iPhone"),
            model=v.get("ProductType", ""),
            ios=v.get("ProductVersion", ""),
            serial=dev.serial,
            connection=dev.connection_type,
        )
        log.info("connected: %s", self.info)
        return self.info

    async def disconnect(self) -> None:
        await self.close_afc_pool()
        if self.lockdown is not None:
            try:
                await self.lockdown.close()
            except Exception:
                pass
        self.lockdown = None

    async def open_afc(self) -> AfcService:
        if self.lockdown is None:
            raise DeviceError("iPhone is not connected.")
        afc = AfcService(self.lockdown)
        await afc.__aenter__()
        return afc

    async def afc_pool(self, n: int) -> list[AfcService]:
        while len(self._afc_pool) < n:
            self._afc_pool.append(await self.open_afc())
        return self._afc_pool[:n]

    async def close_afc_pool(self) -> None:
        pool, self._afc_pool = self._afc_pool, []
        for afc in pool:
            try:
                await afc.aclose()
            except Exception:
                pass

    # -- ranged reads for the remote SQLite reader -------------------------
    async def read_ranges(self, path: str, reqs: list[tuple[int, int]],
                          connections: int = 4, handles_per_conn: int = 8) -> list[bytes]:
        """Read many (offset, size) ranges of one file concurrently.

        AFC has no positional read, so every stream is its own file handle doing
        seek+read. Requests are spread over several handles and connections so
        dozens are in flight at once.
        """
        pool = await self.afc_pool(connections)
        results: list[Optional[bytes]] = [None] * len(reqs)
        queue: asyncio.Queue = asyncio.Queue()
        for i, r in enumerate(reqs):
            queue.put_nowait((i, r))

        async def worker(afc: AfcService) -> None:
            h = await afc.fopen(path)
            try:
                while True:
                    try:
                        i, (off, size) = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    await afc.fseek(h, off)
                    results[i] = await afc.fread(h, size)
            finally:
                try:
                    await afc.fclose(h)
                except Exception:
                    pass

        n_workers = min(len(reqs), connections * handles_per_conn) or 1
        await asyncio.gather(*[worker(pool[k % len(pool)]) for k in range(n_workers)])
        return [r or b"" for r in results]

    async def stat_size(self, path: str) -> int:
        pool = await self.afc_pool(1)
        st = await pool[0].stat(path)
        return int(st.get("st_size", 0))

    async def read_file(self, path: str) -> bytes:
        pool = await self.afc_pool(1)
        return await pool[0].get_file_contents(path)

    async def listdir(self, path: str) -> list[str]:
        pool = await self.afc_pool(1)
        return await pool[0].listdir(path)


def make_read_many(hub: DeviceHub, path: str) -> Callable[[list[tuple[int, int]]], list[bytes]]:
    """Blocking adapter for RemoteDB, to be called from a worker thread."""
    def read_many(reqs):
        return hub.call(hub.read_ranges(path, reqs), timeout=600)
    return read_many
