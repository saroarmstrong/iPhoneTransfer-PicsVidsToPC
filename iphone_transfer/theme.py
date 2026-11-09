"""Watercolor Indigo theme with floating translucent cards and paint-washed buttons."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#2C3E50"

def apply(app: QApplication, skin_dir: str | None = None) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.WindowText, QColor("#161E28"))
    pal.setColor(QPalette.Text, QColor("#161E28"))
    pal.setColor(QPalette.ButtonText, QColor("#161E28"))
    pal.setColor(QPalette.Highlight, QColor("#3D566E"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor("#708090"))
    app.setPalette(pal)
    global _SKIN_DIR
    _SKIN_DIR = skin_dir
    app.setStyleSheet(full_stylesheet(1.0))


_SKIN_DIR: str | None = None
# plain look (a build without the artwork pack): make tick boxes visible
_PLAIN = """
    QCheckBox::indicator, QTreeWidget::indicator { width: 14px; height: 14px; border: 1.5px solid #4B5E70;
        border-radius: 3px; background: #FFFFFF; }
    QCheckBox::indicator:checked, QTreeWidget::indicator:checked { background: #2C3E50; }
    QCheckBox::indicator:indeterminate, QTreeWidget::indicator:indeterminate { background: #9AA8B5; }
    QFrame#dlgCard { background: #FFFFFF; border: 1px solid #9AA8B5; border-radius: 10px; }
    QLabel#dlgTitle { font-size: 12pt; font-weight: 700; }
"""
_LAST_SCALE = 1.0


def full_stylesheet(f: float = 1.0) -> str:
    css = stylesheet() + (skin_stylesheet(_SKIN_DIR) if _SKIN_DIR else _PLAIN)
    return scale_css(css, f)


def scale_css(css: str, f: float) -> str:
    """Multiply every pt / px length by f, so the whole UI grows and shrinks with the window like the mockup."""
    import re
    if abs(f - 1.0) < 0.005:
        return css

    def one(m):
        v, unit = float(m.group(1)), m.group(2)
        if unit == "pt":
            return f"{v * f:.1f}pt"
        return f"{max(1, round(v * f)) if v > 0 else 0}px"
    return re.sub(r"(?<![\w#.])(\d+(?:\.\d+)?)(pt|px)", one, css)


def apply_scale(app: QApplication, f: float) -> None:
    global _LAST_SCALE
    if abs(f - _LAST_SCALE) < 0.03:          # restyling is slow; skip tiny size changes
        return
    _LAST_SCALE = f
    app.setStyleSheet(full_stylesheet(f))


def colors() -> dict:
    return {
        "side": "transparent",
        "ok": "#1E9E4A",
        "warn": "#C77700",
        "fail": "#D83B30",
        "muted": "#4B5E70",
    }


def stylesheet() -> str:
    return f"""
    QWidget {{
        font-family: "Segoe UI", -apple-system, sans-serif;
        font-size: 9pt;
        color: #161E28;
    }}

    QMainWindow, QWidget#page, QScrollArea, QStackedWidget {{
        background: transparent;
    }}

    /* 1. SIDEBAR: Frosted translucent strip */
    QListWidget#sidebar {{
        background: rgba(245, 248, 252, 140);
        border: none;
        border-right: 1.5px solid rgba(255, 255, 255, 180);
        padding: 14px 8px;
        outline: 0;
        font-size: 10.5pt;
    }}

    QListWidget#sidebar::item {{
        background: rgba(255, 255, 255, 130);
        border: 1px solid rgba(185, 202, 218, 140);
        padding: 9px 12px;
        border-radius: 12px;
        margin: 4px 2px;
        color: #161E28;
    }}

    QListWidget#sidebar::item:hover {{
        background: rgba(255, 255, 255, 210);
        border: 1px solid rgba(130, 165, 195, 200);
    }}

    QListWidget#sidebar::item:selected {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(58, 79, 99, 210), stop:1 rgba(30, 43, 55, 220));
        color: #FFFFFF;
        border: none;
    }}

    /* 2. FLOATING TRANSLUCENT CARDS (Lower opacity lets the painting breathe) */
    QFrame#card {{
        background: rgba(247, 249, 252, 190);
        border: 1.5px solid rgba(255, 255, 255, 220);
        border-radius: 18px;
    }}

    QLabel#h1 {{ font-size: 17pt; font-weight: 700; color: #101720; background: transparent; }}
    QLabel#h2 {{ font-size: 12pt; font-weight: 600; color: #101720; background: transparent; }}
    QLabel#big {{ font-size: 14pt; font-weight: 600; color: #101720; background: transparent; }}
    QLabel#muted {{ color: #34414E; background: transparent; }}
    QLabel#speed {{ font-size: 18pt; font-weight: 700; color: #243342; background: transparent; }}

    /* 3. WATERCOLOR PILL BUTTONS (Soft pigment washes with organic rims) */
    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(255, 255, 255, 210),
            stop:0.8 rgba(235, 243, 250, 160),
            stop:1 rgba(205, 220, 235, 180));
        border: 1.5px solid rgba(155, 180, 205, 160);
        border-radius: 12px;
        padding: 6px 16px;
        color: #141D26;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background: rgba(255, 255, 255, 240);
        border: 1.5px solid rgba(100, 145, 180, 220);
    }}

    QPushButton:pressed {{
        background: rgba(210, 225, 240, 200);
    }}

    /* Primary Start copy button: Clean White Gouache block */
    QPushButton#primary {{
        background: #FFFFFF;
        color: #101720;
        border: 2px solid rgba(255, 255, 255, 255);
        border-radius: 14px;
        font-weight: 700;
        padding: 9px 24px;
        font-size: 11pt;
    }}

    QPushButton#primary:hover {{
        background: #F0F4F8;
    }}

    /* 4. TREE WIDGET (Transparent background so tree lines don't form a white wall) */
    QTreeWidget {{
        background: rgba(255, 255, 255, 228);
        border: 1.5px solid rgba(195, 210, 225, 200);
        border-radius: 12px;
        padding: 4px;
        color: #141D26;
    }}

    QTreeWidget::item {{ padding: 3px 0px; color: #141D26; }}

    QTreeWidget::item:selected {{
        background-color: rgba(44, 62, 80, 190);
        color: #FFFFFF;
        border-radius: 6px;
    }}

    QHeaderView::section {{
        background: rgba(236, 242, 248, 245);
        border: none;
        border-bottom: 1px solid rgba(195, 210, 225, 170);
        padding: 6px;
        font-weight: 600;
        color: #141D26;
    }}

    QLineEdit, QComboBox, QSpinBox, QDateEdit {{
        background-color: rgba(255, 255, 255, 240);
        border: 1.5px solid rgba(120, 140, 160, 170);
        border-radius: 8px;
        padding: 4px 8px;
        color: #141D26;
    }}

    QPlainTextEdit, QTextBrowser {{
        background-color: rgba(255, 255, 255, 190);
        border: 1.5px solid rgba(195, 210, 225, 140);
        border-radius: 10px;
        color: #141D26;
    }}

    /* 5. TABS */
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        padding: 3px 14px;
        margin-right: 4px;
        font-size: 9pt;
        background: rgba(248, 250, 252, 200);
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        border: none;
        border-bottom: 2px solid transparent;
        color: #4B5E70;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        border-bottom: 3px solid #243342;
        color: #101720;
    }}

    /* 6. PROGRESS BAR: Recessed Slate Trough & Crisp White Bar */
    QProgressBar {{
        border: 1px solid rgba(0, 0, 0, 25);
        border-radius: 6px;
        background-color: rgba(30, 42, 56, 110);
        height: 10px;
        text-align: center;
        color: #FFFFFF;
    }}

    QProgressBar::chunk {{
        border-radius: 6px;
        background-color: #FFFFFF;
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(60, 76, 92, 120); border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(60, 76, 92, 180); }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: rgba(60, 76, 92, 120); border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QCheckBox {{
        background: transparent;
        color: #141D26;
        spacing: 8px;
    }}
    """

# ---------------------------------------------------------------- Set 3 watercolor skin (v1 PNGs, 2x)
# Each entry: (file stem, image slice top/right/bottom/left in PNG pixels, widget border top/right/bottom/left).
# Slices cover the transparent padding plus the brush rim, so corners stay intact while the centre stretches.
SKIN_VERSION = "v1"


def _url(base: str, stem: str, state: str) -> str:
    return f"{base}/{stem}_{SKIN_VERSION}_{state}.png"


def _bi(base: str, stem: str, state: str, sl: tuple, bw: tuple) -> str:
    t, r, b, l = sl
    return (f'border-image: url("{_url(base, stem, state)}") {t} {r} {b} {l} stretch stretch; '
            f'border-width: {bw[0]}px {bw[1]}px {bw[2]}px {bw[3]}px;')


SLICES = {
    #  name            slice (t, r, b, l)       border (t, r, b, l)
    "sidebar-panel": ((90, 90, 90, 90), (18, 12, 18, 12)),
    "nav-button":    ((60, 64, 72, 66), (14, 16, 16, 16)),
    "tile-button":   ((60, 60, 70, 60), (14, 14, 16, 14)),
    "start-button":  ((64, 64, 72, 64), (14, 16, 16, 16)),
    "card-status":   ((64, 64, 72, 64), (12, 14, 14, 14)),
    "card-speed":    ((64, 64, 72, 64), (12, 14, 14, 14)),
    "card-daterange": ((64, 64, 72, 64), (12, 14, 14, 14)),
    "card-device":   ((64, 64, 72, 64), (12, 14, 14, 14)),
    "start-white":   ((64, 64, 72, 64), (14, 16, 16, 16)),
    "card-white":    ((64, 64, 72, 64), (12, 14, 14, 14)),
    "start-paper":   ((48, 52, 48, 52), (12, 14, 12, 14)),
    "card-pearl":    ((64, 64, 72, 64), (12, 14, 14, 14)),
}


def skin_stylesheet(base: str) -> str:
    from . import art
    if not QFile.exists(f"{base}/nav-button_{SKIN_VERSION}_normal.png"):
        return ""

    def ui(stem: str) -> str:        # high-contrast checkboxes live next to set3: assets/ui
        return art.path(f"ui/{stem}.png") or ""

    def wb(state: str) -> str:       # Start Copy: white paper with a darker, uneven rim (mockup; png set 1 element)
        return bi("start-paper", state)

    def small(stem: str, state: str, bw: str = "7px 9px 8px 9px") -> str:   # Set 3 element, thin rim
        sl = SLICES[stem][0]
        return (f'border-image: url("{_url(base, stem, state)}") {sl[0]} {sl[1]} {sl[2]} {sl[3]} stretch stretch; '
                f'border-width: {bw}; border-radius: 0px; background: transparent;')

    def bi(stem: str, state: str = "normal") -> str:
        sl, bw = SLICES[stem]
        return _bi(base, stem, state, sl, bw)

    soft = ui("sidebar-panel_soft")          # Set 3 panel at 80% opacity, so the painting shows through a little
    sl, bw = SLICES["sidebar-panel"]
    css = [f'QFrame#sidebarPanel {{ border-image: url("{soft}") {sl[0]} {sl[1]} {sl[2]} {sl[3]} stretch stretch; '
           f'border-width: {bw[0]}px {bw[1]}px {bw[2]}px {bw[3]}px; background: transparent; }}']
    css.append(f"""
    QPushButton#navButton {{ {bi('nav-button')} background: transparent; padding: 2px 6px;
        min-height: 26px; text-align: left; font-size: 10pt; font-weight: 600; color: #1C242D; }}
    QPushButton#navButton:hover {{ {bi('nav-button', 'hover')} }}
    QPushButton#navButton:pressed {{ {bi('nav-button', 'pressed')} }}
    QPushButton#navButton:checked {{ {bi('nav-button', 'selected')} color: #101720; }}

    QToolButton#tileButton {{ {bi('tile-button')} background: transparent; padding: 0px;
        min-width: 44px; min-height: 44px; font-size: 8.5pt; font-weight: 600; color: #1C242D; }}
    QToolButton#tileButton:hover {{ {bi('tile-button', 'hover')} }}
    QToolButton#tileButton:pressed {{ {bi('tile-button', 'pressed')} }}
    QToolButton#tileButton:checked {{ {bi('tile-button', 'selected')} }}

    QPushButton#startButton {{ {wb('normal')} background: transparent; padding: 0px 14px;
        min-height: 22px; min-width: 110px; font-size: 11pt; font-weight: 700; color: #101720; }}
    QPushButton#startButton:hover {{ {wb('hover')} }}
    QPushButton#startButton:pressed {{ {wb('pressed')} }}
    QPushButton#startButton:disabled {{ color: rgba(16, 23, 32, 150); }}

    QFrame#cardStatus, QFrame#cardSpeed, QFrame#cardTop {{ {bi('card-pearl')} background: transparent;
        border-radius: 0px; }}
    QFrame#cardDaterange {{ {bi('card-daterange')} background: transparent; }}
    QFrame#cardDevice {{ {bi('card-device')} background: transparent; }}
    QFrame#cardBar {{ {bi('card-daterange')} background: transparent; }}

    QLabel#brand {{ font-size: 13pt; font-weight: 700; color: #101720; background: transparent; padding-left: 8px; }}
    QLabel#cardTitle {{ font-size: 11pt; font-weight: 600; color: #1C242D; background: transparent; }}
    QLabel#cardSub {{ font-size: 9pt; color: #34414E; background: transparent; padding-left: 0px; }}
    QFrame#sidebarPanel QLabel#cardSub {{ padding-left: 8px; }}
    QLabel#cardBig {{ font-size: 14pt; font-weight: 700; color: #1C242D; background: transparent; }}
    QLabel#barTitle {{ font-size: 10.5pt; font-weight: 700; color: #1C242D; background: transparent; }}
    QFrame#whiteBlock, QFrame#card {{ {bi('card-white')} background: transparent; border-radius: 0px; }}

    QPushButton {{ {small('nav-button', 'hover')} padding: 2px 10px; min-height: 18px; font-weight: 600; }}
    QPushButton:hover {{ {small('nav-button', 'selected')} }}
    QPushButton:pressed {{ {small('nav-button', 'pressed')} }}
    QPushButton:disabled {{ color: rgba(20, 29, 38, 110); }}
    QPushButton#primary {{ {small('start-white', 'normal')} padding: 2px 10px; min-height: 18px;
        font-size: 9pt; font-weight: 700; color: #101720; }}
    QPushButton#primary:hover {{ {small('start-white', 'hover')} }}
    QPushButton#primary:pressed {{ {small('start-white', 'pressed')} }}

    QLineEdit, QComboBox, QSpinBox, QDateEdit {{ {small('nav-button', 'hover', '6px 8px 7px 8px')}
        padding: 0px 4px; }}
    QSpinBox {{ padding: 0px 2px; min-width: 40px; }}
    QAbstractSpinBox QLineEdit, QComboBox QLineEdit {{ border-image: none; border: none; background: transparent;
        padding: 0px; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 18px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{ui('chevron_down')}"); width: 11px; height: 11px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 14px; }}
    QSpinBox::up-arrow {{ image: url("{ui('chevron_up')}"); width: 9px; height: 9px; }}
    QSpinBox::down-arrow {{ image: url("{ui('chevron_down')}"); width: 9px; height: 9px; }}
    QComboBox {{ min-height: 20px; }}
    QFrame#dlgCard {{ border-image: url("{_url(base, 'card-dialog', 'normal')}") 64 64 72 64 stretch stretch;
        border-width: 12px 14px 14px 14px; background: transparent; }}
    QLabel#dlgTitle {{ font-size: 12.5pt; font-weight: 700; color: #101720; background: transparent; }}
    QLabel#dlgBody {{ font-size: 9.5pt; color: #1C242D; background: transparent; }}
    QPushButton#dlgOk {{ border-image: url("{_url(base, 'start-button', 'normal')}") 64 64 72 64 stretch stretch;
        border-width: 8px 10px 9px 10px; background: transparent; border-radius: 0px; padding: 4px 22px;
        min-height: 22px; font-weight: 700; color: #101720; }}
    QPushButton#dlgOk:hover {{ border-image: url("{_url(base, 'start-button', 'hover')}") 64 64 72 64 stretch stretch; }}
    QPushButton#dlgOk:pressed {{ border-image: url("{_url(base, 'start-button', 'pressed')}") 64 64 72 64 stretch stretch; }}
    QPushButton#dlgCancel {{ border-image: url("{_url(base, 'nav-button', 'normal')}") 60 64 72 66 stretch stretch;
        border-width: 7px 9px 8px 9px; background: transparent; border-radius: 0px; padding: 3px 16px;
        min-height: 22px; font-weight: 600; color: #34414E; }}
    QPushButton#dlgCancel:hover {{ border-image: url("{_url(base, 'nav-button', 'hover')}") 60 64 72 66 stretch stretch; }}
    QPushButton#dlgCancel:pressed {{ border-image: url("{_url(base, 'nav-button', 'pressed')}") 60 64 72 66 stretch stretch; }}
    QCalendarWidget#pearlCal {{ border-image: url("{_url(base, 'card-pearl', 'normal')}") 64 64 72 64 stretch stretch;
        border-width: 12px 14px 14px 14px; background: transparent; }}
    QCalendarWidget#pearlCal QWidget {{ background: transparent; border: none; border-image: none; }}
    QCalendarWidget#pearlCal QAbstractItemView {{ background: transparent; selection-background-color: transparent; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: transparent; border: none; }}
    QCalendarWidget QToolButton {{ border-image: none; background: transparent; border: none; color: #1C242D;
        font-size: 10.5pt; font-weight: 700; padding: 3px 6px; margin: 2px; }}
    QCalendarWidget QToolButton:hover {{ background: rgba(60, 76, 92, 28); border-radius: 6px; }}
    QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0px; }}
    QCalendarWidget QToolButton#qt_calendar_prevmonth {{ qproperty-icon: url("{ui('chevron_left')}"); }}
    QCalendarWidget QToolButton#qt_calendar_nextmonth {{ qproperty-icon: url("{ui('chevron_right')}"); }}
    QCalendarWidget QSpinBox {{ border-image: none; background: #FFFFFF; border: 1px solid rgba(60, 76, 92, 90);
        border-radius: 4px; padding: 0px 2px; min-width: 0px; }}
    QCalendarWidget QMenu {{ background: #FBFAF6; color: #1C242D; border: 1px solid rgba(60, 76, 92, 90); }}
    QCalendarWidget QMenu::item:selected {{ background: #E4E8EC; }}
    QCalendarWidget QAbstractItemView {{ background: #FBFAF6; color: #1C242D; outline: 0;
        selection-background-color: #D5DCE3; selection-color: #101720; }}
    QCalendarWidget QAbstractItemView:disabled {{ color: #A7AEB5; }}
    QComboBox QAbstractItemView {{ background: #F7F9FB; border: 1px solid rgba(60, 76, 92, 90);
        selection-background-color: rgba(60, 76, 92, 40); selection-color: #141D26; }}

    QTabBar::tab {{ {small('nav-button', 'hover', '8px 11px 9px 11px')} padding: 2px 6px;
        min-width: 112px; max-width: 112px; min-height: 18px; margin-right: -7px; margin-bottom: -5px;
        font-size: 9.5pt; font-weight: 600; color: #34414E; }}
    QTabBar::tab:hover {{ {small('nav-button', 'pressed', '8px 11px 9px 11px')} }}
    QTabBar::tab:selected {{ {small('nav-button', 'selected', '8px 11px 9px 11px')} color: #101720; }}
    QTabWidget#optsPanel::pane, QTabWidget#listPanel::pane {{ {bi('card-white')} background: transparent;
        border-radius: 0px; top: -2px; }}
    QTabWidget::tab-bar {{ left: 6px; }}

    QTextBrowser, QPlainTextEdit {{ background: transparent; border: none; }}
    QTreeWidget#rows {{ background: transparent; border: none; padding: 0px 4px; }}
    QTreeWidget#rows::item {{ padding: 1px 0px; border: none; border-radius: 0px; }}
    QTreeWidget#rows::item:hover, QTreeWidget#rows::branch:hover {{ background: rgba(255, 255, 255, 110); }}
    QTreeWidget#rows::item:selected, QTreeWidget#rows::branch:selected {{
        background: rgba(255, 255, 255, 190); color: #141D26; border-radius: 0px; }}
    QTreeWidget#rows QHeaderView::section {{ background: transparent; border: none;
        border-bottom: 1px solid rgba(60, 76, 92, 90); padding: 2px 6px; font-weight: 600; }}
    QLabel#credit {{ font-size: 7.5pt; color: #34414E; background: transparent; }}
    QFrame[dark="true"] QLabel#credit {{ color: rgba(255, 255, 255, 225); }}
    QLabel#frostTitle {{ font-size: 11pt; font-weight: 400; color: #1C242D; background: transparent; }}
    QLabel#frostSub {{ font-size: 8.5pt; color: #34414E; background: transparent; }}
    QFrame[dark="true"] QLabel#frostTitle {{ color: #FFFFFF; }}
    QFrame[dark="true"] QLabel#frostSub {{ color: rgba(255, 255, 255, 220); }}
    QTabWidget#optsPanel QStackedWidget, QTabWidget#optsPanel QStackedWidget > QWidget,
    QTabWidget#listPanel QStackedWidget, QTabWidget#listPanel QStackedWidget > QWidget {{ background: transparent; }}

    QCheckBox::indicator, QTreeWidget::indicator {{ width: 18px; height: 18px; }}
    QCheckBox::indicator:unchecked, QTreeWidget::indicator:unchecked {{ image: url("{ui('checkbox_off')}"); }}
    QCheckBox::indicator:unchecked:hover, QTreeWidget::indicator:unchecked:hover {{ image: url("{ui('checkbox_off_hover')}"); }}
    QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{ image: url("{ui('checkbox_on')}"); }}
    QCheckBox::indicator:indeterminate, QTreeWidget::indicator:indeterminate {{ image: url("{ui('checkbox_partial')}"); }}
    """)
    return "\n".join(css)
