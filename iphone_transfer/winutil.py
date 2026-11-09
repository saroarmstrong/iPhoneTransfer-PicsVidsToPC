"""Small Windows helpers (all safe no-ops on other systems)."""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path
from typing import Optional

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0     # CREATE_NO_WINDOW


def run_hidden(args: list[str], timeout: float = 20) -> tuple[int, str]:
    """Run a console program without flashing a window. Returns (exit code, output)."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        out = r.stdout or r.stderr or b""
        for enc in ("utf-8", "mbcs" if IS_WIN else "latin-1"):
            try:
                return r.returncode, out.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return r.returncode, out.decode("latin-1", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


# ------------------------------------------------------------ keep awake
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    """Stop Windows from going to sleep while a copy runs (the screen may still turn off)."""
    if not IS_WIN:
        return
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


# ------------------------------------------------------------ power
def on_battery() -> Optional[bool]:
    if not IS_WIN:
        return None

    class SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    s = SPS()
    try:
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None
    except Exception:
        return None
    if s.ACLineStatus == 0:
        return True
    if s.ACLineStatus == 1:
        return False
    return None


# ------------------------------------------------------------ disks
def volume_filesystem(path: Path) -> str:
    """'NTFS', 'exFAT', 'FAT32', ... for the drive holding path ('' if unknown)."""
    if not IS_WIN:
        return ""
    root = os.path.splitdrive(os.path.abspath(str(path)))[0] + "\\"
    if root.startswith("\\\\\\"):
        return ""
    fs = ctypes.create_unicode_buffer(64)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0, None, None, None, fs, 64)
    except Exception:
        return ""
    return fs.value if ok else ""


def is_network_path(path: Path) -> bool:
    p = os.path.abspath(str(path))
    if p.startswith("\\\\"):
        return True
    if IS_WIN:
        try:
            return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(p[:3])) == 4  # DRIVE_REMOTE
        except Exception:
            return False
    return False


# ------------------------------------------------------------ elevation
def run_elevated(exe: str, params: str) -> bool:
    """Start a program as administrator (Windows asks the user first)."""
    if not IS_WIN:
        return False
    try:
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 0)
        return r > 32
    except Exception:
        return False
