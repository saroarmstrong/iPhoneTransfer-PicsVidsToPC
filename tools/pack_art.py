"""Pack the artwork into assets/art.pak (run by build.bat when the artwork folders are present).

assets/ui/**, assets/background.jpg, assets/app.ico and assets/app.png are compiled into one Qt resource
(prefix /art) and scrambled. The pack is not part of the open-source code: see ARTWORK-LICENSE.md.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from iphone_transfer.art import scramble  # noqa: E402

ASSETS = ROOT / "assets"
FILES = ["background.jpg", "app.ico", "app.png"]


def main() -> int:
    if not (ASSETS / "ui" / "skin").is_dir():
        print("pack_art: no artwork folder (assets/ui/skin) - building without artwork")
        return 0
    rels = [f for f in FILES if (ASSETS / f).exists()]
    rels += sorted(p.relative_to(ASSETS).as_posix() for p in (ASSETS / "ui").rglob("*.png"))
    with tempfile.TemporaryDirectory() as tmp:
        qrc = Path(tmp) / "art.qrc"
        lines = ['<RCC>', '  <qresource prefix="/art">']
        lines += [f'    <file alias="{r}">{(ASSETS / r).as_posix()}</file>' for r in rels]
        lines += ['  </qresource>', '</RCC>']
        qrc.write_text("\n".join(lines), encoding="utf-8")
        out = Path(tmp) / "art.rcc"
        rcc = Path(sys.executable).parent / "pyside6-rcc.exe"
        cmd = [str(rcc) if rcc.exists() else "pyside6-rcc", "--binary", str(qrc), "-o", str(out)]
        subprocess.run(cmd, check=True)
        data = out.read_bytes()
    (ASSETS / "art.pak").write_bytes(scramble(data))
    print(f"pack_art: {len(rels)} files -> assets/art.pak ({len(data) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
