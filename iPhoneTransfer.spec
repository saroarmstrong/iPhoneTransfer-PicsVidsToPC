# PyInstaller spec - build with:  build.bat
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = collect_submodules("pymobiledevice3.services.afc") + [
    "pymobiledevice3.lockdown", "pymobiledevice3.usbmux", "pymobiledevice3.service_connection",
    "pymobiledevice3.pair_records", "apsw", "apsw.ext", "pillow_heif", "PIL.JpegImagePlugin",
]
datas = collect_data_files("pymobiledevice3", includes=["**/*.json", "**/*.plist", "**/*.txt"])
import os
datas += [(f, ".") for f in ("LICENSE", "ARTWORK-LICENSE.md") if os.path.exists(f)]
# artwork: only the packed, scrambled file (made by tools/pack_art.py); a build without it gets the plain look
if os.path.exists("assets/art.pak"):
    datas += [("assets/art.pak", "assets")]
ICON = "assets/app.ico" if os.path.exists("assets/app.ico") else None

a = Analysis(
    ["run_gui.py"],
    pathex=["."],
    hiddenimports=hidden,
    datas=datas,
    excludes=["tkinter", "matplotlib", "IPython", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="iPhoneTransfer",
          console=False, upx=False, icon=ICON, version="version_info.txt")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="iPhoneTransfer")
