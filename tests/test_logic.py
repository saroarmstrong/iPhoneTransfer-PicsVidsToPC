import datetime as dt
import sqlite3
import tempfile
from pathlib import Path

from iphone_transfer.library import Album, Asset, pick_display_name, taken_time, apple_time_local
from iphone_transfer.planner import (DATE_ADDED, DATE_TAKEN, KIND_EDITED, KIND_LIVE, album_folder_names,
                                     plan_by_album, plan_by_month, safe_component)
from iphone_transfer.remote_sqlite import RemoteDB, parse_wal


def A(pk, fn="IMG_0001.HEIC", added=dt.datetime(2026, 11, 8, 12, 26, 0), taken=dt.datetime(2022, 5, 1, 9, 0, 0),
      d="DCIM/100APPLE", disp=None, **kw):
    base = dict(is_video=False, size=100, edited=False, live=False, favorite=False, screenshot=False,
                hidden=False, in_library=True)
    base.update(kw)
    return Asset(pk, d, fn, disp or fn, added=added, taken=taken, **base)


def test_name_and_month_use_date_added():
    jobs = plan_by_month([A(1)], Path("D:/P"), DATE_ADDED, edited=False, live=False)
    assert [str(j.dest) for j in jobs] == [str(Path("D:/P/2026 Nov/20261108_12-26-00_IMG_0001.HEIC"))]


def test_exif_mode():
    jobs = plan_by_month([A(1)], Path("D:/P"), DATE_TAKEN, edited=False, live=False)
    assert jobs[0].dest == Path("D:/P/2022 May/20220501_09-00-00_IMG_0001.HEIC")


def test_extras():
    jobs = plan_by_month([A(1, edited=True, live=True)], Path("D:/P"))
    kinds = {j.kind: j for j in jobs}
    assert kinds[KIND_LIVE].src == "/DCIM/100APPLE/IMG_0001.MOV"
    assert kinds[KIND_LIVE].dest.name == "20261108_12-26-00_IMG_0001.MOV"
    assert kinds[KIND_EDITED].src == "/PhotoData/Mutations/DCIM/100APPLE/IMG_0001/Adjustments"
    assert kinds[KIND_EDITED].dest.name == "20261108_12-26-00_IMG_0001_edited.{ext}"


def test_collision_gets_suffix():
    jobs = plan_by_month([A(1, d="DCIM/100APPLE"), A(2, d="DCIM/105APPLE")], Path("D:/P"), edited=False, live=False)
    names = sorted(j.dest.name for j in jobs)
    assert names == ["20261108_12-26-00_IMG_0001.HEIC", "20261108_12-26-00_IMG_0001_2.HEIC"]


def test_album_mode_flat_and_duplicate_titles():
    assets = {1: A(1), 2: A(2, fn="IMG_0002.HEIC")}
    albums = [Album(10, "2024/01", "user", "", [1]), Album(11, "Quick ref.", "user", "HA GOPC", [2]),
              Album(12, "Quick ref.", "user", "HA TMH", [1])]
    names = album_folder_names(albums)
    assert names == {10: "2024-01", 11: "HA GOPC - Quick ref", 12: "HA TMH - Quick ref"}
    jobs = plan_by_album(albums, assets, Path("D:/A"), edited=False, live=False)
    assert jobs[0].dest == Path("D:/A/2024-01/20261108_12-26-00_IMG_0001.HEIC")
    assert len(jobs) == 3   # same photo in two albums -> copied into both


def test_uuid_names_use_original_name():
    assert pick_display_name("9AB6A72C-E00F-49A3-AC04-EEF620948040.JPG", "IMG_0042.HEIC") == "IMG_0042.JPG"
    assert pick_display_name("9AB6A72C-E00F-49A3-AC04-EEF620948040.JPG", "\n\npuffpoy\n\n.jpeg") == "puffpoy.JPG"
    assert pick_display_name("9AB6A72C-E00F-49A3-AC04-EEF620948040.JPG", None) == "9AB6A72C-E00F-49A3-AC04-EEF620948040.JPG"
    assert pick_display_name("IMG_6413.JPEG", "weird.jpeg") == "IMG_6413.JPEG"


def test_safe_component():
    assert safe_component("a/b:c*?") == "a-bc"
    assert safe_component("CON") == "_CON"
    assert safe_component("  ") == "Untitled"


def test_dates():
    assert taken_time("2026:11:08 10:39:13", None, None) == dt.datetime(2026, 11, 8, 10, 39, 13)
    assert taken_time(None, 0, 28800) == dt.datetime(2001, 1, 1, 8, 0, 0)
    assert apple_time_local(None) is None


def test_remote_db_with_wal_matches_sqlite():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.sqlite"
        c = sqlite3.connect(p)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute("CREATE TABLE t(x INTEGER PRIMARY KEY, y TEXT)")
        c.executemany("INSERT INTO t(y) VALUES (?)", [("a" * 200,)] * 3000)
        c.commit()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.executemany("INSERT INTO t(y) VALUES (?)", [("b" * 200,)] * 500)   # stays in WAL
        c.commit()
        main = p.read_bytes()
        wal = Path(str(p) + "-wal").read_bytes()
        pages, _, ps = parse_wal(wal)
        assert pages and ps == 4096

        def read_many(reqs):
            return [main[o:o + s] for o, s in reqs]

        db = RemoteDB("unit", len(main), read_many, wal)
        conn = db.connect()
        root = [r for (r,) in conn.execute("SELECT rootpage FROM sqlite_master WHERE name='t'")]
        db.prefetch_btrees(root)
        assert list(conn.execute("SELECT count(*), sum(y LIKE 'b%') FROM t")) == [(3500, 500)]
        conn.close()
        db.close()
        c.close()


