"""PySide6 main window: sidebar with Connect / Transfer / Troubleshoot / Help."""
from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPixmapCache, QTextCharFormat)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QSpinBox, QStackedWidget, QStyle,
    QStyledItemDelegate, QSystemTrayIcon, QTabWidget, QToolButton, QTextBrowser, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, GITHUB_URL, __version__, art, doctor, icons, theme, winutil
from .copier import CopyEngine, Progress
from .device import DeviceError, DeviceHub
from .help_content import help_html
from .library import Album, Asset, Library
from .planner import (DATE_ADDED, DATE_TAKEN, FILE_DATE, FILE_DATETIME, FILE_ORIGINAL, FOLDER_YEAR_MM,
                      FOLDER_YEAR_MON, CopyJob, asset_date, date_prefix,
                      month_folder, plan_by_album, plan_by_month)
from .service import read_library

log = logging.getLogger(__name__)

ROLE_KEY = Qt.UserRole + 1
PAGE_CONNECT, PAGE_COPY, PAGE_DOCTOR, PAGE_HELP = range(4)
MEDIA_ALL, MEDIA_PHOTOS, MEDIA_VIDEOS = "all", "photos", "videos"
RESUME_WAIT_MIN = 15

MODELS = {
    "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max", "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus", "iPhone17,5": "iPhone 16e",
    "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max", "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus", "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone14,7": "iPhone 14", "iPhone14,8": "iPhone 14 Plus", "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max", "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13",
    "iPhone14,6": "iPhone SE (3rd gen)", "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max", "iPhone12,1": "iPhone 11",
    "iPhone12,3": "iPhone 11 Pro", "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE (2nd gen)",
    "iPhone11,8": "iPhone XR", "iPhone11,2": "iPhone XS", "iPhone11,6": "iPhone XS Max",
}


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit in ("B", "KB") else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec: Optional[float]) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(8)
    return f, lay


def label(text: str = "", obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    lb.setOpenExternalLinks(True)
    return lb


def page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    w.setObjectName("page")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(26, 20, 26, 18)
    lay.setSpacing(12)
    return w, lay


def skin_card(obj: str, margins=(6, 2, 6, 2), spacing: int = 8) -> tuple[QFrame, QHBoxLayout]:
    """A QFrame painted by a Set 3 border-image (cardStatus / cardSpeed / cardDaterange / cardDevice)."""
    f = QFrame()
    f.setObjectName(obj)
    lay = QHBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def icon_label(name: str, size: int = 22) -> QLabel:
    lb = QLabel()
    lb.setPixmap(icons.pixmap(name, "#1C242D", size))
    lb.setFixedSize(size + 2, size + 2)
    lb.setStyleSheet("background: transparent;")
    return lb


INK_C = QColor(28, 36, 45)
WHITE_C = QColor(255, 255, 255)


def paint_frost(p: QPainter, widget: QWidget, rect: QRect, radius: float) -> bool:
    """Frosted glass like the mockup: the blurred painting shows through, with a light veil on light areas and a
    dark veil on dark areas. Returns True when the area is dark (use white text), False for ink text."""
    win = widget.window()
    blur = win.frost_blur() if hasattr(win, "frost_blur") else None
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    dark = True
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if blur is not None and not blur.isNull():
        src = QRect(widget.mapTo(win, rect.topLeft()), rect.size())
        dark = win.bg_luma(src) < 0.58
        p.setClipPath(path)
        p.drawPixmap(rect, blur, src)
        p.setClipping(False)
    p.fillPath(path, QColor(24, 32, 42, 70) if dark else QColor(255, 255, 255, 120))
    p.setPen(QPen(QColor(255, 255, 255, 170 if dark else 220), 1.2))
    p.drawPath(path)
    p.restore()
    return dark


def paint_groove(p: QPainter, rect: QRect, frac: Optional[float], dark: bool) -> None:
    """Slim progress groove (mockup): recessed track with a white fill."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    r = rect.height() / 2
    p.setBrush(QColor(255, 255, 255, 70) if dark else QColor(45, 58, 72, 120))
    p.drawRoundedRect(QRectF(rect), r, r)
    if frac:
        w = max(rect.height(), round(rect.width() * min(1.0, frac)))
        p.setBrush(QColor(255, 255, 255, 255))
        p.drawRoundedRect(QRectF(rect.x(), rect.y(), w, rect.height()), r, r)
    p.restore()


class FrostCard(QFrame):
    """A frosted card; labels inside switch between white and ink text to stay readable."""

    def __init__(self, radius: int = 16) -> None:
        super().__init__()
        self.radius = radius
        self.dark = True
        self._applied = None

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        f = getattr(self.window(), "root", None)
        f = f.f if f is not None else 1.0
        self.dark = paint_frost(p, self, self.rect(), self.radius * f)
        p.end()
        if self._applied != self.dark:
            self._applied = self.dark
            self.setProperty("dark", self.dark)
            for w in self.findChildren(QWidget):
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()


class SlimBar(QProgressBar):
    """The mockup's thin progress groove instead of a chunky bar."""

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        span = max(1, self.maximum() - self.minimum())
        frac = (self.value() - self.minimum()) / span if self.maximum() > self.minimum() else None
        dark = getattr(self.parent(), "dark", False)
        paint_groove(p, self.rect(), frac, dark)
        p.end()


ROLE_PROG = Qt.UserRole + 2


class RowDelegate(QStyledItemDelegate):
    """Draws each month / album as a frosted card with a checkbox, name, count and a slim groove (mockup rows)."""

    def __init__(self, tree: QTreeWidget, info) -> None:
        super().__init__(tree)
        self.tree = tree
        self.info = info                      # item -> "666 items · 3.9 GB"
        self._box = {}

    def _f(self) -> float:
        root = getattr(self.tree.window(), "root", None)
        return root.f if root is not None else 1.0

    def _check_pix(self, state, size: int, dark: bool) -> QPixmap:
        name = {Qt.Checked: "checkbox_on", Qt.PartiallyChecked: "checkbox_partial"}.get(state, "checkbox_off")
        if dark:
            name += "_w"
        key = (name, size)
        if key not in self._box:
            pm = QPixmap(art.path(f"ui/{name}.png") or "")
            self._box[key] = pm.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._box[key].setDevicePixelRatio(2.0)
        return self._box[key]

    def sizeHint(self, opt, idx) -> QSize:
        f = self._f()
        group = idx.model().hasChildren(idx)
        return QSize(100, round((30 if group else 72) * f))

    def paint(self, p: QPainter, opt, idx) -> None:
        f = self._f()
        item = self.tree.itemFromIndex(idx)
        group = item.childCount() > 0
        r = opt.rect
        if group:                                   # year / folder: slim heading on its own frosted pill
            card = r.adjusted(0, round(4 * f), 0, -round(2 * f))
            dark = paint_frost(p, self.tree.viewport(), card, 10 * f)
        else:
            card = r.adjusted(0, round(4 * f), 0, -round(4 * f))
            dark = paint_frost(p, self.tree.viewport(), card, 16 * f)
        fg = WHITE_C if dark else INK_C
        sub = QColor(255, 255, 255, 215) if dark else QColor(52, 65, 78)
        pad = round(16 * f)
        bs = round((15 if group else 18) * f)
        top = card.top() + (card.height() - bs) // 2 if group else card.top() + round(13 * f)
        p.drawPixmap(card.left() + pad, top, self._check_pix(item.checkState(0), bs, dark))
        x = card.left() + pad + bs + round(12 * f)
        font = QFont(opt.font)
        font.setPointSizeF((10 if group else 13) * f)
        font.setWeight(QFont.DemiBold if group else QFont.Normal)
        p.setFont(font)
        p.setPen(fg)
        line = QRect(x, top - round(4 * f), card.right() - x - pad, bs + round(8 * f))
        p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter, item.text(0) + ("   ▾" if group and item.isExpanded()
                                                                         else "   ▸" if group else ""))
        font.setPointSizeF((8.5 if group else 9.5) * f)
        font.setWeight(QFont.Normal)
        p.setFont(font)
        p.setPen(sub)
        p.drawText(line, Qt.AlignRight | Qt.AlignVCenter, self.info(item))
        if not group:
            gh = max(3, round(6 * f))
            groove = QRect(card.left() + pad, card.bottom() - round(15 * f), card.width() - 2 * pad, gh)
            paint_groove(p, groove, item.data(0, ROLE_PROG) or 0.0, dark)

    def editorEvent(self, event, model, opt, idx) -> bool:
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            item = self.tree.itemFromIndex(idx)
            f = self._f()
            if item.childCount() and event.position().x() > opt.rect.left() + round(50 * f):
                item.setExpanded(not item.isExpanded())
                return True
            if item.flags() & Qt.ItemIsUserCheckable:
                new = Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
                model.setData(idx, new, Qt.CheckStateRole)
                return True
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            return True
        return False


def style_rows(tree: QTreeWidget, info) -> None:
    tree.setObjectName("rows")
    tree.setHeaderHidden(True)
    for c in range(1, tree.columnCount()):
        tree.setColumnHidden(c, True)
    tree.setIndentation(0)
    tree.setRootIsDecorated(False)
    tree.setSelectionMode(QTreeWidget.NoSelection)
    tree.setFocusPolicy(Qt.NoFocus)
    tree.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
    tree.setItemDelegate(RowDelegate(tree, info))
    tree.viewport().setAutoFillBackground(False)


CREDIT_TEXT = "Background art: AI-generated imagery of FreenBecky, created out of love and inspiration. Not affiliated with or endorsed by them."

BASE_W, BASE_H = 1200, 752          # design canvas = target mockup.jpg at 1200 px wide (16:10)
RATIO = BASE_W / BASE_H


class NiceDialog(QDialog):
    """The app's own pop-up: 96% pearl card over the app dimmed 28%; Set 3 start element for OK,
    watercolour side-panel button for Cancel."""

    def __init__(self, parent, title: str, text: str, ok: str = "OK", cancel: Optional[str] = None,
                 icon: str = "help", checkbox: Optional[str] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self._drag = None
        win = parent.window() if parent else None
        f = getattr(getattr(win, "root", None), "f", 1.0) or 1.0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("dlgCard")
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(round(22 * f), round(14 * f), round(22 * f), round(14 * f))
        v.setSpacing(round(9 * f))
        top = QHBoxLayout()
        top.setSpacing(round(10 * f))
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, "#1C242D", round(24 * f)))
        top.addWidget(ic)
        t = QLabel(title)
        t.setObjectName("dlgTitle")
        top.addWidget(t, 1)
        v.addLayout(top)
        body = QLabel(text if text.lstrip().startswith("<") else
                      __import__("html").escape(text).replace("\n", "<br>"))
        body.setObjectName("dlgBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(body)
        self.check = None
        if checkbox:
            self.check = QCheckBox(checkbox)
            v.addWidget(self.check)
        row = QHBoxLayout()
        row.addStretch(1)
        if cancel:
            cb = QPushButton(cancel)
            cb.setObjectName("dlgCancel")
            cb.setCursor(Qt.PointingHandCursor)
            cb.clicked.connect(self.reject)
            row.addWidget(cb)
        okb = QPushButton(ok)
        okb.setObjectName("dlgOk")
        okb.setCursor(Qt.PointingHandCursor)
        okb.setDefault(True)
        okb.clicked.connect(self.accept)
        row.addWidget(okb)
        v.addLayout(row)
        self.setFixedWidth(round(480 * f))
        self.adjustSize()
        if win:
            c = win.frameGeometry().center()
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)

    def checked(self) -> bool:
        return bool(self.check and self.check.isChecked())

    def exec(self) -> int:
        win = self.parentWidget().window() if self.parentWidget() else None
        shade = None
        if win is not None and win.isVisible():
            shade = QWidget(win)                      # dims the whole app while the pop-up is open
            shade.setAttribute(Qt.WA_StyledBackground)
            shade.setStyleSheet("background: rgba(0, 0, 0, 71);")
            shade.setGeometry(win.rect())
            shade.show()
            shade.raise_()
        try:
            return super().exec()
        finally:
            if shade is not None:
                shade.deleteLater()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None


