"""Troubleshoot: step-by-step checks that explain why an iPhone won't connect.

Each check returns a Check with a plain-English result and what to do about it.
Checks run in order; later device checks are skipped when an earlier one fails.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import winutil

log = logging.getLogger(__name__)

OK, WARN, FAIL, INFO, SKIP = "ok", "warn", "fail", "info", "skip"

APPLE_SERVICE = "Apple Mobile Device Service"
APPLE_DEVICES_STORE = "https://apps.microsoft.com/detail/9NP83LWLPZ9K"     # "Apple Devices" app
ITUNES_STORE = "https://apps.microsoft.com/detail/9PB2MZ1ZMB1S"
OTHER_APPS = {
    "itunes.exe": "iTunes", "appledevices.exe": "Apple Devices", "imazing.exe": "iMazing",
    "copytrans.exe": "CopyTrans", "copytransshelbee.exe": "CopyTrans", "copytransphoto.exe": "CopyTrans Photo",
    "copytransstudio.exe": "CopyTrans Studio", "3utools.exe": "3uTools", "anytrans.exe": "AnyTrans",
    "icloudphotos.exe": "iCloud Photos", "photos.exe": "Windows Photos (import)",
}


@dataclass
class Check:
    title: str
    status: str = INFO
    detail: str = ""
    fix: list[str] = field(default_factory=list)
    action: str = ""          # optional button: "store", "restart_service", "device_manager"


# ------------------------------------------------------------ error messages
def explain_connect_error(e: BaseException) -> tuple[str, list[str]]:
    """Turn a pymobiledevice3 / usbmux exception into (problem, steps to fix)."""
    name = type(e).__name__
    if name in ("ConnectionFailedToUsbmuxdError",) or isinstance(e, ConnectionRefusedError):
        return ("Apple Mobile Device Service is not reachable.",
                ["Install the free 'Apple Devices' app (or iTunes) from the Microsoft Store.",
                 "Then open Troubleshoot and press 'Restart Apple service'."])
    if name in ("PasswordRequiredError", "PasscodeRequiredError"):
        return ("Your iPhone is locked.",
                ["Unlock the iPhone (Face ID / passcode) and keep it on the Home Screen.",
                 "Press Connect again."])
    if name == "PairingDialogResponsePendingError":
        return ("Your iPhone is waiting for you to tap 'Trust'.",
                ["Look at the iPhone screen: tap 'Trust' and enter your passcode.",
                 "No pop-up? Unplug the cable, unlock the phone, plug it back in."])
    if name == "UserDeniedPairingError":
        return ("'Don't Trust' was chosen on the iPhone.",
                ["Unplug and plug the cable back in, then tap 'Trust'.",
                 "If the question never comes back: on the iPhone go to Settings > General > "
                 "Transfer or Reset iPhone > Reset > Reset Location & Privacy, then plug in again."])
    if name in ("InvalidHostIDError", "NotPairedError", "FatalPairingError", "PairingError", "NotTrustedError"):
        return ("The iPhone no longer trusts this PC (old pairing).",
                ["On the iPhone: Settings > General > Transfer or Reset iPhone > Reset > Reset Location & Privacy.",
                 "Unplug, plug back in, unlock and tap 'Trust'."])
    if name in ("NoDeviceConnectedError", "DeviceNotFoundError", "IRecvNoDeviceConnectedError"):
        return ("No iPhone found.",
                ["Plug the iPhone in with a USB data cable (not a charge-only cable), directly into the PC.",
                 "Unlock it. If it asks 'Allow accessory to connect?' or 'Trust this computer?', allow it."])
    if name in ("ConnectionTerminatedError", "StreamClosedError", "ConnectionAbortedError",
                "ConnectionResetError", "BrokenPipeError", "MuxException", "ConnectionFailedError"):
        return ("The connection to the iPhone dropped.",
                ["Unlock the iPhone, unplug and re-plug the cable, then press Connect again.",
                 "Use a short, original or MFi-certified data cable straight into a USB port on the PC (no hub).",
                 "Still dropping? Open Troubleshoot."])
    if isinstance(e, TimeoutError) or name in ("TimeoutError", "CancelledError"):
        return ("The iPhone did not answer in time.",
                ["Unlock the iPhone and check for a 'Trust' pop-up.",
                 "Unplug, wait 5 seconds, plug back in and press Connect again."])
    return (f"Could not talk to the iPhone ({name}: {e}).",
            ["Unlock the iPhone, unplug and re-plug the cable and press Connect again.",
             "Then open Troubleshoot for a step-by-step check."])


# ------------------------------------------------------------ individual checks
def check_windows() -> Check:
    c = Check("Windows version")
    rel, ver = platform.release(), platform.version()
    bits = "64-bit" if sys.maxsize > 2 ** 32 and platform.machine().endswith("64") else platform.machine()
    try:
        build = int(ver.split(".")[-1])
    except ValueError:
        build = 0
    name = "Windows 11" if (rel == "10" and build >= 22000) or rel == "11" else f"Windows {rel}"
    c.detail = f"{name} (build {ver}), {bits}"
    if os.name != "nt":
        c.status, c.fix = WARN, ["This app is made for Windows 10 and 11."]
    elif rel in ("10", "11"):
        c.status = OK
    else:
        c.status, c.fix = WARN, ["Windows 10 or 11 is required."]
    return c


def check_apple_service() -> Check:
    c = Check("Apple Mobile Device Service")
    code, out = winutil.run_hidden(["sc", "query", APPLE_SERVICE])
    if code == 1060 or "1060" in out:
        c.status = FAIL
        c.detail = "Not installed. Windows needs Apple's free driver and service to talk to an iPhone."
        c.fix = ["Install 'Apple Devices' from the Microsoft Store (or iTunes). You don't need to sign in or use it.",
                 "Restart this app afterwards."]
        c.action = "store"
    elif "RUNNING" in out:
        c.status, c.detail = OK, "Installed and running."
    elif "STOPPED" in out or "STOP_PENDING" in out or "START_PENDING" in out:
        c.status = FAIL
        c.detail = "Installed but not running."
        c.fix = ["Press 'Restart Apple service' (Windows will ask for permission)."]
        c.action = "restart_service"
    else:
        c.status, c.detail = WARN, f"Could not read the service state ({out.strip()[:120]})."
    return c


def list_apple_usb() -> list[dict]:
    """Apple USB devices Windows sees: [{'name', 'status', 'cls', 'id'}]."""
    ps = ("Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
          "Where-Object { $_.InstanceId -like 'USB\\VID_05AC*' } | "
          "Select-Object FriendlyName,Status,Class,InstanceId | ConvertTo-Json -Compress")
    code, out = winutil.run_hidden(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30)
    out = out.strip()
    if not out or not out.startswith(("[", "{")):
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"name": d.get("FriendlyName") or "", "status": d.get("Status") or "",
             "cls": d.get("Class") or "", "id": d.get("InstanceId") or ""} for d in data]


def check_usb(devs: list[dict]) -> Check:
    c = Check("iPhone plugged in (USB)")
    if not devs:
        c.status = WARN
        c.detail = "Windows does not see any iPhone on USB."
        c.fix = ["Plug the iPhone in with a USB data cable, directly into the PC (not a hub, keyboard or monitor port).",
                 "Unlock the iPhone. If it asks 'Allow accessory to connect?', tap Allow.",
                 "Try another cable or USB port; many cheap cables only charge.",
                 "If the phone charges but nothing else happens, the cable is almost always the problem."]
        return c
    names = ", ".join(sorted({d["name"] for d in devs if d["name"]}))
    bad = [d for d in devs if d["status"].upper() not in ("OK", "")]
    has_driver = any("apple mobile device usb device" in d["name"].lower() for d in devs)
    if bad:
        c.status = FAIL
        c.detail = "Driver problem: " + ", ".join(f"{d['name']} ({d['status']})" for d in bad)
        c.fix = ["Reinstall or repair 'Apple Devices' / iTunes, then restart the PC.",
                 "Or open Device Manager, right-click the Apple device > Uninstall device, unplug and plug back in."]
        c.action = "device_manager"
    elif not has_driver:
        c.status = FAIL
        c.detail = f"Windows sees the iPhone ({names}) but Apple's USB driver is missing."
        c.fix = ["Install 'Apple Devices' from the Microsoft Store (or iTunes), then unplug and re-plug the iPhone."]
        c.action = "store"
    else:
        c.status, c.detail = OK, names
        c.fix = ["Double-check in File Explorer: This PC > Apple iPhone should show Internal Storage with "
                 "folders inside. If it's empty, unlock the iPhone and plug it in again."]
        c.action = "thispc"
    return c


def check_power() -> Check:
    c = Check("Power")
    bat = winutil.on_battery()
    if bat:
        c.status = WARN
        c.detail = "This PC is running on battery."
        c.fix = ["Plug in the charger: big copies can take hours. (The app keeps the PC awake while copying.)"]
    else:
        c.status, c.detail = OK, "Plugged in (the app keeps the PC awake while copying)."
    return c


def check_other_apps() -> Check:
    c = Check("Other apps using the iPhone")
    code, out = winutil.run_hidden(["tasklist", "/fo", "csv", "/nh"])
    running = sorted({OTHER_APPS[n] for n in OTHER_APPS if f'"{n}"' in out.lower()})
    if running:
        c.status = WARN
        c.detail = "Running: " + ", ".join(running)
        c.fix = ["Close these apps while copying. iTunes / Apple Devices may start a sync or backup, "
                 "and other transfer apps can hold the connection and make it slow or drop."]
    else:
        c.status, c.detail = OK, "None found."
    return c


def check_destination(dest: Optional[Path], need_bytes: int = 0) -> Check:
    c = Check("Destination folder")
    if not dest:
        c.status, c.detail = SKIP, "No folder chosen yet."
        return c
    probe = Path(dest)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as e:
        c.status, c.detail = FAIL, f"{dest}: {e}"
        return c
    fs = winutil.volume_filesystem(probe)
    parts = [f"{dest}", f"{free / 1e9:,.0f} GB free", fs or "unknown file system"]
    c.detail = " · ".join(parts)
    c.status = OK
    if fs.upper() in ("FAT32", "FAT"):
        c.status = WARN
        c.fix.append("This drive is FAT32: videos larger than 4 GB cannot be saved on it. "
                     "Use an NTFS or exFAT drive (or reformat this one as exFAT).")
    if winutil.is_network_path(probe):
        c.status = WARN
        c.fix.append("This is a network folder; copying will be limited by the network speed. "
                     "A local or USB drive is much faster.")
    if need_bytes and need_bytes > free:
        c.status = FAIL
        c.fix.append(f"Not enough space for the current selection (needs about {need_bytes / 1e9:,.0f} GB).")
    return c


# ------------------------------------------------------------ device checks (async)
async def device_checks(hub, emit: Callable[[Check], None]) -> None:
    from pymobiledevice3 import usbmux
    from pymobiledevice3.lockdown import create_using_usbmux

    c = Check("Apple service sees the iPhone")
    try:
        devices = await usbmux.list_devices()
    except Exception as e:
        c.status = FAIL
        c.detail, c.fix = explain_connect_error(e)[0], explain_connect_error(e)[1]
        c.action = "restart_service"
        emit(c)
        return
    usb = [d for d in devices if d.connection_type == "USB"]
    if not devices:
        c.status = FAIL
        c.detail = "The Apple service is running but no iPhone is connected to it."
        c.fix = ["Unlock the iPhone and re-plug the cable.",
                 "If 'iPhone plugged in' above is OK, press 'Restart Apple service' and try again."]
        c.action = "restart_service"
        emit(c)
        return
    if not usb:
        c.status = WARN
        c.detail = "Only found over Wi-Fi. Copying over Wi-Fi is about 5-10x slower than USB."
        c.fix = ["Plug in a USB cable for fast copying."]
    else:
        c.status, c.detail = OK, f"Found over USB ({len(devices)} connection(s))."
    emit(c)
    dev = usb[0] if usb else devices[0]

    c = Check("Trust this computer")
    emit(Check("Trust this computer", INFO, "Checking… if your iPhone asks 'Trust This Computer?', tap Trust "
                                            "and enter your passcode."))
    try:
        ld = await create_using_usbmux(serial=dev.serial, connection_type=dev.connection_type, pair_timeout=60)
    except Exception as e:
        c.status = FAIL
        c.detail, c.fix = explain_connect_error(e)
        emit(c)
        return
    v = ld.all_values
    c.status, c.detail = OK, f"Trusted. {v.get('DeviceName', 'iPhone')}, {v.get('ProductType', '')}"
    emit(c)

    c = Check("iOS version")
    ios = v.get("ProductVersion", "")
    try:
        major = int(ios.split(".")[0])
    except ValueError:
        major = 0
    c.detail = f"iOS {ios}"
    if major >= 16:
        c.status = OK
    elif major >= 14:
        c.status = WARN
        c.fix = ["iOS 16 or later is recommended. Older versions may work but are not tested."]
    else:
        c.status = FAIL
        c.fix = ["iOS 14 or later is needed. Update the iPhone in Settings > General > Software Update."]
    emit(c)

    c = Check("Photos library")
    try:
        from pymobiledevice3.services.afc import AfcService
        async with AfcService(ld) as afc:
            st = await afc.stat("/PhotoData/Photos.sqlite")
            size = int(st.get("st_size", 0))
            dcim = await afc.listdir("/DCIM")
        c.status = OK
        c.detail = (f"Readable. Library database {size / 1e9:,.1f} GB, "
                    f"{len([d for d in dcim if d.upper().endswith('APPLE')])} camera folders.")
        if size > 3e9:
            c.detail += " Big library: reading it takes 10-60 s (only ~2% of it is downloaded)."
    except Exception as e:
        c.status = FAIL
        c.detail = f"Could not read the Photos library ({type(e).__name__})."
        c.fix = ["Unlock the iPhone, open the Photos app once, then try again.",
                 "Restart the iPhone if this keeps happening."]
    emit(c)
    try:
        await ld.close()
    except Exception:
        pass


def run_all(hub, dest: Optional[Path], emit: Callable[[Check], None], need_bytes: int = 0) -> list[Check]:
    """Blocking; call from a worker thread. emit() is called for every result (and progress)."""
    results: list[Check] = []

    def out(c: Check) -> None:
        if c.status != INFO or c.title not in [r.title for r in results]:
            results.append(c)
        emit(c)

    for fn in (check_windows, check_apple_service):
        out(fn())
    devs = list_apple_usb()
    out(check_usb(devs))
    out(check_other_apps())
    out(check_power())
    out(check_destination(dest, need_bytes))
    svc_ok = next((r.status for r in results if r.title == "Apple Mobile Device Service"), FAIL) == OK
    if svc_ok:
        try:
            hub.call(device_checks(hub, out), timeout=150)
        except Exception as e:
            log.exception("device checks")
            problem, steps = explain_connect_error(e)
            out(Check("iPhone connection", FAIL, problem, steps))
    else:
        out(Check("iPhone connection", SKIP, "Skipped until the Apple service is fixed."))
    return results


def report_text(results: list[Check], app_version: str) -> str:
    """Plain-text summary to paste into a support request / GitHub issue."""
    icon = {OK: "[OK]", WARN: "[!]", FAIL: "[X]", INFO: "[i]", SKIP: "[-]"}
    lines = [f"iPhoneTransfer Troubleshoot report - app {app_version}", ""]
    for r in results:
        if r.status == INFO and r.title in [x.title for x in results if x.status != INFO]:
            continue
        lines.append(f"{icon.get(r.status, '')} {r.title}: {r.detail}")
        for f in r.fix:
            lines.append(f"      - {f}")
    return "\n".join(lines)