def test_buddhist_year_exif():
    from iphone_transfer.library import taken_time
    assert taken_time("2568:04:01 03:31:46", None, None) == dt.datetime(2025, 4, 1, 3, 31, 46)
    assert taken_time("2024:08:15 14:30:22", None, None) == dt.datetime(2024, 8, 15, 14, 30, 22)


def test_set_created_time(tmp_path):
    import os
    from iphone_transfer.copier import set_created_time
    f = tmp_path / "x.jpg"; f.write_bytes(b"x")
    ts = dt.datetime(2026, 11, 8, 14, 3, 18).timestamp()
    set_created_time(f, ts)
    assert abs(os.stat(f).st_birthtime - ts) < 1 if hasattr(os.stat(f), "st_birthtime") else abs(os.stat(f).st_ctime - ts) < 1


def test_tidy_names():
    from iphone_transfer.planner import display_name, is_camera_name
    for keep in ["IMG_1234", "DSCF0564", "IMG_1687_Original", "PXL_20240101_123456", "IMG_E6454"[:0] or "IMG_6454"]:
        assert is_camera_name(keep), keep
    for odd in ["@srchafreen - R⤓Download", "434436880_1113953672983829_2528011784145695882_n",
                "-7808774554935768908", "8400532291273327160", "PHOTO-2021-10-30-14-55-09",
                "srchafreen 2023-12-16T162806", "RPReplay_Final1726236085"]:
        assert not is_camera_name(odd), odd
    a = Asset(392633, "PhotoData/CPLAssets/group1", "X.JPG", "@user - R⤓Download.JPG", False,
              None, None, 1, False, False, False, False, False, True)
    assert display_name(a) == "@user - R⤓Download.JPG"
    assert display_name(a, tidy=True) == "IMG_392633.JPG"
    b = Asset(5, "DCIM/100APPLE", "IMG_6454.JPG", "IMG_6454.JPG", False,
              None, None, 1, False, False, False, False, False, True)
    assert display_name(b, tidy=True) == "IMG_6454.JPG"


def test_all_modules_import():
    """Catches syntax errors before PyInstaller silently drops a module."""
    import importlib
    for m in ["gui", "copier", "device", "service", "planner", "library", "remote_sqlite", "logging_setup", "doctor", "theme", "help_content", "winutil", "convert"]:
        importlib.import_module(f"iphone_transfer.{m}")


def test_keep_filter_and_media():
    from iphone_transfer.planner import plan_by_month
    mk = lambda pk, vid, day: Asset(pk, "DCIM/100APPLE", f"IMG_{pk}.{'MOV' if vid else 'HEIC'}",
                                    f"IMG_{pk}.{'MOV' if vid else 'HEIC'}", vid, dt.datetime(2026, 11, day),
                                    None, 10, False, False, False, False, False, True)
    items = [mk(1, False, 1), mk(2, True, 2), mk(3, False, 5)]
    after = dt.datetime(2026, 11, 3)
    jobs = plan_by_month(items, Path("C:/x"), keep=lambda a: not a.is_video and a.added > after)
    assert [j.asset_pk for j in jobs] == [3]


def test_explain_errors():
    from iphone_transfer.doctor import explain_connect_error
    class PasswordRequiredError(Exception): pass
    class UserDeniedPairingError(Exception): pass
    assert "locked" in explain_connect_error(PasswordRequiredError())[0]
    assert "Don't Trust" in explain_connect_error(UserDeniedPairingError())[0]
    assert "not reachable" in explain_connect_error(ConnectionRefusedError())[0]


def test_heic_to_jpg(tmp_path):
    import pillow_heif
    from PIL import Image
    from iphone_transfer.convert import heic_to_jpg
    pillow_heif.register_heif_opener()
    src = tmp_path / "a.HEIC"
    Image.new("RGB", (64, 48), (200, 30, 30)).save(src, format="HEIF")
    heic_to_jpg(src, tmp_path / "a.JPG")
    assert not src.exists()
    with Image.open(tmp_path / "a.JPG") as im:
        assert im.format == "JPEG" and im.size == (64, 48)


def test_folder_and_file_name_styles():
    import datetime as dt
    from iphone_transfer import planner as p
    when = dt.datetime(2026, 11, 9, 4, 54, 5)
    assert p.month_folder(when, p.FOLDER_YEAR_MON) == "2026 Nov"
    assert p.month_folder(when, p.FOLDER_YEAR_MM) == "2026-11"
    assert p.date_prefix(when, p.FILE_DATETIME) == "20261109_04-54-05"
    assert p.date_prefix(when, p.FILE_DATE) == "20261109"
    assert p.date_prefix(when, p.FILE_ORIGINAL) == ""
