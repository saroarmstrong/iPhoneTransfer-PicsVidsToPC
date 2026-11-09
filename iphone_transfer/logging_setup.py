r"""Log to %LOCALAPPDATA%\iPhoneTransfer\logs (no console in the windowed exe)."""
import logging
import logging.handlers
import os
from pathlib import Path


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "iPhoneTransfer" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup() -> Path:
    path = log_dir() / "transfer.log"
    h = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for noisy in ("pymobiledevice3", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path