def nice_info(parent, title: str, text: str, icon: str = "check") -> None:
    NiceDialog(parent, title, text, "OK", None, icon).exec()


def nice_warn(parent, title: str, text: str) -> None:
    NiceDialog(parent, title, text, "OK", None, "warn").exec()


def nice_ask(parent, title: str, text: str, ok: str = "Yes", cancel: str = "No", icon: str = "help") -> bool:
    return NiceDialog(parent, title, text, ok, cancel, icon).exec() == QDialog.Accepted


class PearlCalendar(QCalendarWidget):
    """Calendar pop-up: pearl card, thin pencil circle on the picked day, dashed ring on today."""

    def __init__(self):
        super().__init__()
        self.setObjectName("pearlCal")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setContentsMargins(14, 10, 14, 12)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setGridVisible(False)
        ink = QTextCharFormat()
        ink.setForeground(QColor("#1C242D"))
        for d in (Qt.Saturday, Qt.Sunday):
            self.setWeekdayTextFormat(d, ink)
        head = QTextCharFormat()
        head.setForeground(QColor("#6B7782"))
        head.setBackground(QBrush(Qt.transparent))
        self.setHeaderTextFormat(head)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Base, Qt.transparent)
        pal.setColor(pal.ColorRole.AlternateBase, Qt.transparent)
        self.setPalette(pal)

    def paintCell(self, p, rect, date) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        other = date.month() != self.monthShown()
        sel, today = date == self.selectedDate(), date == QDate.currentDate()
        r = QRectF(rect).adjusted(3, 2, -3, -2)
        d = min(r.width(), r.height())
        c = QRectF(r.center().x() - d / 2, r.center().y() - d / 2, d, d)
        if sel:
            p.setPen(QPen(QColor("#5A6672"), 1.4))
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(c.adjusted(1, 1, -1, -1))
        elif today:
            p.setPen(QPen(QColor("#8A96A2"), 1.1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c.adjusted(2, 2, -2, -2))
        f = p.font()
        f.setBold(sel)
        p.setFont(f)
        p.setPen(QColor("#B5BCC3") if other else QColor("#1C242D"))
        p.drawText(rect, Qt.AlignCenter, str(date.day()))
        p.restore()


class Canvas(QWidget):
    """Places children at fixed positions on a base canvas and scales them with the widget, like the mockup."""
    scaled = Signal(float)

    def __init__(self, base_w: int, base_h: int) -> None:
        super().__init__()
        self.base_w, self.base_h = base_w, base_h
        self.items: list[tuple[QWidget, tuple[int, int, int, int]]] = []
        self.f = 1.0

    def place(self, w: QWidget, x: int, y: int, wd: int, ht: int) -> QWidget:
        w.setParent(self)
        self.items.append((w, (x, y, wd, ht)))
        return w

    def resizeEvent(self, e) -> None:
        sx, sy = self.width() / self.base_w, self.height() / self.base_h
        for w, (x, y, wd, ht) in self.items:
            w.setGeometry(round(x * sx), round(y * sy), round(wd * sx), round(ht * sy))
        f = min(sx, sy)
        if abs(f - self.f) > 0.01:
            self.f = f
            self.scaled.emit(f)
        super().resizeEvent(e)


class NavBar(QFrame):
    currentRowChanged = Signal(int)

    def __init__(self, items: list[tuple[str, str]]) -> None:
        super().__init__()
        self.setObjectName("sidebarPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        brand = QLabel("iPhoneTransfer")
        brand.setObjectName("brand")
        sub = QLabel("PicsVids to PC")
        sub.setObjectName("cardSub")
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addSpacing(8)
        self.buttons: list[QPushButton] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (ic, text) in enumerate(items):
            b = QPushButton("  " + text)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(icons.icon(ic, "#1C242D", size=20))
            b.setIconSize(QSize(20, 20))
            self.group.addButton(b, i)
            self.buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.group.idClicked.connect(self.currentRowChanged.emit)

    def currentRow(self) -> int:
        return self.group.checkedId()

    def setCurrentRow(self, row: int) -> None:
        b = self.group.button(row)
        if b and not b.isChecked():
            b.setChecked(True)
            self.currentRowChanged.emit(row)


class Bridge(QObject):
    status = Signal(str)
    connected = Signal(object)          # DeviceInfo
    connect_failed = Signal(object)     # DeviceError
    library_loaded = Signal(object)     # Library
    library_failed = Signal(str)
    progress = Signal(object)           # Progress
    doctor_result = Signal(object)      # doctor.Check
    doctor_done = Signal(object)        # list[Check]
    resume_ready = Signal(bool)


class MainWindow(QMainWindow):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        src = self._bg_source()
        if not src.isNull():
            if self._bg_win is not None and self._bg_size == self.size():
                painter.drawPixmap(0, 0, self._bg_win)
            else:
                # while the window is being resized: a quick stretch now, a sharp copy once resizing stops
                painter.drawPixmap(self._cover(src.size()), src)
                self._bg_timer.start()
        super().paintEvent(event)

    def _bg_source(self) -> QPixmap:
        if not hasattr(self, "_bg_src"):
            self._bg_src = QPixmap(art.path("background.jpg")) if art.exists("background.jpg") else QPixmap()
            self._bg_size = self._blur_size = None
            self._bg_win = self._bg_blur = self._bg_small = None
            self._bg_timer = QTimer(self)
            self._bg_timer.setSingleShot(True)
            self._bg_timer.setInterval(160)
            self._bg_timer.timeout.connect(self._rebuild_bg)
        return self._bg_src

    def _cover(self, size: QSize) -> QRect:
        k = max(self.width() / max(1, size.width()), self.height() / max(1, size.height()))
        w, h = round(size.width() * k), round(size.height() * k)
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def _rebuild_bg(self) -> None:
        """Smooth, window-sized copy of the background (done once per size, after resizing stops)."""
        if getattr(self, "_sizing", False):
            self._bg_timer.start()
            return
        src = self._bg_source()
        if src.isNull():
            return
        win = QPixmap(self.size())
        win.fill(Qt.white)
        p = QPainter(win)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self._cover(src.size()), src)
        p.end()
        self._bg_win, self._bg_size = win, self.size()
        self.update()

    def frost_blur(self) -> Optional[QPixmap]:
        """Blurred background for frosted cards; only built if a frosted card is on screen."""
        src = self._bg_source()
        if src.isNull():
            return None
        if self._blur_size != self.size():
            if not hasattr(self, "_blur_src"):
                self._blur_src = QPixmap()
                try:
                    from PIL import Image, ImageFilter
                    import io
                    im = Image.open(io.BytesIO(art.read("background.jpg"))).convert("RGB")
                    im = im.resize((max(1, im.width // 4), max(1, im.height // 4)), Image.LANCZOS)
                    im = im.filter(ImageFilter.GaussianBlur(9))
                    qi = QImage(im.tobytes(), im.width, im.height, 3 * im.width, QImage.Format_RGB888).copy()
                    self._blur_src = QPixmap.fromImage(qi)
                except Exception:
                    log.exception("blur")
            blur = QPixmap(self.size())
            blur.fill(Qt.white)
            if not self._blur_src.isNull():
                p = QPainter(blur)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(self._cover(self._blur_src.size()), self._blur_src)
                p.end()
            self._bg_blur, self._blur_size = blur, self.size()
            self._bg_small = blur.toImage().scaled(max(1, self.width() // 22), max(1, self.height() // 22),
                                                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation
                                                   ).convertToFormat(QImage.Format_RGB32)
        return self._bg_blur

    def bg_luma(self, r: QRect) -> float:
        """Average brightness (0..1) of the painting under a window rectangle."""
        self.frost_blur()
        img = self._bg_small
        if img is None:
            return 1.0
        kx, ky = img.width() / max(1, self.width()), img.height() / max(1, self.height())
        x0, x1 = max(0, int(r.left() * kx)), min(img.width() - 1, int(r.right() * kx))
        y0, y1 = max(0, int(r.top() * ky)), min(img.height() - 1, int(r.bottom() * ky))
        tot = n = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                c = img.pixelColor(x, y)
                tot += 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
                n += 1
        return tot / n if n else 1.0

    def _init_size(self) -> None:
        """Open at the mockup's 16:10 shape, as large as fits comfortably on the screen."""
        self.setMinimumSize(880, round(880 / RATIO))
        scr = QGuiApplication.primaryScreen().availableGeometry()
        w = int(min(scr.width() * 0.82, (scr.height() - 60) * 0.92 * RATIO))
        self.resize(w, round(w / RATIO))

    def nativeEvent(self, event_type, message):
        """While the window is dragged to a new size, keep the client area at the mockup's 16:10 ratio."""
        if os.name == "nt":
            try:
                if bytes(event_type) == b"windows_generic_MSG":
                    import ctypes.wintypes as wt
                    msg = wt.MSG.from_address(int(message))
                    if msg.message == 0x0231:                       # WM_ENTERSIZEMOVE
                        self._sizing = True
                    elif msg.message == 0x0232:                     # WM_EXITSIZEMOVE: now restyle + sharpen once
                        self._sizing = False
                        self._scale_timer.start(0)
                        self._bg_source()
                        self._bg_timer.start(0)
                    elif msg.message == 0x0214 and not self.isMaximized() and not self.isFullScreen():  # WM_SIZING
                        r = wt.RECT.from_address(msg.lParam)
                        dpr = self.devicePixelRatioF()
                        fw = round((self.frameGeometry().width() - self.width()) * dpr)
                        fh = round((self.frameGeometry().height() - self.height()) * dpr)
                        cw, ch = r.right - r.left - fw, r.bottom - r.top - fh
                        edge = msg.wParam
                        if edge in (3, 6):                          # top / bottom edge: width follows
                            r.right = r.left + round(ch * RATIO) + fw
                        else:                                       # sides and corners: height follows
                            nh = round(cw / RATIO) + fh
                            if edge in (4, 5):
                                r.top = r.bottom - nh
                            else:
                                r.bottom = r.top + nh
                        return True, 1
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _heading(self, text: str, icon: str) -> QWidget:
        """Page heading with the same line icon as its side-panel button."""
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        h.addWidget(self._icon_label(icon, 28))
        h.addWidget(label(text, "h1"))
        h.addStretch(1)
        return box

    def _icon_label(self, name: str, size: int = 22) -> QLabel:
        lb = icon_label(name, size)
        self._scaled_pix.append((lb, name, size))
        return lb

    def _set_phone_icon(self, name: str) -> None:
        self._scaled_pix = [(lb, name if lb is self.phone_icon else n, sz) for lb, n, sz in self._scaled_pix]
        n = round(44 * self.root.f)
        self.phone_icon.setPixmap(icons.pixmap(name, "#1C242D", n))

    def _scaled_icon(self, w, size: int) -> None:
        w.setIconSize(QSize(size, size))
        self._scaled_icons.append((w, size))

    def _apply_scale(self) -> None:
        if getattr(self, "_sizing", False):
            return
        f = self.root.f
        theme.apply_scale(QApplication.instance(), f)
        for w, size in self._scaled_icons:
            n = round(size * f)
            w.setIconSize(QSize(n, n))
        for lb, name, size in self._scaled_pix:
            n = round(size * f)
            lb.setPixmap(icons.pixmap(name, "#1C242D", n))
            lb.setFixedSize(n + 2, n + 2)
        for lay, (l, t, r, b) in self._page_margins:
            lay.setContentsMargins(round(l * f), round(t * f), round(r * f), round(b * f))
        for wd, h in getattr(self, "_fixed_heights", []):
            wd.setFixedHeight(max(3, round(h * f)))
        for tree in (self.month_tree, self.album_tree):
            tree.doItemsLayout()
        for tw in (self.tabs, self.opts_panel):          # tab widths are cached; re-set texts so they re-measure
            tb = tw.tabBar()
            for i in range(tb.count()):
                tb.setTabText(i, tb.tabText(i))

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self._scaled_icons: list = []
        self._scaled_pix: list = []
        self._page_margins: list = []
        self._init_size()
        self.settings = QSettings("iPhoneTransfer", "iPhoneTransfer")
        self.hub = DeviceHub()
        self.bridge = Bridge()
        self.library: Optional[Library] = None
        self.device = None
        self.engine: Optional[CopyEngine] = None
        self.copy_dest: Optional[Path] = None
        self.copy_mode = ""
        self._busy = False
        self._last_jobs: list[CopyJob] = []
        self._plan_newest: Optional[dt.datetime] = None
        self._resumes = 0
        self._waiting_resume = False
        self._doctor_results: list[doctor.Check] = []
        self.tray: Optional[QSystemTrayIcon] = None
        self.c = theme.colors()

        b = self.bridge
        b.status.connect(self._set_status)
        b.connected.connect(self._on_connected)
        b.connect_failed.connect(self._on_connect_failed)
        b.library_loaded.connect(self._on_library)
        b.library_failed.connect(self._on_library_failed)
        b.progress.connect(self._on_progress)
        b.doctor_result.connect(self._on_doctor_result)
        b.doctor_done.connect(self._on_doctor_done)
        b.resume_ready.connect(self._on_resume_ready)

        self._build_ui()
        self._load_settings()
        self._update_buttons()
        QTimer.singleShot(400, self.connect_device)

    # =============================================================== layout
    def _build_ui(self) -> None:
        self.root = Canvas(BASE_W, BASE_H)
        self.sidebar = NavBar([("phone", "Connect"), ("photos", "Transfer"), ("pulse", "Troubleshoot"), ("help", "Help")])
        for b in self.sidebar.buttons:
            self._scaled_icon(b, 20)
        self.sidebar.currentRowChanged.connect(self._go)
        self.root.place(self.sidebar, 25, 25, 197, 395)

        dev, dl = skin_card("cardDevice", (6, 0, 4, 0))
        dl.addWidget(self._icon_label("phone"))
        self.side_status = QLabel("")
        self.side_status.setWordWrap(True)
        self.side_status.setStyleSheet("background: transparent; color: #1C242D; font-weight: 600;")
        dl.addWidget(self.side_status, 1)
        self.root.place(dev, 25, 642, 197, 80)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_connect_page())
        self.stack.addWidget(self._build_copy_page())
        self.stack.addWidget(self._build_doctor_page())
        self.stack.addWidget(self._build_help_page())
        self.root.place(self.stack, 253, 25, 925, 697)

        # text pages keep to the same column as the Copy list, so the figure on the right stays visible
        for i in (PAGE_CONNECT, PAGE_DOCTOR, PAGE_HELP):
            lay = self.stack.widget(i).layout()
            m = (0, 0, 256, 0)
            lay.setContentsMargins(*m)
            self._page_margins.append((lay, m))
        self.setCentralWidget(self.root)
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(200)
        self._scale_timer.timeout.connect(self._apply_scale)
        self.root.scaled.connect(lambda _f: None if getattr(self, "_sizing", False) else self._scale_timer.start(200))
        self.sidebar.setCurrentRow(PAGE_CONNECT)

    def _go(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        if self.sidebar.currentRow() != row:
            self.sidebar.setCurrentRow(row)

    # ------------------------------------------------------------ connect page
    def _build_connect_page(self) -> QWidget:
        w, lay = page()
        lay.addWidget(self._heading("Connect your iPhone", "phone"))

        st = QFrame()
        st.setObjectName("cardTop")
        sl = QVBoxLayout(st)
        sl.setContentsMargins(10, 6, 10, 6)
        sl.setSpacing(8)
        top = QHBoxLayout()
        self.phone_icon = self._icon_label("phone", 44)
        top.addWidget(self.phone_icon)
        col = QVBoxLayout()
        self.device_label = label("No iPhone connected", "big")
        self.library_label = label("", "")
        self.status_label = label("", "muted", wrap=True)
        col.addWidget(self.device_label)
        col.addWidget(self.library_label)
        col.addWidget(self.status_label)
        top.addLayout(col, 1)
        sl.addLayout(top)
        brow = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self.connect_device)
        self.next_btn = QPushButton("Next: Choose Photos  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(lambda: self._go(PAGE_COPY))
        self.next_btn.hide()
        brow.addWidget(self.connect_btn)
        brow.addWidget(self.next_btn)
        brow.addStretch(1)
        sl.addLayout(brow)
        lay.addWidget(st)

        self.problem_card, pl = card()
        self.problem_title = label("", "h2", wrap=True)
        self.problem_title.setStyleSheet(f"color: {self.c['fail']}; background: transparent;")
        self.problem_steps = label("", "", wrap=True)
        pl.addWidget(self.problem_title)
        pl.addWidget(self.problem_steps)
        prow = QHBoxLayout()
        b = QPushButton("Open Troubleshoot")
        b.clicked.connect(lambda: (self._go(PAGE_DOCTOR), self.run_doctor()))
        prow.addWidget(b)
        b2 = QPushButton("Try Again")
        b2.clicked.connect(self.connect_device)
        prow.addWidget(b2)
        prow.addStretch(1)
        pl.addLayout(prow)
        self.problem_card.hide()
        lay.addWidget(self.problem_card)

        tips, tl = card()
        tl.addWidget(label("Before you connect", "h2"))
        steps = [
            "Install the free <b>Apple Devices</b> app from the Microsoft Store (or iTunes). You don't have to open it. "
            "<a href='https://apps.microsoft.com/detail/9NP83LWLPZ9K'>Get it here</a>",
            "Use a <b>USB data cable</b> straight into the PC (no hub). Cheap cables often only charge.",
            "<b>Unlock</b> the iPhone and stay on the Home Screen.",
            "When the iPhone asks <b>“Trust This Computer?”</b>, tap <b>Trust</b> and enter your passcode.",
            "Check that Windows can see it: open <b>File Explorer → This PC → Apple iPhone</b>. You should see "
            "<b>Internal Storage</b> with folders inside. If it's empty or missing, unlock the iPhone and plug it "
            "in again. <a href='explorer:thispc'>Open This PC</a>",
            "Close iTunes, Apple Devices, CopyTrans, iMazing and other iPhone apps while copying.",
        ]
        for i, s in enumerate(steps, 1):
            lb = label(f"<b>{i}.</b>&nbsp; {s}", wrap=True)
            lb.setOpenExternalLinks(False)
            lb.linkActivated.connect(self._open_link)
            tl.addWidget(lb)
        tl.addWidget(label("Photos stored only in iCloud (“Optimize iPhone Storage”) can't be copied over USB. "
                           "See Help for how to get them.", "muted", wrap=True))
        lay.addWidget(tips)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------ copy page
    def _build_copy_page(self) -> QWidget:
        w = Canvas(925, 697)
        w.setObjectName("page")

        # status + speed cards (top row)
        stc, stl = skin_card("cardStatus", (8, 0, 6, 0), 10)
        stl.addWidget(self._icon_label("phone"))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.copy_state_label = label("Not connected", "cardTitle")
        self.copy_device_label = label("", "cardSub")
        col.addWidget(self.copy_state_label)
        col.addWidget(self.copy_device_label)
        stl.addLayout(col, 1)
        w.place(stc, 0, 0, 254, 73)

        spc, spl = skin_card("cardSpeed", (8, 0, 6, 0), 10)
        spl.addWidget(self._icon_label("speed"))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("Speed", "cardSub"))
        self.speed_label = label("—", "cardBig")
        col.addWidget(self.speed_label)
        spl.addLayout(col, 1)
        w.place(spc, 272, 0, 223, 73)

        # month / album list
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_month_tab(), "By Year-Month")
        self.tabs.addTab(self._build_album_tab(), "By Album")
        self.tabs.currentChanged.connect(lambda _: self._update_selection_label())
        self.tabs.setObjectName("listPanel")
        w.place(self.tabs, 0, 82, 669, 430)

        self.list_hint = QFrame()
        hl = QVBoxLayout(self.list_hint)
        hl.setContentsMargins(24, 0, 24, 0)
        hint = label("Your months and albums will appear here once your iPhone is connected.", "frostTitle", wrap=True)
        hint.setAlignment(Qt.AlignCenter)
        hl.addWidget(hint)
        w.place(self.list_hint, 0, 130, 669, 370)
        self.tabs.currentChanged.connect(lambda _i: self._update_list_hint())

        # tiles + date range card
        self.tile_all = self._tile("checks", "All", self._toggle_all)
        self.tile_dates = self._tile("calendar", "Dates", checkable=True)
        self.tile_save = self._tile("folder", "Folder", self._open_dest)
        self.tile_opts = self._tile("sliders", "Options", checkable=True)
        for i, t in enumerate((self.tile_all, self.tile_dates, self.tile_save, self.tile_opts)):
            w.place(t, i * 93, 522, 78, 78)

        self.range_card = QFrame()
        self.range_card.setObjectName("cardDaterange")
        rv = QVBoxLayout(self.range_card)
        rv.setContentsMargins(6, 0, 6, 0)
        rv.setSpacing(2)
        self.range_cb = QCheckBox("Date range")
        self.range_from = QDateEdit()
        self.range_to = QDateEdit()
        for de in (self.range_from, self.range_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("d MMM yyyy")
            de.setDate(QDate.currentDate())
        self.range_from.setDate(QDate.currentDate().addDays(-30))
        for de in (self.range_from, self.range_to):
            de.setCalendarWidget(PearlCalendar())
            popup = de.calendarWidget().parentWidget()        # Qt's pop-up window around the calendar
            if popup is not None:
                popup.setObjectName("calPopup")
                popup.setWindowFlags(popup.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
                popup.setAttribute(Qt.WA_TranslucentBackground)
                popup.setAttribute(Qt.WA_StyledBackground)
                popup.setStyleSheet("QWidget#calPopup { background: transparent; border: none; }")
        rv.addWidget(self.range_cb)
        rr = QHBoxLayout()
        rr.setSpacing(4)
        rr.addWidget(self.range_from, 1)
        rr.addWidget(QLabel("—"))
        rr.addWidget(self.range_to, 1)
        rv.addLayout(rr)
        w.place(self.range_card, 375, 522, 294, 78)
        self.range_cb.toggled.connect(self._on_range_changed)
        # picking a date turns the date range on
        self.range_from.dateChanged.connect(lambda _d: self.range_cb.setChecked(True))
        self.range_to.dateChanged.connect(lambda _d: self.range_cb.setChecked(True))
        self.range_from.dateChanged.connect(self._on_range_changed)
        self.range_to.dateChanged.connect(self._on_range_changed)
        self.tile_dates.toggled.connect(self.range_cb.setChecked)
        self.range_cb.toggled.connect(self.tile_dates.setChecked)

        # options + log: a panel the Options tile opens over the empty middle area
        self.opts_panel = QTabWidget()
        self.opts_panel.setObjectName("optsPanel")
        ow = QWidget()
        ol = QVBoxLayout(ow)
        ol.setContentsMargins(10, 6, 10, 4)
        ol.setSpacing(4)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        self.date_combo = QComboBox()
        self.date_combo.addItem("Recently Added", DATE_ADDED)
        self.date_combo.addItem("Date Taken", DATE_TAKEN)
        self.date_combo.setToolTip("Which date sorts photos into months and starts each file name.\n"
                                   "Recently Added: the order of 'Recently Added' on the iPhone.\n"
                                   "Date Taken: when the photo or video was shot.")
        self.date_combo.currentIndexChanged.connect(self._rebuild_month_tree)
        self.date_combo.currentIndexChanged.connect(self._update_example)
        self.media_combo = QComboBox()
        self.media_combo.addItem("Photos and Videos", MEDIA_ALL)
        self.media_combo.addItem("Photos only", MEDIA_PHOTOS)
        self.media_combo.addItem("Videos only", MEDIA_VIDEOS)
        self.media_combo.currentIndexChanged.connect(self._update_selection_label)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        self.workers_spin.setToolTip("How many files are copied at the same time. 4 is usually fastest.")
        # the number sits in the middle of the box (Qt ignores the left rim of a border-image, so even it out)
        self.workers_spin.setAlignment(Qt.AlignCenter)
        self.workers_spin.findChild(QLineEdit).setTextMargins(6, 0, 0, 0)
        dest = QHBoxLayout()
        dest.setSpacing(8)
        dest.addWidget(QLabel("Save to:"))
        dest.addLayout(self.month_dest_row, 1)
        dest.addLayout(self.album_dest_row, 1)
        ol.addLayout(dest)
        self.tabs.currentChanged.connect(self._show_dest_row)
        for row_widgets in ((QLabel("Sort by:"), self.date_combo, QLabel("Include:"), self.media_combo,
                             QLabel("Parallel transfers:"), self.workers_spin),):
            top = QHBoxLayout()
            top.setSpacing(8)
            for wd in row_widgets:
                top.addWidget(wd)
            top.addStretch(1)
            ol.addLayout(top)
        ol.addSpacing(4)

        self.edited_cb = QCheckBox("Also copy edited versions")
        self.live_cb = QCheckBox("Also copy Live Photo videos (.MOV)")
        self.tidy_cb = QCheckBox("Rename app/web downloads to IMG_<ID>")
        self.tidy_cb.setToolTip("Photos saved from Instagram, WhatsApp, browsers… on another device often have long\n"
                                "random names. Camera names like IMG_1234 always stay as they are.")
        self.new_cb = QCheckBox("Only new since last copy")
        self.verify_cb = QCheckBox("Verify every file (slower)")
        self.verify_cb.setToolTip("Reads each file from the iPhone a second time and compares checksums.\n"
                                  "Proves the copy is identical. Roughly halves the speed.")
        self.heic_cb = QCheckBox("Convert HEIC to JPG (not lossless)")
        self.heic_cb.setToolTip("For PCs or apps that can't open HEIC. Quality 95, keeps date/GPS/camera info.\n"
                                "The original HEIC is not kept. Leave off to get exact originals.")
        self.resume_cb = QCheckBox("Resume if the iPhone disconnects")
        self.confirm_cb = QCheckBox("Ask before starting a copy")
        for cb in (self.edited_cb, self.live_cb, self.new_cb, self.heic_cb):
            cb.toggled.connect(self._update_selection_label)
        for cb in (self.tidy_cb, self.heic_cb):
            cb.toggled.connect(self._update_example)
        # folder + file names: pick from examples, see the result right below
        now = self._sample_when = dt.datetime.now().replace(microsecond=0)
        self.folder_combo = QComboBox()
        for key, text in ((FOLDER_YEAR_MON, "yyyy mmm  (e.g. 1998 Aug)"),
                          (FOLDER_YEAR_MM, "yyyy-mm  (e.g. 2002-12)")):
            self.folder_combo.addItem(text, key)
        self.folder_combo.setToolTip("How the Year-Month folders are named. Album folders always use the album's name.")
        self.file_combo = QComboBox()
        for key, text in ((FILE_DATETIME, "Date_Time_Name  (e.g. 20260805_00-00-00_IMG_1234)"),
                          (FILE_DATE, "Date_Name  (e.g. 20260805_IMG_1234)"),
                          (FILE_ORIGINAL, "Name only  (e.g. IMG_1234)")):
            self.file_combo.addItem(text, key)
        self.file_combo.setToolTip("How each file is named. Date + time keeps files in shooting order in File Explorer.\n"
                                   "If two files would get the same name, _2, _3… is added, nothing is overwritten.")
        names = QGridLayout()
        names.setHorizontalSpacing(8)
        names.setVerticalSpacing(4)
        names.addWidget(QLabel("Year-Month folder:"), 0, 0)
        names.addWidget(self.folder_combo, 0, 1)
        names.addWidget(QLabel("File name:"), 1, 0)
        names.addWidget(self.file_combo, 1, 1)
        names.setColumnStretch(2, 1)
        ol.addSpacing(6)
        ol.addLayout(names)
        ol.addWidget(self.tidy_cb)
        self.example_label = label("", "cardSub", wrap=True)
        ol.addWidget(self.example_label)
        for cmb in (self.folder_combo, self.file_combo):
            cmb.currentIndexChanged.connect(self._update_example)

        ol.addSpacing(6)
        ol.addWidget(label("More options", "barTitle"))
        boxes = [self.edited_cb, self.live_cb, self.new_cb, self.verify_cb, self.heic_cb, self.resume_cb,
                 self.confirm_cb]
        for i, cb in enumerate(boxes):
            grid.addWidget(cb, i // 2, i % 2)
        for c in range(2):
            grid.setColumnStretch(c, 1)
        grid.setVerticalSpacing(6)
        ol.addLayout(grid)
        ol.addStretch(1)
        # if the window is small, the options scroll instead of squashing the boxes
        ow.setObjectName("page")
        osc = QScrollArea()
        osc.setWidgetResizable(True)
        osc.setFrameShape(QFrame.NoFrame)
        osc.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                          " QScrollArea > QWidget > QWidget#page { background: transparent; }")
        osc.viewport().setAutoFillBackground(False)
        osc.setWidget(ow)
        self.opts_panel.addTab(osc, "Options")
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(2000)
        self.opts_panel.addTab(self.log_box, "Log")
        w.place(self.opts_panel, 0, 82, 669, 430)
        self.opts_panel.hide()
        self.tile_opts.toggled.connect(self.opts_panel.setVisible)
        self.tile_opts.toggled.connect(lambda on: self.tabs.setVisible(not on))
        self.tile_opts.toggled.connect(lambda _on: self._update_list_hint())
        self._show_dest_row(0)
        for ed in (self.month_dest, self.album_dest):
            ed.textChanged.connect(lambda _t: self._show_dest_row(self.tabs.currentIndex()))
        self.month_dest.textChanged.connect(lambda t: self.settings.setValue("month_dest", t))
        self.album_dest.textChanged.connect(lambda t: self.settings.setValue("album_dest", t))

        # copy bar + start button (bottom row)
        bar = QFrame()
        bar.setObjectName("whiteBlock")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(8, 0, 8, 0)
        bl.setSpacing(4)
        srow = QHBoxLayout()
        self.selection_label = label("", "frostTitle")
        srow.addWidget(self.selection_label, 1)
        self.eta_label = label("", "frostSub")
        srow.addWidget(self.eta_label)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_copy)
        srow.addWidget(self.cancel_btn)
        bl.addLayout(srow)
        self.progress_bar = SlimBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setFormat("")
        self.progress_bar.setFixedHeight(6)
        self._fixed_heights = [(self.progress_bar, 6)]
        bl.addWidget(self.progress_bar)
        self.stats_label = label("", "frostSub")
        bl.addWidget(self.stats_label)
        self.stats_label.hide()
        self.copy_bar = bar
        w.place(bar, 0, 622, 669, 75)

        self.start_btn = QPushButton("Start Copy")
        self.start_btn.setObjectName("startButton")
        self.start_btn.setIcon(icons.icon("arrow", "#101720", size=20))
        self._scaled_icon(self.start_btn, 20)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.start_copy)
        w.place(self.start_btn, 687, 622, 238, 75)
        return w

    def _tile(self, ic: str, text: str, on_click=None, checkable: bool = False) -> QToolButton:
        t = QToolButton()
        t.setObjectName("tileButton")
        t.setText(text)
        t.setIcon(icons.icon(ic, "#1C242D", size=22))
        self._scaled_icon(t, 22)
        t.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        t.setCheckable(checkable)
        t.setCursor(Qt.PointingHandCursor)
        if on_click:
            t.clicked.connect(on_click)
        return t

    def _current_tree(self) -> QTreeWidget:
        return self.month_tree if self.tabs.currentIndex() == 0 else self.album_tree

    def _toggle_all(self) -> None:
        tree = self._current_tree()
        it = QTreeWidgetItemIterator(tree)
        all_on = True
        while it.value():
            item = it.value()
            if item.parent() is None and not item.isHidden() and item.checkState(0) != Qt.Checked:
                all_on = False
                break
            it += 1
        self._check_all(tree, not all_on, visible_only=tree is self.album_tree)

    def _update_list_hint(self) -> None:
        if hasattr(self, "list_hint") and hasattr(self, "tile_opts"):
            empty = self._current_tree().topLevelItemCount() == 0
            self.list_hint.setVisible(empty and not self.tile_opts.isChecked())

    def _show_dest_row(self, idx: int = 0) -> None:
        for row, on in ((self.month_dest_row, idx == 0), (self.album_dest_row, idx != 0)):
            for i in range(row.count()):
                wd = row.itemAt(i).widget()
                if wd:
                    wd.setVisible(on)
        edit = self.month_dest if idx == 0 else self.album_dest
        self.tile_save.setToolTip(f"Open the save folder: {edit.text()}")
        if hasattr(self, "folder_combo"):
            self._update_example()

    def _open_dest(self) -> None:
        edit = self.month_dest if self.tabs.currentIndex() == 0 else self.album_dest
        p = Path(edit.text())
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        else:
            nice_info(self, "Open Folder", f"The save folder doesn't exist yet:\n{p}\n\n"
                      "It is created when you press Start Copy. You can change it in Options.", icon="folder")

    def _browse_dest(self) -> None:
        edit = self.month_dest if self.tabs.currentIndex() == 0 else self.album_dest
        d = QFileDialog.getExistingDirectory(self, "Choose destination folder", edit.text())
        if d:
            edit.setText(os.path.normpath(d))

    def _dest_row(self, default: Path) -> tuple[QHBoxLayout, QLineEdit]:
        row = QHBoxLayout()
        edit = QLineEdit(str(default))
        btn = QPushButton("Browse…")
        openb = QPushButton("Open")

        def browse():
            d = QFileDialog.getExistingDirectory(self, "Choose destination folder", edit.text())
            if d:
                edit.setText(os.path.normpath(d))

        def open_dir():
            p = Path(edit.text())
            if p.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

        btn.clicked.connect(browse)
        openb.clicked.connect(open_dir)
        edit.textChanged.connect(self._update_example)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        row.addWidget(openb)
        return row, edit

    def _build_month_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        self.month_tree = QTreeWidget()
        self.month_tree.setHeaderLabels(["Month", "Photos", "Videos", "Total", "Size"])
        self._tidy_columns(self.month_tree)
        self.month_tree.setObjectName("rows")
        self.month_tree.header().setStyleSheet("QHeaderView::section { background: rgba(236, 242, 248, 235); border: none; border-bottom: 1px solid rgba(60, 76, 92, 70); padding: 3px 6px; font-weight: 600; } QHeaderView { background: transparent; }")
        self.month_tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.month_tree, 1)
        self.month_dest_row, self.month_dest = self._dest_row(
            Path(os.path.expanduser("~")) / "Pictures" / "iPhone" / "By Month")
        return w

    def _build_album_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)
        frow = QHBoxLayout()
        self.album_filter = QLineEdit()
        self.album_filter.setPlaceholderText("Search albums…")
        self.album_filter.textChanged.connect(self._filter_albums)
        frow.addWidget(self.album_filter, 1)
        lay.addLayout(frow)
        self.album_tree = QTreeWidget()
        self.album_tree.setHeaderLabels(["Album", "Photos", "Videos", "Total", "Size"])
        self._tidy_columns(self.album_tree)
        self.album_tree.setObjectName("rows")
        self.album_tree.header().setStyleSheet("QHeaderView::section { background: rgba(236, 242, 248, 235); border: none; border-bottom: 1px solid rgba(60, 76, 92, 70); padding: 3px 6px; font-weight: 600; } QHeaderView { background: transparent; }")
        self.album_tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.album_tree, 1)
        self.album_dest_row, self.album_dest = self._dest_row(
            Path(os.path.expanduser("~")) / "Pictures" / "iPhone" / "Albums")
        return w

    # ------------------------------------------------------------ doctor page
    def _build_doctor_page(self) -> QWidget:
        w, lay = page()
        lay.addWidget(self._heading("Troubleshoot", "pulse"))
        intro, il = card()
        intro.setObjectName("cardTop")
        il.addWidget(label("Checks everything between Windows and your iPhone, one step at a time, and tells you "
                           "exactly what to do. Plug in and unlock the iPhone first.", "", wrap=True))
        brow = QHBoxLayout()
        self.doctor_btn = QPushButton("Run Checks")
        self.doctor_btn.setObjectName("primary")
        self.doctor_btn.clicked.connect(self.run_doctor)
        brow.addWidget(self.doctor_btn)
        self.restart_btn = QPushButton("Restart Apple Service")
        self.restart_btn.setToolTip("Restarts 'Apple Mobile Device Service'. Windows asks for permission.")
        self.restart_btn.clicked.connect(self._restart_service)
        brow.addWidget(self.restart_btn)
        b = QPushButton("Get Apple Devices")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(doctor.APPLE_DEVICES_STORE)))
        brow.addWidget(b)
        b = QPushButton("Copy Report")
        b.setToolTip("Copies the results as text, so you can keep them or search online for the problem.")
        b.clicked.connect(self._copy_doctor_report)
        brow.addWidget(b)
        brow.addStretch(1)
        il.addLayout(brow)
        lay.addWidget(intro)
        self.doctor_hint = QFrame()
        self.doctor_hint.setObjectName("whiteBlock")
        hl = QVBoxLayout(self.doctor_hint)
        hl.setContentsMargins(24, 0, 24, 0)
        hint = label("Press Run Checks. Each step shows up here with what to do next.", "frostTitle", wrap=True)
        hint.setAlignment(Qt.AlignCenter)
        hl.addWidget(hint)
        self._fixed_heights.append((self.doctor_hint, 235))
        self.doctor_hint.setFixedHeight(235)
        lay.addWidget(self.doctor_hint)
        self.doctor_panel = panel = QFrame()
        panel.setObjectName("whiteBlock")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(8)
        self.doctor_area = QScrollArea()
        self.doctor_area.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        self.doctor_list = QVBoxLayout(inner)
        self.doctor_list.setContentsMargins(0, 0, 8, 0)
        self.doctor_list.setSpacing(8)
        self.doctor_list.addStretch(1)
        self.doctor_area.setWidget(inner)
        self.doctor_area.setFrameShape(QFrame.NoFrame)
        pl.addWidget(self.doctor_area, 1)
        panel.hide()
        lay.addWidget(panel, 100)
        lay.addStretch(1)
        return w

    def _build_help_page(self) -> QWidget:
        w, lay = page()
        lay.addWidget(self._heading("Help", "help"))
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(help_html(self.c))
        tb.setStyleSheet("QTextBrowser { padding: 4px 8px; }")
        hc = QFrame()
        hc.setObjectName("card")
        hcl = QVBoxLayout(hc)
        hcl.setContentsMargins(6, 4, 4, 4)
        hcl.addWidget(tb)
        lay.addWidget(hc, 1)
        return w

    # ========================================================== settings
    def _load_settings(self) -> None:
        s = self.settings
        if s.value("month_dest"):
            self.month_dest.setText(s.value("month_dest"))
        if s.value("album_dest"):
            self.album_dest.setText(s.value("album_dest"))
        self.date_combo.setCurrentIndex(max(0, self.date_combo.findData(s.value("date_source", DATE_ADDED))))
        self.media_combo.setCurrentIndex(max(0, self.media_combo.findData(s.value("media", MEDIA_ALL))))
        self.folder_combo.setCurrentIndex(max(0, self.folder_combo.findData(s.value("folder_style", FOLDER_YEAR_MON))))
        self.file_combo.setCurrentIndex(max(0, self.file_combo.findData(s.value("file_style", FILE_DATETIME))))

        def flag(key, default):
            return s.value(key, "true" if default else "false") == "true"
        self.edited_cb.setChecked(flag("edited", True))
        self.live_cb.setChecked(flag("live", True))
        self.tidy_cb.setChecked(flag("tidy_names", False))
        self.verify_cb.setChecked(flag("verify", False))
        self.heic_cb.setChecked(flag("heic_jpg", False))
        self.resume_cb.setChecked(flag("auto_resume", True))
        self.confirm_cb.setChecked(flag("confirm_start", True))
        self.workers_spin.setValue(int(s.value("workers", 4)))
        self.tabs.setCurrentIndex(int(s.value("tab", 0)))
        self._update_example()

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("month_dest", self.month_dest.text())
        s.setValue("album_dest", self.album_dest.text())
        s.setValue("date_source", self.date_combo.currentData())
        s.setValue("folder_style", self.folder_combo.currentData())
        s.setValue("file_style", self.file_combo.currentData())
        s.setValue("media", self.media_combo.currentData())
        for key, cb in (("edited", self.edited_cb), ("live", self.live_cb), ("tidy_names", self.tidy_cb),
                        ("verify", self.verify_cb), ("heic_jpg", self.heic_cb), ("auto_resume", self.resume_cb),
                        ("confirm_start", self.confirm_cb)):
            s.setValue(key, "true" if cb.isChecked() else "false")
        s.setValue("workers", self.workers_spin.value())
        s.setValue("tab", self.tabs.currentIndex())

    def _last_copy_key(self, mode: str) -> Optional[str]:
        if not self.device:
            return None
        return f"last_copy/{self.device.serial}/{mode}"

    def _last_copy(self, mode: str) -> Optional[dt.datetime]:
        key = self._last_copy_key(mode)
        v = self.settings.value(key) if key else None
        try:
            return dt.datetime.fromisoformat(v) if v else None
        except (TypeError, ValueError):
            return None

    def _update_example(self) -> None:
        if not hasattr(self, "album_dest") or not hasattr(self, "heic_cb"):
            return
        # a fixed sample, so the line only changes when a naming choice changes
        when = dt.datetime(2026, 8, 5, 0, 0, 0)
        root = r"F:\freenbeck married life\bonfybobafreya"
        ext = "JPG" if self.heic_cb.isChecked() else "HEIC"
        pre = date_prefix(when, self.file_combo.currentData())
        pre = f"{pre}_" if pre else ""
        folder = month_folder(when, self.folder_combo.currentData()) if self.tabs.currentIndex() == 0 else "My Album"
        text = f"Example:  {root}\\{folder}\\{pre}IMG_1234.{ext}"
        if self.tidy_cb.isChecked():
            text += f"\nIf app/web download:  {pre}IMG_123456.JPG"
        self.example_label.setText(text)

    # ========================================================= device
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _log(self, text: str) -> None:
        self.log_box.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {text}")
        log.info(text)

    def connect_device(self) -> None:
        if self._busy or self.engine:
            return
        self._busy = True
        self.library = None
        self.device = None
        self.month_tree.clear()
        self.album_tree.clear()
        self.problem_card.hide()
        self.next_btn.hide()
        self.device_label.setText("Connecting…")
        self.library_label.setText("")
        self._set_phone_icon("wait")
        self._set_status("Looking for your iPhone…")
        self._update_buttons()

        def work():
            try:
                info = self.hub.call(self.hub.connect(on_status=self.bridge.status.emit), timeout=150)
            except DeviceError as e:
                self.bridge.connect_failed.emit(e)
                return
            except Exception as e:
                log.exception("connect")
                problem, steps = doctor.explain_connect_error(e)
                self.bridge.connect_failed.emit(DeviceError(problem, steps))
                return
            self.bridge.connected.emit(info)
            try:
                lib = read_library(self.hub, progress=self.bridge.status.emit)
            except Exception as e:
                log.exception("library")
                self.bridge.library_failed.emit(f"{type(e).__name__}: {e}")
                return
            self.bridge.library_loaded.emit(lib)

        threading.Thread(target=work, daemon=True, name="connect").start()

    def _device_text(self, info) -> str:
        model = MODELS.get(info.model, info.model)
        conn = "USB" if info.connection == "USB" else "Wi-Fi"
        return f"{info.name}  ·  {model}  ·  iOS {info.ios}  ·  {conn}"

    def _on_connected(self, info) -> None:
        self.device = info
        self._set_phone_icon("phone")
        self.device_label.setText(self._device_text(info))
        self.copy_device_label.setText(self._device_text(info))
        self.copy_state_label.setText("Connected")
        if info.connection != "USB":
            self._set_status("Connected over Wi-Fi: this works but is 5-10x slower. Plug in a USB cable for speed.")
        self._log(f"Connected to {info.name} (iOS {info.ios}) via {info.connection}")
        self.side_status.setText(f"● {MODELS.get(info.model, info.model)}\n   reading library…")

    def _on_connect_failed(self, e: DeviceError) -> None:
        self._busy = False
        self._set_phone_icon("plug")
        self.device_label.setText("No iPhone connected")
        self._set_status("")
        self.problem_title.setText(e.problem)
        self.problem_steps.setText("".join(f"<p>• {s}</p>" for s in e.steps) or "")
        self.problem_card.show()
        self.side_status.setText("○ Not connected")
        self.copy_state_label.setText("Not connected")
        self.copy_device_label.setText("")
        self._log(f"Connect failed: {e.problem}")
        self._update_buttons()

    def _on_library_failed(self, msg: str) -> None:
        self._busy = False
        self.problem_title.setText("Connected, but the Photos library could not be read.")
        self.problem_steps.setText(f"<p>• Unlock the iPhone, open the Photos app once and press Try again.</p>"
                                   f"<p class='muted'>Details: {msg}</p>")
        self.problem_card.show()
        self._set_status("")
        self._log("Could not read the Photos library: " + msg)
        self._update_buttons()

    def _on_library(self, lib: Library) -> None:
        self._busy = False
        self.library = lib
        la = lib.library_assets()
        summary = (f"{len(la):,} items  ·  {sum(not a.is_video for a in la):,} photos  ·  "
                   f"{sum(a.is_video for a in la):,} videos  ·  {human_bytes(sum(a.size for a in la))}  ·  "
                   f"{len(lib.albums):,} albums")
        self.library_label.setText(summary)
        if self.device and self.device.connection == "USB":
            self._set_status("Ready. Choose what to copy.")
        self.next_btn.show()
        self.side_status.setText(f"● {MODELS.get(self.device.model, self.device.model)}\n   {len(la):,} items")
        self._log("Library: " + summary)
        self._rebuild_month_tree()
        self._build_album_tree()
        self._update_buttons()

    # ====================================================== month tree
    def _rebuild_month_tree(self) -> None:
        if not self.library:
            return
        source = self.date_combo.currentData()
        prev_unchecked = set()
        first = self.month_tree.topLevelItemCount() == 0
        it = QTreeWidgetItemIterator(self.month_tree)
        while it.value():
            item = it.value()
            key = item.data(0, ROLE_KEY)
            if isinstance(key, str) and len(key) == 7 and item.checkState(0) == Qt.Unchecked:
                prev_unchecked.add(key)
            it += 1

        groups: dict[str, list[Asset]] = defaultdict(list)
        for a in self.library.library_assets():
            d = asset_date(a, source)
            groups[f"{d:%Y-%m}" if d else "0000-00"].append(a)
        self.month_groups = groups

        self.month_tree.blockSignals(True)
        self.month_tree.clear()
        years: dict[str, QTreeWidgetItem] = {}
        for key in sorted(groups, reverse=True):
            year = key[:4]
            if year not in years:
                yi = QTreeWidgetItem([year if year != "0000" else "Unknown date"])
                yi.setFlags(yi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                yi.setData(0, ROLE_KEY, "Y" + year)
                self.month_tree.addTopLevelItem(yi)
                years[year] = yi
            items = groups[key]
            lbl = f"{key[:4]} - {key[5:]}" if key != "0000-00" else "Unknown date"
            mi = QTreeWidgetItem([lbl, f"{sum(not a.is_video for a in items):,}",
                                  f"{sum(a.is_video for a in items):,}", f"{len(items):,}",
                                  human_bytes(sum(a.size for a in items))])
            mi.setFlags(mi.flags() | Qt.ItemIsUserCheckable)
            mi.setData(0, ROLE_KEY, key)
            checked = (not first) and key not in prev_unchecked
            mi.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            for c in (1, 2, 3, 4):
                mi.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            years[year].addChild(mi)
        for yi in years.values():
            n = yi.childCount()
            kids = [groups[yi.child(i).data(0, ROLE_KEY)] for i in range(n)]
            ph = sum(sum(not a.is_video for a in k) for k in kids)
            vi = sum(sum(a.is_video for a in k) for k in kids)
            yi.setText(1, f"{ph:,}")
            yi.setText(2, f"{vi:,}")
            yi.setText(3, f"{ph + vi:,}")
            yi.setText(4, human_bytes(sum(sum(a.size for a in k) for k in kids)))
            for c in (1, 2, 3, 4):
                yi.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
        self.month_tree.blockSignals(False)
        if self.month_tree.topLevelItemCount():
            self.month_tree.topLevelItem(0).setExpanded(True)
        self._update_selection_label()

    def _select_recent_months(self) -> None:
        self.range_from.blockSignals(True)
        self.range_to.blockSignals(True)
        self.range_from.setDate(QDate.currentDate().addDays(-30))
        self.range_to.setDate(QDate.currentDate())
        self.range_from.blockSignals(False)
        self.range_to.blockSignals(False)
        if self.range_cb.isChecked():
            self._on_range_changed()
        else:
            self.range_cb.setChecked(True)

    def _range(self) -> Optional[tuple[dt.date, dt.date]]:
        if not self.range_cb.isChecked():
            return None
        a, b = self.range_from.date().toPython(), self.range_to.date().toPython()
        return (a, b) if a <= b else (b, a)

    def _on_range_changed(self, *_) -> None:
        rng = self._range()
        if rng and self.library and self._mode() == "month":
            first = f"{rng[0]:%Y-%m}"
            last = f"{rng[1]:%Y-%m}"
            self.month_tree.blockSignals(True)
            it = QTreeWidgetItemIterator(self.month_tree)
            while it.value():
                item = it.value()
                key = item.data(0, ROLE_KEY)
                if isinstance(key, str) and len(key) == 7:
                    item.setCheckState(0, Qt.Checked if first <= key <= last else Qt.Unchecked)
                it += 1
            self.month_tree.blockSignals(False)
            self.month_tree.viewport().update()
        self._update_selection_label()

    def _selected_month_assets(self) -> list[Asset]:
        out: list[Asset] = []
        it = QTreeWidgetItemIterator(self.month_tree)
        while it.value():
            item = it.value()
            key = item.data(0, ROLE_KEY)
            if isinstance(key, str) and len(key) == 7 and item.checkState(0) == Qt.Checked:
                out.extend(self.month_groups.get(key, []))
            it += 1
        return out

    # ====================================================== album tree
    def _build_album_tree(self) -> None:
        lib = self.library
        self.album_tree.blockSignals(True)
        self.album_tree.clear()
        self.album_by_pk = {a.pk: a for a in lib.albums}
        groups = {
            "smart": QTreeWidgetItem(["Smart albums"]),
            "user": QTreeWidgetItem(["My albums"]),
            "shared": QTreeWidgetItem(["Shared albums"]),
        }
        folders: dict[tuple[str, str], QTreeWidgetItem] = {}
        for g in groups.values():
            g.setFlags(g.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            g.setCheckState(0, Qt.Unchecked)
        for al in lib.albums:
            parent = groups[al.kind]
            if al.folder:
                path = ""
                for part in al.folder.split(" / "):
                    path = f"{path}/{part}"
                    k = (al.kind, path)
                    if k not in folders:
                        fi = QTreeWidgetItem([f"📁 {part}"])
                        fi.setFlags(fi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                        fi.setCheckState(0, Qt.Unchecked)
                        parent.addChild(fi)
                        folders[k] = fi
                    parent = folders[k]
            members = [lib.assets[pk] for pk in al.asset_pks if pk in lib.assets]
            vids = sum(a.is_video for a in members)
            item = QTreeWidgetItem([al.title, f"{len(members) - vids:,}", f"{vids:,}", f"{len(members):,}",
                                    human_bytes(sum(a.size for a in members))])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, ROLE_KEY, al.pk)
            for c in (1, 2, 3, 4):
                item.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            parent.addChild(item)
        for g in groups.values():
            if g.childCount():
                self.album_tree.addTopLevelItem(g)
                g.setExpanded(True)
        self.album_tree.blockSignals(False)
        self._update_selection_label()

    def _filter_albums(self, text: str) -> None:
        text = text.lower().strip()
        it = QTreeWidgetItemIterator(self.album_tree)
        while it.value():
            item = it.value()
            if isinstance(item.data(0, ROLE_KEY), int):
                item.setHidden(bool(text) and text not in item.text(0).lower())
            it += 1

    def _selected_albums(self) -> list[Album]:
        out = []
        it = QTreeWidgetItemIterator(self.album_tree)
        while it.value():
            item = it.value()
            pk = item.data(0, ROLE_KEY)
            if isinstance(pk, int) and item.checkState(0) == Qt.Checked:
                out.append(self.album_by_pk[pk])
            it += 1
        return out

    # ========================================================= helpers
    def _check_all(self, tree: QTreeWidget, state: bool, visible_only: bool = False) -> None:
        tree.blockSignals(True)
        it = QTreeWidgetItemIterator(tree)
        while it.value():
            item = it.value()
            if item.data(0, ROLE_KEY) is not None and not (visible_only and item.isHidden()):
                item.setCheckState(0, Qt.Checked if state else Qt.Unchecked)
            it += 1
        tree.blockSignals(False)
        tree.viewport().update()
        self._update_selection_label()

    def _on_item_changed(self, item, column) -> None:
        if column == 0:
            QTimer.singleShot(0, self._update_selection_label)

    def _mode(self) -> str:
        return "month" if self.tabs.currentIndex() == 0 else "album"

    def _keep_filter(self) -> Optional[Callable[[Asset], bool]]:
        media = self.media_combo.currentData()
        after = self._last_copy(self._mode()) if self.new_cb.isChecked() else None
        rng = self._range()
        source = self.date_combo.currentData()
        if media == MEDIA_ALL and after is None and rng is None:
            return None

        def keep(a: Asset) -> bool:
            if media == MEDIA_PHOTOS and a.is_video:
                return False
            if media == MEDIA_VIDEOS and not a.is_video:
                return False
            if after is not None and (a.added is None or a.added <= after):
                return False
            if rng is not None:
                d = asset_date(a, source)
                if d is None or not (rng[0] <= d.date() <= rng[1]):
                    return False
            return True
        return keep

    def _selected_assets(self) -> list[Asset]:
        if not self.library:
            return []
        if self._mode() == "month":
            assets = self._selected_month_assets()
        else:
            seen: set[int] = set()
            assets = []
            for al in self._selected_albums():
                for pk in al.asset_pks:
                    if pk in self.library.assets and pk not in seen:
                        seen.add(pk)
                        assets.append(self.library.assets[pk])
        keep = self._keep_filter()
        return [a for a in assets if keep(a)] if keep else assets

    def _current_plan(self) -> tuple[list[CopyJob], Path, str]:
        source = self.date_combo.currentData()
        edited, live, tidy = self.edited_cb.isChecked(), self.live_cb.isChecked(), self.tidy_cb.isChecked()
        keep = self._keep_filter()
        if self._mode() == "month":
            dest = Path(self.month_dest.text())
            return plan_by_month(self._selected_month_assets(), dest, source, edited, live,
                                 tidy=tidy, keep=keep, folder_style=self.folder_combo.currentData(),
                                 file_style=self.file_combo.currentData()), dest, "month"
        dest = Path(self.album_dest.text())
        return plan_by_album(self._selected_albums(), self.library.assets, dest, source, edited, live,
                             tidy=tidy, keep=keep, file_style=self.file_combo.currentData()), dest, "album"

    def _update_selection_label(self) -> None:
        self._update_list_hint()
        if not hasattr(self, "new_cb"):
            return
        last = self._last_copy(self._mode())
        self.new_cb.setText(f"Only new since last copy ({last:%d %b %Y %H:%M})" if last
                            else "Only new since last copy (no copy yet)")
        self.new_cb.setEnabled(last is not None and self.engine is None)
        if not self.library:
            self.selection_label.setText("Connect your iPhone first." if not self._busy else "Reading library…")
            self._update_buttons()
            return
        assets = self._selected_assets()
        extras = []
        if self.edited_cb.isChecked():
            n = sum(a.edited for a in assets)
            if n:
                extras.append(f"{n:,} edited")
        if self.live_cb.isChecked():
            n = sum(a.live and not a.is_video for a in assets)
            if n:
                extras.append(f"{n:,} Live")
        extra_txt = f"  (+ {', '.join(extras)})" if extras else ""
        vids = sum(a.is_video for a in assets)
        self.selection_label.setText(
            f"{len(assets):,} items{extra_txt}  ·  {len(assets) - vids:,} photos  ·  {vids:,} videos  ·  "
            f"{human_bytes(sum(a.size for a in assets))}")
        self._update_example()
        self._update_buttons()

    def _update_buttons(self) -> None:
        copying = self.engine is not None or self._waiting_resume
        self.start_btn.setEnabled(bool(self.library) and not copying and not self._busy)
        self.cancel_btn.setEnabled(copying)
        self.cancel_btn.setVisible(copying)
        self.connect_btn.setEnabled(not copying and not self._busy)
        self.connect_btn.setVisible(not self._busy)
        self.connect_btn.setText("Reconnect / Reload" if self.library else "Connect")
        for w in (self.tabs, self.date_combo, self.media_combo, self.folder_combo, self.file_combo, self.edited_cb, self.live_cb, self.tidy_cb,
                  self.verify_cb, self.heic_cb, self.resume_cb, self.workers_spin, self.range_cb,
                  self.range_from, self.range_to):
            w.setEnabled(not copying)

    # ============================================================ copy
    def start_copy(self) -> None:
        if not self.library or self.engine:
            return
        jobs, dest, mode = self._current_plan()
        if not jobs:
            nice_info(self, "Nothing to copy",
                                    "Tick at least one month or album first."
                                    + ("\n\n('Only new since last copy' is on: nothing new was added since then.)"
                                       if self.new_cb.isChecked() else ""), icon="help")
            return
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            nice_warn(self, "Destination", f"Cannot create the destination folder:\n{e}")
            return
        n_files = sum(1 for j in jobs if j.kind == "original")
        total = sum(j.size for j in jobs)
        speed = float(self.settings.value("last_speed", 0) or 0)
        est = f"\nEstimated time: about {human_time(total / speed)} (at your last speed)" if speed > 1e6 else ""
        notes = []
        if self.heic_cb.isChecked():
            notes.append("HEIC photos will be converted to JPG (not lossless).")
        if self.verify_cb.isChecked():
            notes.append("Every file is verified (slower).")
        fs = winutil.volume_filesystem(dest)
        fat_problem = fs.upper().startswith("FAT") and any(j.size > 4 * 1024 ** 3 for j in jobs)
        if fat_problem:
            notes.append("⚠ This drive is FAT32: videos over 4 GB will fail. Use an NTFS/exFAT drive.")
        if self.confirm_cb.isChecked():
            dlg = NiceDialog(
                self, "Start copying?",
                f"Copy {n_files:,} items (about {human_bytes(total)}) to\n{dest}{est}\n\n"
                "Files already there with the same name and size are skipped. You can stop any time with Cancel."
                + ("\n\n" + "\n".join(notes) if notes else ""),
                ok="Start Copy", cancel="Cancel", icon="arrow", checkbox="Don't ask me again")
            if dlg.exec() != QDialog.Accepted:
                return
            if dlg.checked():
                self.confirm_cb.setChecked(False)
                self.settings.setValue("confirm_start", "false")
        elif fat_problem and not nice_ask(
                self, "Videos over 4 GB will fail",
                "This drive is FAT32, which can't hold files over 4 GB, so large videos will fail.\n"
                "Use an NTFS or exFAT drive, or start anyway.", ok="Start Anyway", cancel="Cancel"):
            return
        need = sum(j.size for j in jobs if not j.dest.exists())
        free = shutil.disk_usage(dest).free
        if need > free:
            if not nice_ask(
                    self, "Not enough space",
                    f"The selection needs about {human_bytes(need)} but only {human_bytes(free)} is free on "
                    f"{dest.anchor}.\n\nStart anyway? (It will stop with errors when the disk is full.)",
                    ok="Start Anyway", cancel="Cancel", icon="warn"):
                return
        self._save_settings()
        self.copy_dest, self.copy_mode = dest, mode
        self._last_jobs = jobs
        sel = self._selected_assets()
        self._plan_newest = max((a.added for a in sel if a.added), default=None)
        self._resumes = 0
        self._start_engine()

    def _start_engine(self) -> None:
        self.engine = CopyEngine(self.hub, self._last_jobs, workers=self.workers_spin.value(),
                                 on_progress=self.bridge.progress.emit,
                                 verify=self.verify_cb.isChecked(), convert_heic=self.heic_cb.isChecked())
        self._log(f"Starting: {self.engine.p.total_files:,} files (+ extras) → {self.copy_dest}")
        self.progress_bar.setValue(0)
        winutil.keep_awake(True)
        self._update_buttons()
        fut = self.hub.submit(self.engine.run())

        def done(f):
            exc = f.exception()
            if exc:
                p = self.engine.p.snapshot() if self.engine else Progress()
                p.finished = True
                p.fatal = f"{type(exc).__name__}: {exc}"
                self.bridge.progress.emit(p)
        fut.add_done_callback(done)

    def cancel_copy(self) -> None:
        if self._waiting_resume:
            self._waiting_resume = False
            self._log("Stopped waiting for the iPhone.")
            winutil.keep_awake(False)
            self._update_buttons()
            return
        if self.engine:
            self.engine.cancel()
            self.cancel_btn.setEnabled(False)
            self._log("Cancelling… (finished files are kept; press Start Copy again later to continue)")

    def _on_progress(self, p: Progress) -> None:
        total = max(1, p.total_bytes)
        frac = min(1.0, (p.copied_bytes + p.skipped_bytes) / total) if p.total_bytes else (
            p.done_files / max(1, p.total_files))
        self.progress_bar.setValue(int(frac * 1000))
        self.progress_bar.setFormat(f"{frac * 100:.1f}%   ·   {p.done_files:,} / {p.total_files:,} files")
        self.selection_label.setText(f"Copying {p.done_files:,} of {p.total_files:,}")
        self.eta_label.setText(f"{human_time(p.eta)} left")
        self.speed_label.setText(f"{human_bytes(p.speed)}/s")
        extras = p.copied_edited + p.copied_live
        bits = [f"copied {p.copied_files:,}" + (f" +{extras:,} extras" if extras else "")
                + f" ({human_bytes(p.copied_bytes)})",
                f"already there {p.skipped_files:,}"]
        if p.verified_files:
            bits.append(f"verified {p.verified_files:,}")
        if p.converted_files:
            bits.append(f"→JPG {p.converted_files:,}")
        bits += [f"not on iPhone {len(p.missing):,}", f"errors {len(p.failed):,}"]
        self.stats_label.setText("  ·  ".join(bits))
        self.copy_bar.setToolTip("  ·  ".join(bits) + (f"\n{p.current}" if p.current else ""))
        if p.finished and self.engine is not None:
            self._copy_finished(p)

    def _copy_finished(self, p: Progress) -> None:
        self.engine = None
        avg = p.copied_bytes / p.elapsed if p.elapsed else 0
        if avg > 5e6 and p.copied_bytes > 200e6 and not self.verify_cb.isChecked():
            self.settings.setValue("last_speed", avg)
        fatal = (p.fatal or "").lower()
        disconnected = "disconnect" in fatal or "connection" in fatal
        if disconnected and self.resume_cb.isChecked() and not p.cancelled and self._resumes < 50:
            self._log(f"The iPhone disconnected after {p.copied_files:,} files. Waiting up to "
                      f"{RESUME_WAIT_MIN} min for it to come back… (unlock it and re-plug the cable)")
            self.speed_label.setText("Waiting…")
            self.stats_label.setText("The iPhone disconnected. Unlock it and re-plug the cable; "
                                     "the copy continues automatically.")
            self._wait_for_device()
            return
        winutil.keep_awake(False)
        self._update_buttons()
        head = "Cancelled" if p.cancelled else ("Stopped" if p.fatal else "Done")
        extra_n = p.copied_edited + p.copied_live
        parts = [f"{p.copied_files:,} photos/videos"]
        if p.copied_edited:
            parts.append(f"{p.copied_edited:,} edited versions")
        if p.copied_live:
            parts.append(f"{p.copied_live:,} Live Photo videos")
        what = " + ".join(parts)
        if extra_n:
            what = f"{p.copied_files + extra_n:,} files ({what})"
        summary = (f"{head}: copied {what}, {human_bytes(p.copied_bytes)} in "
                   f"{human_time(p.elapsed)}, average {human_bytes(avg)}/s. "
                   f"Already there: {p.skipped_files:,}"
                   + (f" (+{p.skipped_extra:,} extras)" if p.skipped_extra else "")
                   + f". Not on iPhone (iCloud only): {len(p.missing):,}. Errors: {len(p.failed):,}.")
        if p.verified_files:
            summary += f" Verified identical: {p.verified_files:,}."
        if p.converted_files:
            summary += f" Converted to JPG: {p.converted_files:,}."
        self._log(summary)
        if p.fatal:
            self._log("Problem: " + p.fatal)
        if head == "Done" and not p.failed and self._plan_newest:
            key = self._last_copy_key(self.copy_mode)
            prev = self._last_copy(self.copy_mode)
            if key and (prev is None or self._plan_newest > prev):
                self.settings.setValue(key, self._plan_newest.isoformat())
            self._update_selection_label()
        report = self._write_report(p, summary)
        self.speed_label.setText(f"{human_bytes(avg)}/s avg")
        self.stats_label.setText(summary)
        self._notify(head, f"Copied {p.copied_files:,} items" + (f", {len(p.failed):,} errors" if p.failed else ""))
        msg = summary
        if p.fatal:
            msg += f"\n\nProblem: {p.fatal}\nReconnect the iPhone and press Start Copy again; copied files are skipped."
        if p.missing:
            msg += "\n\nItems 'not on iPhone' are stored only in iCloud. See Help > What it can't do."
        if report:
            msg += f"\n\nReport saved to:\n{report}"
        done = NiceDialog(self, head, msg, ok="Open Folder", cancel="Close",
                          icon="warn" if (p.fatal or p.failed) else "check")
        if done.exec() == QDialog.Accepted and self.copy_dest:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.copy_dest)))

    # ---------------------------------------------------- auto resume
    def _wait_for_device(self) -> None:
        self._waiting_resume = True
        self._update_buttons()
        serial = self.device.serial if self.device else None

        def work():
            deadline = time.monotonic() + RESUME_WAIT_MIN * 60
            while self._waiting_resume and time.monotonic() < deadline:
                time.sleep(5)
                if not self._waiting_resume:
                    return
                try:
                    info = self.hub.call(self.hub.connect(), timeout=100)
                except Exception:
                    continue
                if serial and info.serial != serial:
                    continue
                self.bridge.resume_ready.emit(True)
                return
            if self._waiting_resume:
                self.bridge.resume_ready.emit(False)

        threading.Thread(target=work, daemon=True, name="resume").start()

    def _on_resume_ready(self, ok: bool) -> None:
        if not self._waiting_resume:
            return
        self._waiting_resume = False
        if ok:
            self._resumes += 1
            self._log(f"iPhone is back. Resuming (attempt {self._resumes})…")
            self._start_engine()
        else:
            winutil.keep_awake(False)
            self._update_buttons()
            self._log("The iPhone did not come back. Reconnect it and press Start Copy again; copied files are skipped.")
            self._notify("Copy stopped", "The iPhone disconnected.")
            nice_warn(self, "Copy stopped",
                                "The iPhone disconnected and did not come back within "
                                f"{RESUME_WAIT_MIN} minutes.\n\nReconnect it and press Start Copy again. "
                                "Already copied files are skipped.\nTroubleshoot can help find the cause.")

    def _notify(self, title: str, text: str) -> None:
        QApplication.alert(self, 0)
        try:
            if self.tray is None and QSystemTrayIcon.isSystemTrayAvailable():
                icon = self.windowIcon()
                if icon.isNull():
                    icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
                self.tray = QSystemTrayIcon(icon, self)
                self.tray.show()
            if self.tray and not self.isActiveWindow():
                self.tray.showMessage(f"{APP_NAME}: {title}", text, QSystemTrayIcon.Information, 8000)
        except Exception:
            log.exception("notify")

    def _write_report(self, p: Progress, summary: str) -> Optional[Path]:
        if not self.copy_dest or (not p.missing and not p.failed):
            return None
        path = self.copy_dest / f"_transfer_report_{dt.datetime.now():%Y%m%d_%H%M%S}.txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(summary + "\n\n")
                if p.missing:
                    f.write(f"Not on the iPhone ({len(p.missing)}) - these are stored only in iCloud\n"
                            "('Optimize iPhone Storage'). On the iPhone choose Settings > Apps > Photos >\n"
                            "'Download and Keep Originals', wait until done, then run the copy again.\n")
                    f.writelines(f"  {m}\n" for m in p.missing)
                    f.write("\n")
                if p.failed:
                    f.write(f"Errors ({len(p.failed)}) - press Start Copy again to retry these\n")
                    f.writelines(f"  {n}: {e}\n" for n, e in p.failed)
            return path
        except OSError:
            log.exception("report")
            return None

    # ============================================================ doctor
    def run_doctor(self) -> None:
        if self.engine or self._waiting_resume:
            nice_info(self, "Troubleshoot", "Wait until the copy has finished.", icon="wait")
            return
        if not self.doctor_btn.isEnabled():
            return
        self.doctor_btn.setEnabled(False)
        self.doctor_btn.setText("Checking…")
        self.doctor_hint.hide()
        self.doctor_panel.show()
        while self.doctor_list.count() > 1:
            it = self.doctor_list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._doctor_rows: dict[str, QWidget] = {}
        dest = Path(self.month_dest.text() if self._mode() == "month" else self.album_dest.text())

        def work():
            try:
                res = doctor.run_all(self.hub, dest, self.bridge.doctor_result.emit)
            except Exception as e:
                log.exception("doctor")
                res = [doctor.Check("Troubleshoot", doctor.FAIL, f"{type(e).__name__}: {e}")]
                self.bridge.doctor_result.emit(res[0])
            self.bridge.doctor_done.emit(res)

        threading.Thread(target=work, daemon=True, name="doctor").start()

    def _on_doctor_result(self, c: doctor.Check) -> None:
        icon = {doctor.OK: "check", doctor.WARN: "warn", doctor.FAIL: "fail", doctor.INFO: "wait",
                doctor.SKIP: "skip"}[c.status]
        color = {doctor.OK: self.c["ok"], doctor.WARN: self.c["warn"], doctor.FAIL: self.c["fail"]}.get(
            c.status, self.c["muted"])
        f, lay = card()
        lay.setContentsMargins(14, 10, 14, 10)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, color, 24))
        ic.setStyleSheet("background: transparent;")
        ic.setFixedWidth(34)
        top.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        t = label(f"<b>{c.title}</b>", "")
        col.addWidget(t)
        d = label(c.detail, "", wrap=True)
        d.setStyleSheet(f"color: {color}; background: transparent;" if c.status in (doctor.WARN, doctor.FAIL) else "background: transparent;")
        col.addWidget(d)
        for step in c.fix:
            col.addWidget(label(f"→ {step}", "", wrap=True))
        if c.action == "store":
            b = QPushButton("Get Apple Devices (Microsoft Store)")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(doctor.APPLE_DEVICES_STORE)))
            col.addWidget(b, 0, Qt.AlignLeft)
        elif c.action == "restart_service":
            b = QPushButton("Restart Apple Service")
            b.clicked.connect(self._restart_service)
            col.addWidget(b, 0, Qt.AlignLeft)
        elif c.action == "thispc":
            b = QPushButton("Open This PC")
            b.clicked.connect(lambda: self._open_link("explorer:thispc"))
            col.addWidget(b, 0, Qt.AlignLeft)
        elif c.action == "device_manager":
            b = QPushButton("Open Device Manager")
            b.clicked.connect(lambda: winutil.run_hidden(["cmd", "/c", "start", "devmgmt.msc"]))
            col.addWidget(b, 0, Qt.AlignLeft)
        top.addLayout(col, 1)
        lay.addLayout(top)
        old = self._doctor_rows.get(c.title)
        if old is not None:
            idx = self.doctor_list.indexOf(old)
            self.doctor_list.removeWidget(old)
            old.deleteLater()
            self.doctor_list.insertWidget(idx, f)
        else:
            self.doctor_list.insertWidget(self.doctor_list.count() - 1, f)
        self._doctor_rows[c.title] = f

    def _on_doctor_done(self, results: list) -> None:
        self._doctor_results = results
        self.doctor_btn.setEnabled(True)
        self.doctor_btn.setText("Run Checks Again")
        final = [r for r in results if r.status != doctor.INFO]
        fails = [r for r in final if r.status == doctor.FAIL]
        warns = [r for r in final if r.status == doctor.WARN]
        if fails:
            text = f"❌  Found {len(fails)} problem(s). Fix the first ❌ below, then run the checks again."
        elif warns:
            text = "⚠️  It should work. Have a look at the warnings below."
        else:
            text = "✅  Everything looks good. Go to Connect and press Connect."
        f, lay = card()
        lay.addWidget(label(text, "h2", wrap=True))
        self.doctor_list.insertWidget(0, f)
        self._doctor_rows["__summary__"] = f
        self.doctor_area.verticalScrollBar().setValue(0)

    def _open_link(self, url: str) -> None:
        if url == "explorer:thispc":
            winutil.run_hidden(["explorer.exe", "shell:MyComputerFolder"])
        else:
            QDesktopServices.openUrl(QUrl(url))

    @staticmethod
    def _tidy_columns(tree: QTreeWidget) -> None:
        h = tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, tree.columnCount()):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            tree.setColumnWidth(c, 105)
            tree.headerItem().setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)

    def _copy_doctor_report(self) -> None:
        if not self._doctor_results:
            nice_info(self, "Copy Report", "Run the checks first.", icon="help")
            return
        QGuiApplication.clipboard().setText(doctor.report_text(self._doctor_results, __version__))
        nice_info(self, "Copy Report",
                                "The report is on the clipboard. Paste it into a note to keep it, or search "
                                "online for the problem it shows.\n\niPhoneTransfer is shared as-is, without "
                                "support or updates. The Help page and the steps here fix most problems.")

    def _restart_service(self) -> None:
        cmd = (f'/c net stop "{doctor.APPLE_SERVICE}" & net start "{doctor.APPLE_SERVICE}"')
        if winutil.run_elevated("cmd.exe", cmd):
            nice_info(self, "Restart Apple Service",
                                    "Restarting the Apple service… Wait about 10 seconds, re-plug the iPhone, "
                                    "then press Connect (or run the checks again).")
        else:
            nice_warn(self, "Restart Apple Service",
                                "Could not restart the service (permission was not given, or it isn't installed).")

    # ============================================================ close
    def closeEvent(self, ev) -> None:
        if self.engine or self._waiting_resume:
            if not nice_ask(self, "Copy in progress", "A copy is running. Cancel it and quit?",
                            ok="Quit", cancel="Keep Copying", icon="warn"):
                ev.ignore()
                return
            self._waiting_resume = False
            if self.engine:
                self.engine.cancel()
        winutil.keep_awake(False)
        self._save_settings()
        try:
            self.hub.call(self.hub.disconnect(), timeout=5)
        except Exception:
            pass
        ev.accept()


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def run() -> int:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("iPhoneTransfer")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # the watercolour images are big; with Qt's default 10 MB cache they are re-read from disk on every
    # restyle (after each window resize), which froze the window for ~0.4 s
    QPixmapCache.setCacheLimit(256 * 1024)
    art.init(resource_path(""))
    theme.apply(app, art.path("ui/skin") if art.exists("ui/skin/nav-button_v1_normal.png") else None)
    if art.exists("app.ico"):
        app.setWindowIcon(QIcon(art.path("app.ico")))
    w = MainWindow()
    w.show()
    return app.exec()