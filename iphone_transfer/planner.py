"""Turn a selection of assets into a list of copy jobs (pure logic, no device I/O).

Naming:   <YYYYMMDD>_<HH-MM-SS>_<File name>      e.g. 20261108_12-26-00_IMG_1234.HEIC
By month: <dest>\\<YYYY Mon>\\<new name>   (default; see FOLDER_STYLES / FILE_STYLES)
By album: <dest>\\<Album>\\<new name>
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .library import Album, Asset

DATE_ADDED = "added"
DATE_TAKEN = "taken"

KIND_ORIGINAL = "original"
KIND_EDITED = "edited"      # src is the Adjustments folder; resolved at copy time
KIND_LIVE = "live"          # src is the paired .MOV; may not exist


@dataclass
class CopyJob:
    src: str                 # path on the phone (or folder for KIND_EDITED)
    dest: Path
    size: int                # expected size in bytes (0 = unknown)
    when: Optional[dt.datetime]
    kind: str = KIND_ORIGINAL
    asset_pk: int = 0
    label: str = ""          # original phone file name, for reports
    is_video: bool = False
    live: bool = False


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_component(name: str, fallback: str = "Untitled") -> str:
    name = name.replace("/", "-").replace("\\", "-")
    name = _ILLEGAL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = fallback
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name[:120]


def asset_date(a: Asset, source: str) -> Optional[dt.datetime]:
    if source == DATE_TAKEN:
        return a.taken or a.added
    return a.added or a.taken


# File name styles
FILE_DATETIME = "datetime"     # 20261109_04-54-05_IMG_1234.HEIC
FILE_DATE = "date"             # 20261109_IMG_1234.HEIC
FILE_ORIGINAL = "original"     # IMG_1234.HEIC
FILE_STYLES = (FILE_DATETIME, FILE_DATE, FILE_ORIGINAL)

# Year-Month folder styles
FOLDER_YEAR_MON = "year_mon"           # 2026 Nov
FOLDER_YEAR_MM = "year_mm"             # 2026-11
FOLDER_STYLES = (FOLDER_YEAR_MON, FOLDER_YEAR_MM)


def date_prefix(when: Optional[dt.datetime], style: str = FILE_DATETIME) -> str:
    if style == FILE_ORIGINAL:
        return ""
    if style == FILE_DATE:
        return "00000000" if when is None else when.strftime("%Y%m%d")
    if when is None:
        return "00000000_00-00-00"
    return when.strftime("%Y%m%d_%H-%M-%S")


MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_folder(when: Optional[dt.datetime], style: str = FOLDER_YEAR_MON) -> str:
    """Folder name for a month, e.g. "2026 Nov" or "2026-11"."""
    if when is None:
        return "Unknown date"
    mon = MONTH_ABBR[when.month - 1]                       # English, whatever the PC language
    if style == FOLDER_YEAR_MM:
        return f"{when:%Y-%m}"
    return f"{when:%Y} {mon}"                              # e.g. "2026 Nov"


# Camera-style names that are kept as they are: IMG_1234, DSCF0564, IMG_1687_Original, PXL_20240101_123456
_CAMERA_NAME = re.compile(r"^[A-Z]{2,6}_?\d{3,}(_\d+)*(_[A-Za-z]+)?$")


def is_camera_name(stem: str) -> bool:
    return bool(_CAMERA_NAME.match(stem))


def display_name(a: Asset, tidy: bool = False) -> str:
    """'File name' part. tidy=True replaces app/web names (e.g. '@user - Download.JPG',
    '434436880_..._n.JPG') with IMG_<phone ID>, which is unique and stable between runs."""
    name = a.display_name
    if tidy:
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        if not is_camera_name(stem):
            return f"IMG_{a.pk}.{ext}" if ext else f"IMG_{a.pk}"
    return name


def new_name(a: Asset, when: Optional[dt.datetime], suffix: str = "", ext: Optional[str] = None,
             tidy: bool = False, style: str = FILE_DATETIME) -> str:
    name = display_name(a, tidy)
    stem, _, orig_ext = name.rpartition(".")
    if not stem:
        stem, orig_ext = name, ""
    ext = orig_ext if ext is None else ext
    stem = safe_component(stem, a.stem)
    prefix = date_prefix(when, style)
    name = f"{prefix}_{stem}{suffix}" if prefix else f"{stem}{suffix}"
    return f"{name}.{ext}" if ext else name


def album_folder_names(albums: list[Album]) -> dict[int, str]:
    """Folder name per album; duplicate titles get their parent folder as prefix."""
    base = {a.pk: safe_component(a.title) for a in albums}
    counts: dict[str, int] = {}
    for n in base.values():
        counts[n.lower()] = counts.get(n.lower(), 0) + 1
    out: dict[int, str] = {}
    used: set[str] = set()
    for a in albums:
        n = base[a.pk]
        if counts[n.lower()] > 1 and a.folder:
            n = safe_component(f"{a.folder.replace(' / ', ' - ')} - {a.title}")
        cand, i = n, 2
        while cand.lower() in used:
            cand = f"{n} ({i})"
            i += 1
        used.add(cand.lower())
        out[a.pk] = cand
    return out


def _jobs_for_asset(a: Asset, folder: Path, source: str, edited: bool, live: bool,
                    tidy: bool = False, style: str = FILE_DATETIME) -> list[CopyJob]:
    when = asset_date(a, source)
    jobs = [CopyJob(a.device_path, folder / new_name(a, when, tidy=tidy, style=style), a.size, when, KIND_ORIGINAL,
                    a.pk, a.filename)]
    if live and a.live and not a.is_video:
        jobs.append(CopyJob(f"/{a.directory}/{a.stem}.MOV", folder / new_name(a, when, ext="MOV", tidy=tidy, style=style),
                            0, when, KIND_LIVE, a.pk, a.filename))
    if edited and a.edited:
        # e.g. /PhotoData/Mutations/DCIM/286APPLE/IMG_6401/Adjustments/FullSizeRender.jpg
        # dest is a template; the copier fills in the real extension(s).
        jobs.append(CopyJob(f"/PhotoData/Mutations/{a.directory}/{a.stem}/Adjustments",
                            folder / new_name(a, when, suffix="_edited", ext="{ext}", tidy=tidy, style=style),
                            0, when, KIND_EDITED, a.pk, a.filename, a.is_video, a.live))
    return jobs


def _dedupe(jobs: list[CopyJob]) -> list[CopyJob]:
    """Two different phone files must never map to the same destination file."""
    seen: dict[str, str] = {}
    out = []
    for j in jobs:
        key = str(j.dest).lower()
        src = j.src
        if key in seen and seen[key] != src:
            stem, dot, ext = j.dest.name.rpartition(".")
            if not dot:
                stem, ext = j.dest.name, ""
            i = 2
            while True:
                cand = j.dest.with_name(f"{stem}_{i}.{ext}" if ext else f"{stem}_{i}")
                if str(cand).lower() not in seen:
                    break
                i += 1
            j.dest = cand
            key = str(cand).lower()
        if key in seen:      # exact same src+dest twice: drop
            continue
        seen[key] = src
        out.append(j)
    return out


def plan_by_month(assets: Iterable[Asset], dest_root: Path, source: str = DATE_ADDED,
                  edited: bool = True, live: bool = True,
                  date_from: Optional[dt.date] = None, date_to: Optional[dt.date] = None,
                  tidy: bool = False, keep: Optional[Callable[[Asset], bool]] = None,
                  folder_style: str = FOLDER_YEAR_MON, file_style: str = FILE_DATETIME) -> list[CopyJob]:
    jobs: list[CopyJob] = []
    if keep:
        assets = [a for a in assets if keep(a)]
    for a in sorted(assets, key=lambda x: (asset_date(x, source) or dt.datetime.min, x.pk)):
        when = asset_date(a, source)
        if when is not None:
            if date_from and when.date() < date_from:
                continue
            if date_to and when.date() > date_to:
                continue
        jobs += _jobs_for_asset(a, dest_root / month_folder(when, folder_style), source, edited, live, tidy,
                                file_style)
    return _dedupe(jobs)


def plan_by_album(albums: list[Album], assets: dict[int, Asset], dest_root: Path,
                  source: str = DATE_ADDED, edited: bool = True, live: bool = True,
                  tidy: bool = False, keep: Optional[Callable[[Asset], bool]] = None,
                  file_style: str = FILE_DATETIME) -> list[CopyJob]:
    names = album_folder_names(albums)
    jobs: list[CopyJob] = []
    for al in albums:
        folder = dest_root / names[al.pk]
        members = [assets[pk] for pk in al.asset_pks if pk in assets and (keep is None or keep(assets[pk]))]
        for a in sorted(members, key=lambda x: (asset_date(x, source) or dt.datetime.min, x.pk)):
            jobs += _jobs_for_asset(a, folder, source, edited, live, tidy, file_style)
    return _dedupe(jobs)
