"""Thin line icons drawn from small inline SVGs (24x24, 1.6 px stroke)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M11 18.5h2"/>',
    "photos": '<rect x="3" y="5" width="18" height="14" rx="2.2"/><circle cx="8.5" cy="10" r="1.6"/>'
              '<path d="M21 15.5l-5-5L5 19"/>',
    "pulse": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .9-1 1.6v.3"/>'
            '<path d="M12 16.8v.2"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.3l2.7 2.7L16 9.7"/>',
    "warn": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.2"/><path d="M12 17v.2"/>',
    "fail": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "wait": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    "skip": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "plug": '<path d="M9 3v5M15 3v5"/><path d="M6.5 8h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5V21"/>',
    "folder": '<path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "checks": '<path d="M3 12.5l3.5 3.5L13 9.5"/><path d="M11 15.5l1 1 8.5-8.5"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "speed": '<path d="M4.5 17a8.5 8.5 0 1 1 15 0"/><path d="M12 13l4-4.5"/><circle cx="12" cy="13.5" r="1.2"/>',
    "arrow": '<path d="M12 4v12M6.5 10.5L12 16l5.5-5.5"/><path d="M5 20h14"/>',
}


def svg(name: str, color: str) -> bytes:
    body = _PATHS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, color: str, size: int, dpr: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color)))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str, selected_color: str | None = None, size: int = 20) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal)
    if selected_color:
        ic.addPixmap(pixmap(name, selected_color, size), QIcon.Selected)
    return ic
