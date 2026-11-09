"""Read the iPhone Photos library (Photos.sqlite) into plain Python objects.

Schema notes (verified on iOS 18.6.2):
  ZASSET                      one row per photo/video
    ZDIRECTORY / ZFILENAME    file location under /var/mobile/Media
                              ("DCIM/286APPLE" or "PhotoData/CPLAssets/group12")
    ZADDEDDATE                when the item was added to this library (Core Data time, UTC)
    ZDATECREATED              capture date (UTC)
    ZKIND                     0 photo, 1 video
    ZPLAYBACKSTYLE            3 = Live Photo
    ZADJUSTMENTSSTATE         > 0 = edited in Photos
    ZTRASHEDSTATE/ZHIDDEN/ZVISIBILITYSTATE  filters
  ZADDITIONALASSETATTRIBUTES  ZORIGINALFILENAME, ZORIGINALFILESIZE,
                              ZEXIFTIMESTAMPSTRING ('YYYY:MM:DD HH:MM:SS'), ZTIMEZONEOFFSET
  ZGENERICALBUM               albums (ZKIND 2 = user album, 4000 = folder, 1505 = shared album)
  Z_<n>ASSETS                 album <-> asset join table; the number changes between iOS
                              versions so it is discovered at runtime.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import apsw

log = logging.getLogger(__name__)

APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
UUID_NAME = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\.", re.ASCII)

ALBUM_USER = 2
ALBUM_SHARED = 1505
ALBUM_FOLDER = 4000


@dataclass
class Asset:
    pk: int
    directory: str
    filename: str            # name of the file on the phone
    display_name: str        # name used in the renamed file (IMG_1234.HEIC)
    is_video: bool
    added: Optional[dt.datetime]       # local naive time
    taken: Optional[dt.datetime]       # local naive time at the place it was taken
    size: int                # bytes, from the database (estimate)
    edited: bool
    live: bool
    favorite: bool
    screenshot: bool
    hidden: bool
    in_library: bool         # part of the main library (not shared-album only, not hidden)

    @property
    def device_path(self) -> str:
        return f"/{self.directory}/{self.filename}"

    @property
    def stem(self) -> str:
        return self.filename.rsplit(".", 1)[0]


@dataclass
class Album:
    pk: int
    title: str
    kind: str                # "user", "shared", "smart"
    folder: str = ""         # "Parent / Sub" path of containing folders
    asset_pks: list[int] = field(default_factory=list)


@dataclass
class Library:
    assets: dict[int, Asset]
    albums: list[Album]

    def library_assets(self) -> list[Asset]:
        return [a for a in self.assets.values() if a.in_library]


# --------------------------------------------------------------------- helpers
def apple_time_local(value) -> Optional[dt.datetime]:
    if value is None:
        return None
    try:
        return (APPLE_EPOCH + dt.timedelta(seconds=float(value))).astimezone().replace(tzinfo=None)
    except (OverflowError, ValueError, OSError):
        return None


def taken_time(exif: Optional[str], created, tz_offset) -> Optional[dt.datetime]:
    if exif:
        try:
            t = dt.datetime.strptime(exif.strip()[:19], "%Y:%m:%d %H:%M:%S")
            # Phones set to the Thai Buddhist calendar write EXIF years +543 (2568 = 2025).
            if t.year > dt.date.today().year + 1 and t.year - 543 >= 1900:
                t = t.replace(year=t.year - 543)
            return t
        except ValueError:
            pass
    if created is not None:
        try:
            base = APPLE_EPOCH + dt.timedelta(seconds=float(created))
            if tz_offset is not None:
                return (base + dt.timedelta(seconds=int(tz_offset))).replace(tzinfo=None)
            return base.astimezone().replace(tzinfo=None)
        except (OverflowError, ValueError, OSError):
            return None
    return None


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_name(name: str) -> str:
    name = _BAD.sub("", name or "").strip().strip(".")
    return name


def pick_display_name(filename: str, original: Optional[str]) -> str:
    """The 'File name' part of the new name.

    DCIM files already have camera-style names (IMG_1234.HEIC). Items downloaded
    from iCloud are stored with UUID names, so for those use the original name,
    keeping the real extension of the stored file.
    """
    if UUID_NAME.match(filename):
        ext = filename.rsplit(".", 1)[-1]
        orig = clean_name(original or "")
        if orig:
            stem = orig.rsplit(".", 1)[0] if "." in orig else orig
            stem = clean_name(stem)
            if stem:
                return f"{stem}.{ext}"
    return filename


def _columns(conn: apsw.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _find_album_join(conn: apsw.Connection) -> Optional[tuple[str, str, str]]:
    """Find (table, album_col, asset_col) of the album<->asset join table."""
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if not re.fullmatch(r"Z_\d+ASSETS", name):
            continue
        cols = _columns(conn, name)
        album_col = next((c for c in cols if re.fullmatch(r"Z_\d+ALBUMS", c)), None)
        asset_col = next((c for c in cols if re.fullmatch(r"Z_\d+ASSETS", c)), None)
        if album_col and asset_col:
            return name, album_col, asset_col
    return None


# ------------------------------------------------------------------------ load
def load_library(conn: apsw.Connection, progress=None, prefetch=None) -> Library:
    """prefetch(list_of_root_pages) is called (if given) before the big scans."""
    def step(msg):
        log.info(msg)
        if progress:
            progress(msg)

    acols = _columns(conn, "ZASSET")
    xcols = _columns(conn, "ZADDITIONALASSETATTRIBUTES")
    join = _find_album_join(conn)

    if prefetch:
        wanted = {"ZASSET", "ZADDITIONALASSETATTRIBUTES", "ZGENERICALBUM"}
        if join:
            wanted.add(join[0])
        roots = [r for (n, r) in conn.execute(
            "SELECT name, rootpage FROM sqlite_master WHERE type='table'") if n in wanted]
        step("Reading Photos library from iPhone…")
        prefetch(roots)

    def col(cols, name, default="NULL"):
        return name if name in cols else default

    step("Reading photo list…")
    # Two plain table scans joined in Python: an SQL join would walk an index
    # with one random page read per photo.
    extra: dict[int, tuple] = {}
    for row in conn.execute(f"""
            SELECT ZASSET, {col(xcols, 'ZORIGINALFILENAME')}, {col(xcols, 'ZORIGINALFILESIZE', '0')},
                   {col(xcols, 'ZEXIFTIMESTAMPSTRING')}, {col(xcols, 'ZTIMEZONEOFFSET')}
            FROM ZADDITIONALASSETATTRIBUTES NOT INDEXED"""):
        extra[row[0]] = row[1:]

    sql = f"""
        SELECT Z_PK, ZDIRECTORY, ZFILENAME, ZKIND, ZADDEDDATE, ZDATECREATED,
               {col(acols, 'ZADJUSTMENTSSTATE', '0')}, {col(acols, 'ZPLAYBACKSTYLE', '0')},
               {col(acols, 'ZFAVORITE', '0')}, {col(acols, 'ZISDETECTEDSCREENSHOT', '0')},
               {col(acols, 'ZHIDDEN', '0')}, {col(acols, 'ZVISIBILITYSTATE', '0')},
               {col(acols, 'ZKINDSUBTYPE', '0')}, ZTRASHEDSTATE
        FROM ZASSET NOT INDEXED
    """
    assets: dict[int, Asset] = {}
    for (pk, d, fn, kind, added, created, adj, playback, fav, shot, hidden, vis, subtype,
         trashed) in conn.execute(sql):
        if trashed or not fn or not d:
            continue
        orig, size, exif, tzoff = extra.get(pk, (None, 0, None, None))
        shared = d.startswith("PhotoData/PhotoCloudSharingData")
        assets[pk] = Asset(
            pk=pk,
            directory=d,
            filename=fn,
            display_name=pick_display_name(fn, orig),
            is_video=(kind == 1),
            added=apple_time_local(added),
            taken=taken_time(exif, created, tzoff),
            size=int(size or 0),
            edited=bool(adj),
            live=(playback == 3 or subtype == 2),
            favorite=bool(fav),
            screenshot=bool(shot) or subtype == 10,
            hidden=bool(hidden),
            in_library=(not shared and not hidden and (vis or 0) == 0),
        )
    step(f"Found {len(assets):,} items. Reading albums…")

    gcols = _columns(conn, "ZGENERICALBUM")
    parent_col = "ZPARENTFOLDER" if "ZPARENTFOLDER" in gcols else "NULL"
    rows = list(conn.execute(
        f"SELECT Z_PK, ZKIND, ZTITLE, {parent_col} FROM ZGENERICALBUM NOT INDEXED "
        f"WHERE ZTRASHEDSTATE = 0 AND ZKIND IN ({ALBUM_USER}, {ALBUM_SHARED}, {ALBUM_FOLDER}, 3999)"))
    info = {pk: (kind, title, parent) for pk, kind, title, parent in rows}

    def folder_path(parent) -> str:
        parts = []
        seen = set()
        while parent in info and parent not in seen:
            seen.add(parent)
            kind, title, nxt = info[parent]
            if kind == ALBUM_FOLDER and title:
                parts.append(title)
            parent = nxt
        return " / ".join(reversed(parts))

    members: dict[int, list[int]] = {}
    if join:
        table, album_col, asset_col = join
        for album_pk, asset_pk in conn.execute(f"SELECT {album_col}, {asset_col} FROM {table} NOT INDEXED"):
            if asset_pk in assets:
                members.setdefault(album_pk, []).append(asset_pk)
    else:
        log.warning("album join table not found")

    albums: list[Album] = []
    for pk, (kind, title, parent) in info.items():
        if kind not in (ALBUM_USER, ALBUM_SHARED):
            continue
        albums.append(Album(
            pk=pk,
            title=title or "Untitled",
            kind="user" if kind == ALBUM_USER else "shared",
            folder=folder_path(parent),
            asset_pks=members.get(pk, []),
        ))
    albums.sort(key=lambda a: (a.kind != "user", a.folder.lower(), a.title.lower()))

    lib_assets = [a for a in assets.values() if a.in_library]
    smart = [
        Album(-1, "Favorites", "smart", asset_pks=[a.pk for a in lib_assets if a.favorite]),
        Album(-2, "Videos", "smart", asset_pks=[a.pk for a in lib_assets if a.is_video]),
        Album(-3, "Screenshots", "smart", asset_pks=[a.pk for a in lib_assets if a.screenshot]),
        Album(-4, "Live Photos", "smart", asset_pks=[a.pk for a in lib_assets if a.live]),
        Album(-5, "Recently Edited", "smart", asset_pks=[a.pk for a in lib_assets if a.edited]),
        Album(-6, "Hidden", "smart", asset_pks=[a.pk for a in assets.values() if a.hidden]),
    ]
    now = dt.datetime.now()
    smart.insert(0, Album(-7, "Recently Added (30 days)", "smart",
                          asset_pks=[a.pk for a in lib_assets if a.added and (now - a.added).days < 30]))
    albums = [a for a in smart if a.asset_pks] + albums
    step(f"Found {len(assets):,} items and {len(albums):,} albums.")
    return Library(assets=assets, albums=albums)
