import sys

from iphone_transfer import logging_setup


def selftest() -> int:
    """iPhoneTransfer.exe --selftest : checks the bundled libraries work (for releases / CI)."""
    import logging
    import tempfile
    from pathlib import Path
    log = logging.getLogger("selftest")
    try:
        import apsw  # noqa: F401
        import pillow_heif
        from PIL import Image
        from pymobiledevice3 import usbmux  # noqa: F401
        from iphone_transfer import gui  # noqa: F401
        from iphone_transfer.convert import heic_to_jpg
        pillow_heif.register_heif_opener()
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "t.HEIC"
            Image.new("RGB", (32, 32), (10, 132, 255)).save(src, format="HEIF")
            heic_to_jpg(src, Path(d) / "t.JPG")
            assert (Path(d) / "t.JPG").stat().st_size > 0
        log.info("SELFTEST OK")
        return 0
    except Exception:
        log.exception("SELFTEST FAILED")
        return 1


def main() -> int:
    logging_setup.setup()
    if "--selftest" in sys.argv:
        return selftest()
    from iphone_transfer.gui import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
