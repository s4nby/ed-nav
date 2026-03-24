# coord_window.py
# Standalone dark-themed coordinate input window.
# Always-on-top but NOT click-through, so the user can interact with it.
#
# Shows: current body name + auto-detected radius (from tracker NavResult),
#        Lat/Lon inputs with paste-parse support, Set/Clear buttons,
#        live tracking status.
#
# Closing the window hides it instead of destroying it (preserves state).

import json
import random
import re
from typing import Optional

from PyQt6.QtCore    import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSettings, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui     import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QRegion
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QScrollArea, QFrame, QDialog, QWidgetAction,
)


from constants import (
    COLOR_ERROR, COLOR_ORANGE,
    DEFAULT_PLANET_RADIUS_M,
    FONT_FAMILY,
    GITHUB_REPO,
    VERSION,
)

# ---------------------------------------------------------------------------
# Coord-window local style constants (ED-style theme)
# ---------------------------------------------------------------------------
_FONT        = "Segoe UI"    # Windows-native sans-serif — clean, professional
_FONT_MONO   = "Consolas"    # used for coordinate inputs so numbers stay aligned

_SZ_TITLE    = 12   # "SET TARGET" header
_SZ_LABEL    = 10   # field labels (BODY NAME, LATITUDE…)
_SZ_HINT     = 9    # hint / FSS hint text
_SZ_INPUT    = 10   # line-edit content
_SZ_STATUS   = 9    # status line
_SZ_BTN      = 10   # button text

# Orange palette — three tiers matching ED's UI hierarchy
_COL_ACTIVE  = "#FF8C00"   # bright — title, active elements
_COL_LABEL   = "#CC6600"   # mid    — field labels, button borders
_COL_DIM     = "#7A3D00"   # dim    — hints, inactive text
_COL_INPUT_BG = "#161616"  # input background
_COL_BORDER  = "#3D3D3D"   # global border color

# UI Dimensions
_TITLE_BAR_H      = 34
_SIDEBAR_ICON_W   = 48
_SIDEBAR_FULL_W   = 160
_SIDEBAR_HEADER_H = 34
_FIXED_W, _FIXED_H = 560, 678

from tracker import NavResult
from journal import LandableBody
from planet_preview import PlanetPreviewWidget
from tray import TrayIcon

# ---------------------------------------------------------------------------
# Animated app-icon button (sidebar toggle trigger)
# ---------------------------------------------------------------------------

class _AppIconButton(QWidget):
    """
    Shows the app icon at rest.  On hover, crossfades to a directional chevron
    that previews the *resulting* sidebar state (expand ▶ or collapse ◀).
    Clicking emits `clicked`.
    """

    clicked = pyqtSignal()

    _SZ = 18   # matches the QLabel it replaces

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SZ, self._SZ)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._sidebar_open  = False
        self._blend_val     = 0.0      # 0 = app icon, 1 = hint icon
        self._forced_hover  = False    # True when the title bar (parent) is hovered

        self._app_px = TrayIcon._make_icon().pixmap(self._SZ, self._SZ)

        self._anim = QPropertyAnimation(self, b"blend")
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ---- pyqtProperty (animatable) ----------------------------------------

    @pyqtProperty(float)
    def blend(self) -> float:
        return self._blend_val

    @blend.setter
    def blend(self, v: float) -> None:
        self._blend_val = v
        self.update()

    # ---- public API -------------------------------------------------------

    def set_sidebar_open(self, open: bool) -> None:
        self._sidebar_open = open
        if self._blend_val > 0.0:   # already showing hint — redraw immediately
            self.update()

    def set_forced_hover(self, forced: bool) -> None:
        """Called by the parent title bar to drive the hover state from a wider trigger area."""
        self._forced_hover = forced
        self._anim.stop()
        self._anim.setStartValue(self._blend_val)
        self._anim.setEndValue(1.0 if forced else 0.0)
        self._anim.start()

    # ---- hover ------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._blend_val)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._forced_hover:
            self._anim.stop()
            self._anim.setStartValue(self._blend_val)
            self._anim.setEndValue(0.0)
            self._anim.start()
        super().leaveEvent(event)

    # ---- click ------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ---- paint ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._blend_val < 1.0:
            p.setOpacity(1.0 - self._blend_val)
            p.drawPixmap(0, 0, self._app_px)

        if self._blend_val > 0.0:
            p.setOpacity(self._blend_val)
            self._draw_hint(p)

        p.end()

    def _draw_hint(self, p: QPainter) -> None:
        """Chevron + vertical bar indicating the action that will be performed."""
        pen = QPen(QColor(_COL_ACTIVE), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Vertical bar on the left edge
        p.drawLine(QPointF(3, 3), QPointF(3, 15))

        if self._sidebar_open:
            # Sidebar is open → hint: collapse (chevron points LEFT ‹)
            p.drawLine(QPointF(13, 4), QPointF(7,  9))
            p.drawLine(QPointF(7,  9), QPointF(13, 14))
        else:
            # Sidebar is closed → hint: expand (chevron points RIGHT ›)
            p.drawLine(QPointF(7,  4), QPointF(13, 9))
            p.drawLine(QPointF(13, 9), QPointF(7,  14))


# ---------------------------------------------------------------------------
# Custom title bar
# ---------------------------------------------------------------------------

class _TitleBar(QWidget):
    """Draggable title bar with centered app name and window controls."""

    update_clicked = pyqtSignal()
    icon_clicked   = pyqtSignal()

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(_TITLE_BAR_H)
        self.setStyleSheet(
            f"background: #202020;"
            f" border: none;"
            f" border-top: 1px solid {_COL_BORDER};"
            f" border-left: 1px solid {_COL_BORDER};"
            f" border-right: 1px solid {_COL_BORDER};"
            f" border-top-left-radius: 10px;"
            f" border-top-right-radius: 10px;"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Windows 11-style caption buttons and icon sizing.
        _btn_ss = (
            f"QPushButton {{ background: transparent; border: none;"
            f" color: #CFCFCF; font-size: 10px;"
            f" min-width: 46px; max-width: 46px;"
            f" min-height: 32px; max-height: 32px;"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: #2A2A2A; color: white; }}"
            f"QPushButton:pressed {{ background: #343434; color: white; }}"
        )
        _close_ss = (
            f"QPushButton {{ background: transparent; border: none;"
            f" color: #CFCFCF; font-size: 10px;"
            f" min-width: 46px; max-width: 46px;"
            f" min-height: 32px; max-height: 32px;"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: #C42B1C; color: white; }}"
            f"QPushButton:pressed {{ background: #A82019; color: white; }}"
        )
        _update_ss = (
            f"QPushButton {{ background: transparent; border: none;"
            f" color: #FFCC00; font-size: 10px;"
            f" min-width: 36px; max-width: 36px;"
            f" min-height: 32px; max-height: 32px;"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: #2e2a00; color: #FFE566; }}"
            f"QPushButton:pressed {{ background: #252200; color: #FFCC00; }}"
        )

        # App icon — clicking it toggles the sidebar
        self._icon_btn = _AppIconButton(self)
        self._icon_btn.clicked.connect(self.icon_clicked)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_lbl.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet(
            f"color: {_COL_ACTIVE}; letter-spacing: 0.5px;"
            " background: transparent; border: none;"
        )

        self._update_btn = QPushButton()
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setStyleSheet(_update_ss)
        self._update_btn.setVisible(False)
        self._update_btn.setToolTip("Update available! Click to open download page.")
        # We'll use a _NavIcon inside this button
        up_icon_lay = QHBoxLayout(self._update_btn)
        up_icon_lay.setContentsMargins(0, 0, 0, 0)
        self._up_icon = _NavIcon(_NavIcon.UPDATE, self._update_btn)
        self._up_icon.set_color("#FFCC00")
        up_icon_lay.addWidget(self._up_icon, 0, Qt.AlignmentFlag.AlignCenter)
        self._update_btn.clicked.connect(self.update_clicked)

        self._min_btn   = QPushButton("\uE921")
        self._max_btn   = QPushButton("\uE922")
        self._close_btn = QPushButton("\uE8BB")

        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Segoe Fluent Icons", 10))
        self._min_btn.setStyleSheet(_btn_ss)
        self._max_btn.setStyleSheet(_btn_ss)
        self._close_btn.setStyleSheet(_close_ss)

        layout.addWidget(self._icon_btn)
        layout.addSpacing(8)
        layout.addWidget(title_lbl)
        layout.addStretch(1)
        layout.addWidget(self._update_btn)
        layout.addSpacing(4)
        layout.addWidget(self._min_btn)
        layout.addWidget(self._max_btn)
        layout.addWidget(self._close_btn)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        gradient = QLinearGradient(0, self.height() - 10, 0, self.height())
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 30))
        p.fillRect(QRect(1, self.height() - 10, self.width() - 2, 10), gradient)
        p.end()

    def set_sidebar_open(self, open: bool) -> None:
        self._icon_btn.set_sidebar_open(open)

    # ---- drag-to-move ----

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            if not win.isMaximized():
                win.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:
        self._icon_btn.set_forced_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._icon_btn.set_forced_hover(False)
        super().leaveEvent(event)


# ---------------------------------------------------------------------------
# Eliding button — QPushButton that truncates its label with '...' on resize
# ---------------------------------------------------------------------------

class _ElidedButton(QPushButton):
    """QPushButton that elides its label to fit the available width."""

    _H_PAD   = 30         # total horizontal padding (12px × 2 from stylesheet)
    _CHEVRON = " \u25be"  # appended after elision, always visible beside the text


    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text
        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def sizeHint(self):
        hint = super().sizeHint()
        fm   = QFontMetrics(self.font())
        hint.setWidth(fm.horizontalAdvance(self._full_text + self._CHEVRON) + self._H_PAD)
        return hint

    def _refresh(self) -> None:
        fm         = QFontMetrics(self.font())
        chevron_w  = fm.horizontalAdvance(self._CHEVRON)
        available  = max(0, self.width() - self._H_PAD - chevron_w)
        elided     = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available)
        super().setText(elided + self._CHEVRON)


# ---------------------------------------------------------------------------
# Crisp 1px horizontal separator (bypasses QFrame/style-engine rendering)
# ---------------------------------------------------------------------------

class _Separator(QWidget):
    """1px horizontal rule painted directly — no QFrame style-engine involvement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setOpacity(0.3)
        p.fillRect(self.rect(), QColor(_COL_BORDER))
        p.end()


class _RoundedPanel(QWidget):
    """Paint and mask a panel so child widgets cannot bleed into square corners."""

    def __init__(
        self,
        bg_color: str,
        border_color: str | None = None,
        radius_tl: int = 10,
        radius_tr: int = 10,
        radius_br: int = 10,
        radius_bl: int = 10,
        parent=None,
    ):
        super().__init__(parent)
        self._bg_color = QColor(bg_color)
        self._border_color = QColor(border_color) if border_color else None
        self._radius_tl = radius_tl
        self._radius_tr = radius_tr
        self._radius_br = radius_br
        self._radius_bl = radius_bl
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _rounded_path(self, rect: QRectF) -> QPainterPath:
        left = rect.left()
        top = rect.top()
        right = rect.right()
        bottom = rect.bottom()

        tl = min(self._radius_tl, rect.width() / 2, rect.height() / 2)
        tr = min(self._radius_tr, rect.width() / 2, rect.height() / 2)
        br = min(self._radius_br, rect.width() / 2, rect.height() / 2)
        bl = min(self._radius_bl, rect.width() / 2, rect.height() / 2)

        path = QPainterPath()
        path.moveTo(left + tl, top)
        path.lineTo(right - tr, top)
        if tr:
            path.quadTo(right, top, right, top + tr)
        else:
            path.lineTo(right, top)
        path.lineTo(right, bottom - br)
        if br:
            path.quadTo(right, bottom, right - br, bottom)
        else:
            path.lineTo(right, bottom)
        path.lineTo(left + bl, bottom)
        if bl:
            path.quadTo(left, bottom, left, bottom - bl)
        else:
            path.lineTo(left, bottom)
        path.lineTo(left, top + tl)
        if tl:
            path.quadTo(left, top, left + tl, top)
        else:
            path.lineTo(left, top)
        path.closeSubpath()
        return path

    def _update_mask(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            self.clearMask()
            return
        path = self._rounded_path(QRectF(0, 0, self.width(), self.height()))
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mask()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._rounded_path(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        )
        painter.fillPath(path, self._bg_color)
        if self._border_color:
            pen = QPen(self._border_color, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(path)


class _SidebarPanel(_RoundedPanel):
    """Rounded overlay panel that visually matches the main window chrome."""

    def __init__(self, parent=None):
        super().__init__("#202020", radius_tl=0, radius_tr=0, radius_br=0, radius_bl=10, parent=parent)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        shadow_w = 12
        gradient = QLinearGradient(self.width() - shadow_w, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 30))
        p.fillRect(QRect(self.width() - shadow_w, 0, shadow_w, self.height()), gradient)
        p.end()


class _BookmarkDialog(QDialog):
    """Themed modal for manual bookmark entry with backdrop dismissal."""
    def __init__(self, parent=None, initial_data: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Bookmark")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Backdrop fills the parent window
        if parent:
            self.setGeometry(parent.window().geometry())
        else:
            self.setFixedSize(300, 400)

        self._initial_data = initial_data or {}
        self._data = None

        # Main layout holds the centered form
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self._form_box = QWidget()
        self._form_box.setFixedSize(300, 400)
        # Prevent clicks on the form box from being interpreted as backdrop clicks
        self._form_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        main_layout.addWidget(self._form_box, 0, Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self._form_box)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel("NEW BOOKMARK")
        header.setFont(QFont(_FONT, 12, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {_COL_ACTIVE}; letter-spacing: 2px; background: transparent;")
        layout.addWidget(header)

        self._name_in   = self._make_field("Bookmark Name", "e.g. My Secret Base")
        self._system_in = self._make_field("System Name", "e.g. Sol")
        self._body_in   = self._make_field("Body Name", "e.g. Earth")
        self._lat_in    = self._make_field("Latitude", "e.g. -22.45")
        self._lon_in    = self._make_field("Longitude", "e.g. 137.88")

        if initial_data:
            self._name_in[1].setText(initial_data.get("name", ""))
            self._system_in[1].setText(initial_data.get("system", ""))
            self._body_in[1].setText(initial_data.get("body", ""))
            self._lat_in[1].setText(str(initial_data.get("lat", "")))
            self._lon_in[1].setText(str(initial_data.get("lon", "")))

        layout.addWidget(self._name_in[0])
        layout.addWidget(self._name_in[1])
        layout.addWidget(self._system_in[0])
        layout.addWidget(self._system_in[1])
        layout.addWidget(self._body_in[0])
        layout.addWidget(self._body_in[1])
        layout.addWidget(self._lat_in[0])
        layout.addWidget(self._lat_in[1])
        layout.addWidget(self._lon_in[0])
        layout.addWidget(self._lon_in[1])

        layout.addStretch(1)

        btn_lay = QHBoxLayout()
        self._save_btn = CoordWindow._make_button("Save")
        self._save_btn.setDefault(True) # Bind Enter key
        self._save_btn.setAutoDefault(True)
        self._save_btn.clicked.connect(self._on_save)
        self._cancel_btn = CoordWindow._make_button("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(self._cancel_btn)
        btn_lay.addWidget(self._save_btn)
        layout.addLayout(btn_lay)

        # Focus the name field by default
        self._name_in[1].setFocus()

    def _has_unsaved_changes(self) -> bool:
        """Return True if any field differs from initial or is not empty."""
        curr = {
            "name":   self._name_in[1].text().strip(),
            "system": self._system_in[1].text().strip(),
            "body":   self._body_in[1].text().strip(),
            "lat":    self._lat_in[1].text().strip(),
            "lon":    self._lon_in[1].text().strip(),
        }
        if self._initial_data:
            for k, v in curr.items():
                init_val = str(self._initial_data.get(k, ""))
                if v != init_val:
                    return True
            return False
        return any(curr.values())

    def mousePressEvent(self, event):
        # Backdrop dismissal logic
        if not self._form_box.geometry().contains(event.position().toPoint()):
            if self._has_unsaved_changes():
                # Flash the border to indicate unsaved changes
                self._form_box.setStyleSheet("border: 1px solid #FF4422; border-radius: 8px;")
                QTimer.singleShot(500, lambda: self._form_box.setStyleSheet(""))
                event.accept()
                return
            self.reject()
        event.accept()
        super().mousePressEvent(event)

    def _make_field(self, label: str, placeholder: str):
        lbl = QLabel(label)
        lbl.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {_COL_LABEL}; background: transparent;")
        edit = CoordWindow._make_line_edit(placeholder)
        return lbl, edit

    def _on_save(self):
        name = self._name_in[1].text().strip()
        system = self._system_in[1].text().strip()
        body = self._body_in[1].text().strip()
        lat_txt = self._lat_in[1].text().strip()
        lon_txt = self._lon_in[1].text().strip()

        lat = _validate_coord(lat_txt, -90.0, 90.0)
        lon = _validate_coord(lon_txt, -180.0, 180.0)

        if not name: name = "Unnamed"
        if lat is None or lon is None:
            if lat is None: self._lat_in[1].setStyleSheet(self._lat_in[1].styleSheet().replace(_COL_LABEL, "#FF0000"))
            if lon is None: self._lon_in[1].setStyleSheet(self._lon_in[1].styleSheet().replace(_COL_LABEL, "#FF0000"))
            return

        self._data = {
            "name": name,
            "system": system or "Unknown",
            "body": body or "Unknown",
            "lat": lat,
            "lon": lon
        }
        self.accept()

    def get_data(self) -> dict | None:
        return self._data

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. Draw semi-transparent backdrop
        # We use a rounded rect to match the main app window's shape
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.fillPath(path, QColor(0, 0, 0, 160))

        # 2. Draw centered form box background
        box_rect = self._form_box.geometry()
        path = QPainterPath()
        path.addRoundedRect(QRectF(box_rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.fillPath(path, QColor("#131314"))
        p.setPen(QPen(QColor("#252525"), 1))
        p.drawPath(path)


# ---------------------------------------------------------------------------
# Bookmark Cards — Gallery items
# ---------------------------------------------------------------------------

class _BookmarkCard(QWidget):
    """Compact gallery card showing bookmark details."""
    clicked = pyqtSignal(dict)
    edit_clicked = pyqtSignal(dict)
    delete_clicked = pyqtSignal(dict)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self.setFixedSize(145, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_hovered = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        name_lbl = QLabel(data.get("name", "Unnamed"))
        name_lbl.setFont(QFont(_FONT, 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {_COL_ACTIVE}; background: transparent;")
        name_lbl.setWordWrap(True)
        layout.addWidget(name_lbl)

        sys_lbl = QLabel(data.get("system", "Unknown System"))
        sys_lbl.setFont(QFont(_FONT, 9))
        sys_lbl.setStyleSheet(f"color: {_COL_LABEL}; background: transparent;")
        layout.addWidget(sys_lbl)

        body_lbl = QLabel(data.get("body", "No Body"))
        body_lbl.setFont(QFont(_FONT, 9))
        body_lbl.setStyleSheet(f"color: {_COL_DIM}; background: transparent;")
        layout.addWidget(body_lbl)

        coord_lbl = QLabel(f"{data['lat']:.2f}, {data['lon']:.2f}")
        coord_lbl.setFont(QFont(_FONT_MONO, 8))
        coord_lbl.setStyleSheet(f"color: {_COL_LABEL}; background: transparent;")
        layout.addWidget(coord_lbl)

        # Control buttons container
        self._ctrl_row = QWidget(self)
        self._ctrl_row.move(100, 4)
        self._ctrl_row.setFixedSize(42, 20)
        ctrl_lay = QHBoxLayout(self._ctrl_row)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(2)

        self._edit_btn = _IconButton(_NavIcon.EDIT, "Edit bookmark")
        self._edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self._data))

        self._del_btn = QPushButton("\u2715") # ✕
        self._del_btn.setFixedSize(18, 18)
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_COL_DIM}; border: none; font-size: 10px; }}"
            f"QPushButton:hover {{ color: #FF4422; }}"
        )
        self._del_btn.clicked.connect(lambda: self.delete_clicked.emit(self._data))

        ctrl_lay.addWidget(self._edit_btn)
        ctrl_lay.addWidget(self._del_btn)

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Prevent trigger if clicking the buttons
            if self._del_btn.underMouse() or self._edit_btn.underMouse():
                return
            self.clicked.emit(self._data)
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 4, 4)
        
        bg = QColor("#1e1f20") if not self._is_hovered else QColor("#2a2a2a")
        p.fillPath(path, bg)
        
        border = QColor(_COL_LABEL) if self._is_hovered else QColor("#252525")
        p.setPen(QPen(border, 1))
        p.drawPath(path)


class _AddBookmarkPlaceholder(QWidget):
    """The '+' card at the end of the gallery."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(145, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_hovered = False

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 4, 4)
        
        bg = QColor("#1e1f20") if not self._is_hovered else QColor("#2a2a2a")
        p.fillPath(path, bg)
        
        pen = QPen(QColor(_COL_DIM), 1, Qt.PenStyle.DashLine)
        if self._is_hovered:
            pen = QPen(QColor(_COL_ACTIVE), 1, Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawPath(path)

        p.setFont(QFont(_FONT, 24))
        p.setPen(QColor(_COL_DIM) if not self._is_hovered else QColor(_COL_ACTIVE))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "+")


# ---------------------------------------------------------------------------
# Sidebar vector icons (QPainter-rendered, crisp at any DPI)
# ---------------------------------------------------------------------------

class _NavIcon(QWidget):
    """Scalable vector icon drawn with QPainter — no SVG dependency."""

    TARGET  = 0
    INFO    = 1
    HISTORY = 2
    RANDOM  = 3
    UPDATE  = 4
    BOOKMARKS = 5
    EDIT    = 6
    MENU    = 7
    SEARCH  = 8
    CLEAR   = 9
    SEND    = 10
    STOP    = 11
    _SZ     = 20

    def __init__(self, kind: int, parent=None):
        super().__init__(parent)
        self._kind  = kind
        self._color = QColor(_COL_LABEL)
        self.setFixedSize(self._SZ, self._SZ)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_kind(self, kind: int) -> None:
        self._kind = kind
        self.update()

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._SZ / 2.0

        if self._kind == self.TARGET:
            pen = QPen(self._color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Outer ring
            p.drawEllipse(QRectF(c - 5.5, c - 5.5, 11.0, 11.0))
            # Four crosshair segments with gap at the ring
            for x1, y1, x2, y2 in (
                (0,       c,       c - 5.5, c      ),
                (c + 5.5, c,       self._SZ, c     ),
                (c,       0,       c,       c - 5.5),
                (c,       c + 5.5, c,       self._SZ),
            ):
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            # Inner filled dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(QRectF(c - 1.5, c - 1.5, 3.0, 3.0))

        elif self._kind == self.INFO:
            pen = QPen(self._color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Outer circle (slightly larger: 11.0 -> 13.0)
            p.drawEllipse(QRectF(c - 6.5, c - 6.5, 13.0, 13.0))
            # Filled dot above stem
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(QRectF(c - 1.0, c - 4.5, 2.0, 2.0))
            # Stem
            pen2 = QPen(self._color, 1.5)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen2)
            p.drawLine(QPointF(c, c - 1.5), QPointF(c, c + 4.0))

        elif self._kind == self.HISTORY:
            pen = QPen(self._color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Outer circle
            p.drawEllipse(QRectF(c - 5.5, c - 5.5, 11.0, 11.0))
            # Hour hand  (~9 o'clock — points left)
            p.drawLine(QPointF(c, c), QPointF(c - 3.2, c))
            # Minute hand (~12 o'clock — points up)
            p.drawLine(QPointF(c, c), QPointF(c, c - 4.2))

        elif self._kind == self.RANDOM:
            pen = QPen(self._color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)

            # Draw shuffle icon (crossing arrows)
            # Path 1: Top-left to bottom-right
            p.drawLine(QPointF(c - 6, c - 4), QPointF(c - 2, c - 4))
            p.drawLine(QPointF(c - 2, c - 4), QPointF(c + 2, c + 4))
            p.drawLine(QPointF(c + 2, c + 4), QPointF(c + 6, c + 4))
            # Arrow head 1
            p.drawLine(QPointF(c + 4, c + 2), QPointF(c + 6, c + 4))
            p.drawLine(QPointF(c + 4, c + 6), QPointF(c + 6, c + 4))

            # Path 2: Bottom-left to top-right
            p.drawLine(QPointF(c - 6, c + 4), QPointF(c - 2, c + 4))
            p.drawLine(QPointF(c - 2, c + 4), QPointF(c + 2, c - 4))
            p.drawLine(QPointF(c + 2, c - 4), QPointF(c + 6, c - 4))
            # Arrow head 2
            p.drawLine(QPointF(c + 4, c - 6), QPointF(c + 6, c - 4))
            p.drawLine(QPointF(c + 4, c - 2), QPointF(c + 6, c - 4))

        elif self._kind == self.UPDATE:
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Circle
            p.drawEllipse(QRectF(c - 6.5, c - 6.5, 13.0, 13.0))
            # Up arrow
            p.drawLine(QPointF(c, c + 3.5), QPointF(c, c - 3.5))
            p.drawLine(QPointF(c - 3, c - 0.5), QPointF(c, c - 3.5))
            p.drawLine(QPointF(c + 3, c - 0.5), QPointF(c, c - 3.5))

        elif self._kind == self.BOOKMARKS:
            pen = QPen(self._color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Ribbon/Bookmark shape
            path = QPainterPath()
            path.moveTo(c - 4.5, c - 6.5)
            path.lineTo(c + 4.5, c - 6.5)
            path.lineTo(c + 4.5, c + 6.5)
            path.lineTo(c,       c + 3.5)
            path.lineTo(c - 4.5, c + 6.5)
            path.closeSubpath()
            p.drawPath(path)

        elif self._kind == self.EDIT:
            pen = QPen(self._color, 1.3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Scaled down vector pencil
            path = QPainterPath()
            path.moveTo(c - 5.0, c + 5.0)
            path.lineTo(c - 5.0, c + 2.5)
            path.lineTo(c + 2.5, c - 5.0)
            path.lineTo(c + 5.0, c - 5.0)
            path.lineTo(c + 5.0, c - 2.5)
            path.lineTo(c - 2.5, c + 5.0)
            path.closeSubpath()
            p.drawPath(path)
            # Detail lines
            p.drawLine(QPointF(c - 4.0, c + 3.5), QPointF(c - 3.5, c + 4.0))
            p.drawLine(QPointF(c + 3.5, c - 4.0), QPointF(c + 4.0, c - 3.5))

        elif self._kind == self.MENU:
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            # Three bars, 12px width
            w = 6.0
            p.drawLine(QPointF(c - w, c - 4.5), QPointF(c + w, c - 4.5))
            p.drawLine(QPointF(c - w, c),       QPointF(c + w, c))
            p.drawLine(QPointF(c - w, c + 4.5), QPointF(c + w, c + 4.5))

        elif self._kind == self.SEARCH:
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Circle lens
            p.drawEllipse(QPointF(c - 2.0, c - 2.0), 4.2, 4.2)
            # Handle
            p.drawLine(QPointF(c + 1.2, c + 1.2), QPointF(c + 5.5, c + 5.5))

        elif self._kind == self.CLEAR:
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Circular arrow
            r = 5.5
            p.drawArc(QRectF(c - r, c - r, 2 * r, 2 * r), 40 * 16, 280 * 16)
            # Arrow head
            p.drawLine(QPointF(c + r, c), QPointF(c + r - 3, c - 3))
            p.drawLine(QPointF(c + r, c), QPointF(c + r + 3, c - 3))

        elif self._kind == self.SEND:
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Right-pointing arrow/triangle
            p.drawLine(QPointF(c - 6, c), QPointF(c + 6, c))
            p.drawLine(QPointF(c + 2, c - 4), QPointF(c + 6, c))
            p.drawLine(QPointF(c + 2, c + 4), QPointF(c + 6, c))

        elif self._kind == self.STOP:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            # Filled square centred in the icon
            p.drawRect(QRectF(c - 5, c - 5, 10, 10))

        p.end()


# ---------------------------------------------------------------------------
# Sidebar navigation item (icon + collapsible label)
# ---------------------------------------------------------------------------

class _SidebarNavItem(QWidget):
    """Sidebar row: vector icon on the left, text label that clips when narrow."""

    clicked = pyqtSignal()

    def __init__(self, icon_kind: int, label: str, parent=None):
        super().__init__(parent)
        self._is_checked = False
        self._is_hovered = False
        self._label_visible = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)

        self._icon = _NavIcon(icon_kind, self)
        row.addWidget(self._icon)

        self._lbl = QLabel(label)
        self._lbl.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        self._lbl.setMinimumWidth(0)
        row.addWidget(self._lbl, 1)

        self._refresh()

    def set_label_visible(self, visible: bool) -> None:
        self._label_visible = visible
        self._lbl.setVisible(visible)
        row = self.layout()
        if visible:
            row.setContentsMargins(12, 0, 12, 0)
        else:
            row.setContentsMargins(14, 0, 14, 0)

    # ------------------------------------------------------------------

    def set_checked(self, checked: bool) -> None:
        self._is_checked = checked
        self._refresh()

    def is_checked(self) -> bool:
        return self._is_checked

    # ------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        self._refresh()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        self._refresh()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body_rect = QRectF(self.rect()).adjusted(6, 2, -6, -2)

        if self._is_checked or self._is_hovered:
            fill = QColor("#2B2118" if self._is_checked else "#201A12")
            border = QColor("#52311A" if self._is_checked else "#3D2810")
            path = QPainterPath()
            path.addRoundedRect(body_rect, 9, 9)
            p.fillPath(path, fill)
            pen = QPen(border, 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPath(path)
        p.end()

    def _refresh(self) -> None:
        color = (
            _COL_ACTIVE if self._is_checked else
            _COL_LABEL  if self._is_hovered else
            _COL_DIM
        )
        self._icon.set_color(color)
        self._lbl.setStyleSheet(
            f"color: {color}; background: transparent; border: none; letter-spacing: 0px;"
        )
        self.update()


# ---------------------------------------------------------------------------
# Minimal icon-only clickable widget (used for history trigger, etc.)
# ---------------------------------------------------------------------------

class _IconButton(QWidget):
    """Transparent icon button — color-only hover, no background box."""

    clicked = pyqtSignal()

    def __init__(self, icon_kind: int, tooltip: str = "", parent=None, size: tuple[int, int] | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._icon = _NavIcon(icon_kind, self)
        self._icon.set_color(_COL_LABEL)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignCenter)
        if size:
            self.setFixedSize(*size)
        else:
            sz = 32
            self.setFixedSize(sz, sz)

    def set_icon(self, icon_kind: int, tooltip: str = "") -> None:
        self._icon.set_kind(icon_kind)
        if tooltip:
            self.setToolTip(tooltip)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._icon.set_color(_COL_LABEL if enabled else "#3D1E00")
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    def enterEvent(self, event) -> None:
        if self.isEnabled():
            self._icon.set_color(_COL_ACTIVE)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._icon.set_color(_COL_LABEL if self.isEnabled() else "#3D1E00")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
            event.accept()


# ---------------------------------------------------------------------------
# Shared QMenu stylesheet — keeps both context menus visually consistent
# ---------------------------------------------------------------------------

def _menu_ss(font_size: int) -> str:
    return (
        f"QMenu {{ background: transparent; color: {_COL_ACTIVE};"
        f" font-family: '{_FONT}'; font-size: {font_size}pt;"
        f" font-weight: 600; letter-spacing: 0px;"
        f" border: none; padding: 6px 0px; }}"
        f"QMenu::item {{ padding: 3px 10px; }}"
        f"QMenu::item:selected {{ background: #282828; color: {_COL_ACTIVE}; }}"
        f"QMenu::item:disabled {{ color: {_COL_DIM}; }}"
        f"QMenu::separator {{ height: 1px; background: {_COL_BORDER}; margin: 2px 6px; }}"
    )


class _RoundedMenu(QMenu):
    """QMenu with smooth anti-aliased rounded corners via WA_TranslucentBackground.

    Replaces the setMask approach (which caused border thinness at corners due to
    pixel-level clipping) with a fully composited transparent window + custom paintEvent.
    The 6px top/bottom padding in _menu_ss ensures items start below the corner arc,
    so their hover fill never bleeds into the transparent corner regions.
    """
    _RADIUS = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            self._RADIUS, self._RADIUS,
        )
        pen = QPen(QColor(_COL_BORDER), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor(_COL_INPUT_BG))
        p.drawPath(path)
        p.end()


# ---------------------------------------------------------------------------
# Custom widget for menu rows (Recent targets or Body selection)
# ---------------------------------------------------------------------------

class _MenuRow(QWidget):
    """Custom-painted row with elided left text and right-aligned secondary text."""

    _H_PAD = 12
    _V_PAD = 4

    def __init__(self, left_text: str, right_text: str, parent=None):
        super().__init__(parent)
        self._left_text   = left_text
        self._right_text  = right_text
        self._font_size   = _SZ_LABEL - 1
        self._hovered     = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_font_size(self, size: int) -> None:
        self._font_size = size
        self.updateGeometry()
        self.update()

    def set_hovered(self, hovered: bool) -> None:
        if self._hovered != hovered:
            self._hovered = hovered
            self.update()

    def enterEvent(self, event) -> None:
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_hovered(False)
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._make_font())
        # Calculate natural width: padding + left_text + gap + right_text + padding
        w = (self._H_PAD 
             + fm.horizontalAdvance(self._left_text) 
             + 24 # Gap
             + fm.horizontalAdvance(self._right_text) 
             + self._H_PAD)
        # Dynamic but bounded: at least 320px, at most 480px
        w = max(320, min(w, 480))
        h = fm.height() + 2 * self._V_PAD
        return QSize(int(w), h)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        if self._hovered:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            hl = QPainterPath()
            hl.addRoundedRect(QRectF(self.rect()).adjusted(3, 1, -3, -1), 4, 4)
            p.fillPath(hl, QColor(42, 42, 42, 200))
        
        font = self._make_font()
        p.setFont(font)
        fm = QFontMetrics(font)
        y  = (self.height() + fm.ascent() - fm.descent()) // 2
        
        # Right text always fully visible
        right_w = fm.horizontalAdvance(self._right_text)
        
        # Left text elided if it exceeds available space
        # Gap of 24px between columns
        avail_l = self.width() - (2 * self._H_PAD) - right_w - 24
        elided_l = fm.elidedText(self._left_text, Qt.TextElideMode.ElideRight, avail_l)
        
        p.setPen(QColor(_COL_ACTIVE))
        p.drawText(self._H_PAD, y, elided_l)
        
        p.setPen(QColor(_COL_DIM))
        p.drawText(self.width() - self._H_PAD - right_w, y, self._right_text)
        p.end()

    def _make_font(self) -> QFont:
        f = QFont(_FONT, self._font_size)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        return f


# ---------------------------------------------------------------------------
# Paste-parsing regexes (same logic as the old settings_panel.py)
# ---------------------------------------------------------------------------
_POI_PATTERN = re.compile(
    r"lat[:\s]*([+-]?\d+\.?\d*)\s*[/,]?\s*lon[:\s]*([+-]?\d+\.?\d*)",
    re.IGNORECASE,
)
_SIMPLE_PATTERN = re.compile(
    r"^([+-]?\d+\.?\d*)\s*[,\s]\s*([+-]?\d+\.?\d*)$"
)


def _parse_paste(text: str) -> Optional[tuple[float, float]]:
    """Try to extract (lat, lon) from a pasted string.  Returns None on failure."""
    m = _POI_PATTERN.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _SIMPLE_PATTERN.match(text.strip())
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _validate_coord(text: str, lo: float, hi: float) -> Optional[float]:
    """
    Return the parsed float if text is a valid in-range coordinate with at most
    4 decimal places; otherwise return None.
    Trailing zeros after the decimal point are not counted (85.36580 == 4 dp).
    """
    text = text.strip()
    try:
        val = float(text)
    except ValueError:
        return None
    if not (lo <= val <= hi):
        return None
    if '.' in text:
        if len(text.split('.')[1].rstrip('0')) > 4:
            return None
    return val


# ---------------------------------------------------------------------------
# CoordWindow
# ---------------------------------------------------------------------------

class CoordWindow(QWidget):
    """
    Always-on-top settings/input window.
    Emits target_set(lat, lon, radius_m) and target_cleared().
    """

    target_set     = pyqtSignal(float, float, float, object, str)  # lat, lon, radius_m, body_name, system
    target_cleared = pyqtSignal()
    move_overlay   = pyqtSignal()
    toggle_overlay = pyqtSignal()
    apply_update   = pyqtSignal(str, str)  # (version, path_to_new_exe)

    # UI constants (referenced from top-level style section)
    _TITLE_BAR_H      = _TITLE_BAR_H
    _SIDEBAR_ICON_W   = _SIDEBAR_ICON_W
    _SIDEBAR_FULL_W   = _SIDEBAR_FULL_W
    _SIDEBAR_HEADER_H = _SIDEBAR_HEADER_H
    _FIXED_W, _FIXED_H = _FIXED_W, _FIXED_H

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("ED Navigator")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        self._radius_m:      float = 0.0
        self._bodies:        list[LandableBody] = []
        self._selected_body: LandableBody | None = None
        self._last_system:   str = ""
        self._menu_open:         bool = False
        self._history_menu_open: bool = False
        self._target_history: list[dict] = self._load_history()
        self._bookmarks:      list[dict] = self._load_bookmarks()

        self._build_ui()
        self.setFixedSize(self._FIXED_W, self._FIXED_H)
        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event):
        """Hide instead of destroy so state is preserved."""
        event.ignore()
        self.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._sidebar_open:
            self._close_sidebar()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        """Draw rounded-rect background and outer border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.fillPath(path, QColor("#181818"))
        pen = QPen(QColor(_COL_BORDER), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPath(path)

    def resizeEvent(self, event):
        """Handle window resizing."""
        super().resizeEvent(event)
        if hasattr(self, '_sidebar_panel') and hasattr(self, '_body'):
            self._sidebar_panel.setFixedHeight(self._body.height())
        if hasattr(self, '_body'):
            self._update_body_mask()

    def _update_body_mask(self) -> None:
        """Clip _body (and all its children) to the window's rounded bottom corners."""
        w, h = self._body.width(), self._body.height()
        if w <= 0 or h <= 0:
            self._body.clearMask()
            return
        r = 10
        bottom = h - 1
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(w, 0)
        path.lineTo(w, bottom - r)
        path.quadTo(w, bottom, w - r, bottom)
        path.lineTo(r, bottom)
        path.quadTo(0, bottom, 0, bottom - r)
        path.lineTo(0, 0)
        path.closeSubpath()
        self._body.setMask(QRegion(path.toFillPolygon().toPolygon()))

    @pyqtProperty(int)
    def sidebarWidth(self) -> int:
        return self._sidebar_w_cur

    @sidebarWidth.setter
    def sidebarWidth(self, w: int) -> None:
        self._sidebar_w_cur = w
        self._sidebar_panel.setFixedWidth(w)
        if hasattr(self, '_body'):
            self._sidebar_panel.setFixedHeight(self._body.height())
        self._sidebar_panel.raise_()


        if hasattr(self, '_sidebar_nav_items'):
            labels_visible = w > 80
            for item in self._sidebar_nav_items:
                item.set_label_visible(labels_visible)
            if hasattr(self, '_info_item'):
                self._info_item.set_label_visible(labels_visible)

    # ------------------------------------------------------------------
    # Public API called from main's push_nav()
    # ------------------------------------------------------------------

    def set_move_mode(self, active: bool) -> None:
        self._move_btn.setText("Done moving" if active else "Move overlay")

    def set_overlay_visible(self, visible: bool) -> None:
        """Update the toggle button text based on overlay visibility."""
        self._toggle_btn.setText("Hide overlay" if visible else "Show overlay")

    def show_update_available(self, version: str) -> None:
        """Show the update button in a 'downloading' state."""
        self._update_version = version
        self._update_new_exe: str | None = None
        self._title_bar._update_btn.setVisible(True)
        self._title_bar._update_btn.setToolTip(
            f"v{version} available — downloading..."
        )

    def show_update_ready(self, version: str, new_exe_path: str) -> None:
        """Update is downloaded; prompt the user to restart."""
        self._update_version = version
        self._update_new_exe = new_exe_path
        self._title_bar._update_btn.setToolTip(
            f"v{version} ready — click to restart and update"
        )


    def update_status(self, nav: NavResult, has_target: bool) -> None:
        # Silently absorb live planet radius for Haversine accuracy
        if nav.planet_radius_m and self._selected_body is None:
            self._radius_m = nav.planet_radius_m

        if not nav.has_lat_long:
            self._status_label.setText("NO SIGNAL")
        elif not has_target:
            self._status_label.setText("AWAITING")
        elif nav.body_mismatch:
            self._status_label.setText("MISMATCH")
        elif nav.arrived:
            self._status_label.setText("ARRIVED")
        elif nav.distance_m is not None:
            dist = nav.distance_m
            dist_str = f"{dist / 1000:.1f} KM" if dist >= 1000 else f"{int(dist)} M"
            # Show ONLY the distance value + unit
            self._status_label.setText(dist_str)
        else:
            self._status_label.setText("TRACKING")

    def update_bodies(self, bodies: list[LandableBody], system: str, scan_required: bool = False) -> None:
        """Called from push_nav() with the latest journal body list."""
        self._bodies = bodies

        # Clear selection when the system changes
        if system != self._last_system:
            self._last_system    = system
            self._selected_body  = None
            self._radius_m       = 0.0

        # Sync count label and list-button state
        _FSS_TIP = (
            "FSS scan the desired planet, or approach within at least "
            "30 LS of it to be detected."
        )
        n = len(bodies)
        if n:
            self._body_count_label.setText(f"BODIES: {n}")
            self._planet_name_label.setEnabled(True)
            self._planet_name_label.setToolTip("")
            self._body_count_label.setToolTip("")
        elif scan_required:
            self._body_count_label.setText("SCAN REQ")
            self._planet_name_label.setEnabled(False)
            self._planet_name_label.setToolTip(_FSS_TIP)
            self._body_count_label.setToolTip(_FSS_TIP)
        else:
            self._body_count_label.setText("BODIES: 0")
            self._planet_name_label.setEnabled(False)
            self._planet_name_label.setToolTip(_FSS_TIP)
            self._body_count_label.setToolTip(_FSS_TIP)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outer layout: title bar edge-to-edge, then content stack
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title_bar = _TitleBar("ed-nav", self)
        self._title_bar._min_btn.clicked.connect(self.showMinimized)
        self._title_bar._max_btn.setEnabled(False)
        self._title_bar._close_btn.clicked.connect(self.hide)
        self._title_bar.update_clicked.connect(self._on_update_clicked)
        self._title_bar.icon_clicked.connect(self._toggle_sidebar)
        outer.addWidget(self._title_bar)

        # Horizontal body container (no separator — title bar bleeds into content)
        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        outer.addWidget(self._body)

        # Card-style content container with rounded corners
        content_layout = QHBoxLayout(self._body)
        content_layout.setContentsMargins(3, 4, 3, 3)
        content_layout.setSpacing(0)

        self._card = _RoundedPanel("#181818", radius_tl=10, radius_tr=10, radius_br=10, radius_bl=10)
        card_inner = QVBoxLayout(self._card)
        card_inner.setContentsMargins(0, 0, 0, 0)
        card_inner.setSpacing(0)

        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background: transparent; border-radius: 10px;")
        card_inner.addWidget(self._content_stack)
        content_layout.addWidget(self._card)

        # Sidebar is added as an overlay on top of _body (flush against window edges)
        self._build_sidebar()
        self._sidebar_panel.setParent(self._body)
        self._sidebar_panel.move(1, 0)
        self._sidebar_panel.setFixedHeight(self._body.height())
        self._sidebar_panel.raise_()
        self._update_body_mask()

        self._build_target_page()
        self._build_bookmarks_page()
        self._build_about_page()

    def _build_target_page(self) -> None:
        """Build the main target-input page and add it to the content stack."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(4)

        self._planet_name_label = _ElidedButton("Select a Planet")
        self._planet_name_label.setFont(QFont(_FONT, _SZ_BTN, QFont.Weight.DemiBold))
        self._planet_name_label.setStyleSheet(
            f"QPushButton {{ background: {_COL_INPUT_BG}; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 3px;"
            f" padding: 4px 12px; letter-spacing: 0px;"
            f" font-family: '{_FONT}', 'Segoe UI Symbol'; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE}; background: #282828; }}"
            f"QPushButton:pressed {{ background: #7A3D00; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        self._planet_name_label.setFixedWidth(int(self._planet_name_label.sizeHint().width() * 1.5))
        self._planet_name_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._planet_name_label.setEnabled(False)
        self._planet_name_label.clicked.connect(self._show_body_menu)

        self._status_label = QLabel("NO SIGNAL")
        self._status_label.setFixedWidth(110)
        self._status_label.setFont(QFont(_FONT, _SZ_STATUS, QFont.Weight.Bold))
        self._status_label.setStyleSheet(f"background: transparent; color: {_COL_LABEL};")

        self._body_count_label = QLabel("BODIES: 0")
        self._body_count_label.setFixedWidth(110)
        self._body_count_label.setFont(QFont(_FONT, _SZ_STATUS, QFont.Weight.Bold))
        self._body_count_label.setStyleSheet(
            f"background: transparent; color: {_COL_LABEL};"
        )
        self._body_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Top row: Status | Select Planet | Body Count
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 2, 0, 2)
        top_row.setSpacing(8)
        top_row.addWidget(self._status_label, 0)
        top_row.addWidget(self._planet_name_label, 1) # Expand and center
        top_row.addWidget(self._body_count_label, 0)
        layout.addLayout(top_row)

        # 3D planet preview — hidden until a body is selected
        self._planet_preview = PlanetPreviewWidget()
        self._planet_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._planet_preview.setMinimumSize(210, 210)
        self._planet_preview.setMaximumSize(16777215, 16777215)
        self._planet_preview.coord_picked.connect(self._on_coord_picked)
        layout.addWidget(self._planet_preview, 1) # Give it stretch

        layout.addWidget(_Separator())

        # Body name row: label on the left, history icon button on the right
        self._bookmark_btn = _IconButton(_NavIcon.BOOKMARKS, "Save current coordinates as a bookmark")
        self._bookmark_btn.setEnabled(False)
        self._bookmark_btn.clicked.connect(self._on_quick_bookmark)

        self._random_btn = _IconButton(_NavIcon.RANDOM, "Populate with random coordinates")
        self._random_btn.clicked.connect(self._on_random)

        self._history_btn = _IconButton(_NavIcon.HISTORY, "Recently used targets")
        self._history_btn.setEnabled(bool(self._target_history))
        self._history_btn.clicked.connect(self._show_history_menu)

        body_name_label = QLabel("BODY NAME")
        body_name_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        body_name_label.setStyleSheet(f"background: transparent; color: {_COL_LABEL}; letter-spacing: 0px;")

        # Inline error label — sits between the section label and the icon buttons
        self._error_label = QLabel("")
        self._error_label.setFont(QFont(_FONT, _SZ_HINT))
        self._error_label.setStyleSheet(f"background: transparent; color: {COLOR_ERROR};")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._error_label.setVisible(False)

        body_name_row = QHBoxLayout()
        body_name_row.setContentsMargins(0, 0, 0, 0)
        body_name_row.setSpacing(6)
        body_name_row.addWidget(body_name_label, 0)
        body_name_row.addWidget(self._error_label, 1)
        body_name_row.addWidget(self._bookmark_btn)
        body_name_row.addWidget(self._random_btn)
        body_name_row.addWidget(self._history_btn)
        layout.addLayout(body_name_row)

        self._body_name_input = self._make_line_edit("e.g.  Synuefe XR-H d11-102 1 b")
        self._body_name_input.textChanged.connect(self._on_body_name_changed)
        layout.addWidget(self._body_name_input)

        # Latitude / Longitude in a grid to save vertical space
        coords_grid = QGridLayout()
        coords_grid.setContentsMargins(0, 0, 0, 0)
        coords_grid.setSpacing(6)

        lat_label = QLabel("LATITUDE (−90 to 90)")
        lat_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lat_label.setStyleSheet(f"background: transparent; color: {_COL_LABEL}; letter-spacing: 0px;")
        
        self._lat_input = self._make_line_edit("e.g. −22.45")
        self._lat_input.textChanged.connect(self._clear_error)
        self._lat_input.textChanged.connect(self._update_preview_marker)
        self._lat_input.installEventFilter(self)

        lon_label = QLabel("LONGITUDE (−180 to 180)")
        lon_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lon_label.setStyleSheet(f"background: transparent; color: {_COL_LABEL}; letter-spacing: 0px;")

        self._lon_input = self._make_line_edit("e.g. 137.88")
        self._lon_input.textChanged.connect(self._clear_error)
        self._lon_input.textChanged.connect(self._update_preview_marker)
        self._lon_input.installEventFilter(self)

        coords_grid.addWidget(lat_label, 0, 0)
        coords_grid.addWidget(self._lat_input, 1, 0)
        coords_grid.addWidget(lon_label, 0, 1)
        coords_grid.addWidget(self._lon_input, 1, 1)
        layout.addLayout(coords_grid)

        layout.addSpacing(8)

        # Control Row: Clear | [Move overlay] | [Hide overlay] | Set
        self._clear_btn = _IconButton(_NavIcon.CLEAR, "Clear inputs")
        self._clear_btn.clicked.connect(self._on_clear)

        self._set_btn = _IconButton(_NavIcon.SEND, "Set Target")
        self._set_btn.setEnabled(False) # Disabled until name is entered
        self._set_btn.clicked.connect(self._on_set_or_stop)
        self._navigating = False

        self._move_btn   = self._make_button("Move overlay")
        self._toggle_btn = self._make_button("Hide overlay")
        
        # Reduced font size and fixed width to fit inline
        _small_btn_ss = (
            f"QPushButton {{ background: {_COL_INPUT_BG}; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 3px;"
            f" padding: 3px 8px; letter-spacing: 0px; font-size: 9pt; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE}; background: #282828; }}"
            f"QPushButton:pressed {{ background: #7A3D00; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        self._move_btn.setStyleSheet(_small_btn_ss)
        self._toggle_btn.setStyleSheet(_small_btn_ss)
        self._move_btn.setFixedWidth(110)
        self._toggle_btn.setFixedWidth(110)
        
        self._move_btn.clicked.connect(self.move_overlay)
        self._toggle_btn.clicked.connect(self.toggle_overlay)
        self._toggle_btn.setToolTip("Shortcut: Ctrl+Shift+N")

        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(6)
        ctrl_row.addWidget(self._clear_btn)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._move_btn)
        ctrl_row.addWidget(self._toggle_btn)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._set_btn)
        layout.addLayout(ctrl_row)

        self._content_stack.addWidget(page)

    def _build_bookmarks_page(self) -> None:
        """Build the Bookmarks page with gallery view."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header = QLabel("BOOKMARKS")
        header.setFont(QFont(_FONT, _SZ_TITLE, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {_COL_ACTIVE}; letter-spacing: 0.5px;")
        header_row.addWidget(header)
        header_row.addStretch(1)

        self._search_btn = _IconButton(
            _NavIcon.SEARCH, "Search Bookmarks", size=(32, 32)
        )
        self._search_btn.clicked.connect(self._toggle_bookmark_search)
        header_row.addWidget(self._search_btn)
        layout.addLayout(header_row)

        layout.addWidget(_Separator())

        # Search bar (hidden until search button is toggled)
        self._bookmark_search_bar = QLineEdit()
        self._bookmark_search_bar.setPlaceholderText("name, system, body, coords…")
        self._bookmark_search_bar.setFont(QFont(_FONT_MONO, _SZ_INPUT))
        self._bookmark_search_bar.setStyleSheet(
            f"QLineEdit {{ background: {_COL_INPUT_BG}; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 3px;"
            f" padding: 3px 6px; }}"
            f"QLineEdit:focus {{ border-color: {_COL_ACTIVE}; }}"
        )
        self._bookmark_search_bar.setVisible(False)
        self._bookmark_search_bar.textChanged.connect(self._filter_bookmarks)
        layout.addWidget(self._bookmark_search_bar)

        # Scroll area for the gallery
        self._bookmark_scroll = QScrollArea()
        self._bookmark_scroll.setWidgetResizable(True)
        self._bookmark_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._bookmark_scroll.setStyleSheet("background: transparent;")

        self._bookmark_container = QWidget()
        self._bookmark_container.setStyleSheet("background: transparent;")
        self._bookmark_grid = QGridLayout(self._bookmark_container)
        self._bookmark_grid.setContentsMargins(0, 6, 0, 6)
        self._bookmark_grid.setSpacing(8)
        self._bookmark_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._bookmark_scroll.setWidget(self._bookmark_container)
        layout.addWidget(self._bookmark_scroll)

        self._refresh_bookmarks()
        self._content_stack.addWidget(page)

    def _refresh_bookmarks(self, subset: list[dict] | None = None) -> None:
        """Rebuild the bookmark card gallery, optionally limited to *subset*."""
        # Clear existing
        while self._bookmark_grid.count():
            item = self._bookmark_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries = subset if subset is not None else self._bookmarks
        row, col = 0, 0
        for b_data in entries:
            card = _BookmarkCard(b_data)
            card.clicked.connect(self._on_bookmark_clicked)
            card.edit_clicked.connect(self._on_bookmark_edit)
            card.delete_clicked.connect(self._on_bookmark_delete)
            self._bookmark_grid.addWidget(card, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1

        # Only show the add-placeholder when not filtering
        if subset is None:
            add_btn = _AddBookmarkPlaceholder()
            add_btn.clicked.connect(self._on_add_bookmark)
            self._bookmark_grid.addWidget(add_btn, row, col)

    def _filter_bookmarks(self, query: str) -> None:
        """Filter the bookmark gallery by name, system, body, or coordinates."""
        q = query.strip().lower()
        if not q:
            self._refresh_bookmarks()
            return
        matched = []
        for b in self._bookmarks:
            haystack = " ".join([
                b.get("name", ""),
                b.get("system", ""),
                b.get("body", ""),
                f"{b.get('lat', '')}",
                f"{b.get('lon', '')}",
            ]).lower()
            if q in haystack:
                matched.append(b)
        self._refresh_bookmarks(subset=matched)

    def _toggle_bookmark_search(self) -> None:
        """Show/focus the search bar on the Bookmarks page."""
        # Switch to the bookmarks page (index 1)
        self._sidebar_nav_select(1)
        visible = not self._bookmark_search_bar.isVisible()
        self._bookmark_search_bar.setVisible(visible)
        if visible:
            self._bookmark_search_bar.setFocus()
        else:
            self._bookmark_search_bar.clear()

    def _on_add_bookmark(self) -> None:
        """Open a dialog for manual bookmark entry."""
        dlg = _BookmarkDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_b = dlg.get_data()
            if new_b:
                self._bookmarks.append(new_b)
                self._save_bookmarks()
                self._refresh_bookmarks()

    def _on_bookmark_clicked(self, data: dict) -> None:
        """Load bookmark into inputs and switch to target page."""
        self._lat_input.setText(str(data["lat"]))
        self._lon_input.setText(str(data["lon"]))
        self._body_name_input.setText(data.get("body", ""))
        self._last_system = data.get("system", "")
        # Sync sidebar state when switching back to target page
        self._sidebar_nav_select(0)
        self._clear_error()
        self._update_preview_marker()

    def _on_bookmark_edit(self, data: dict) -> None:
        """Open a dialog to edit an existing bookmark."""
        dlg = _BookmarkDialog(self, initial_data=data)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated_b = dlg.get_data()
            if updated_b:
                idx = self._bookmarks.index(data)
                self._bookmarks[idx] = updated_b
                self._save_bookmarks()
                self._refresh_bookmarks()

    def _on_bookmark_delete(self, data: dict) -> None:
        self._bookmarks.remove(data)
        self._save_bookmarks()
        self._refresh_bookmarks()

    def _load_bookmarks(self) -> list[dict]:
        s = QSettings("ED-Navigator", "Overlay")
        raw = s.value("bookmarks", "[]")
        try:
            return json.loads(raw)
        except:
            return []

    def _save_bookmarks(self) -> None:
        s = QSettings("ED-Navigator", "Overlay")
        s.setValue("bookmarks", json.dumps(self._bookmarks))

    def _build_about_page(self) -> None:
        """Build the About/info page and add it to the content stack."""
        _GH_BASE   = f"https://github.com/{GITHUB_REPO}"
        _LINK_COL  = "#4A9FDF"   # blue hyperlink colour

        # --- helpers (local, no state needed) ---
        def _section_cap(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(QFont(_FONT, 8, QFont.Weight.Bold))
            lbl.setStyleSheet(
                f"color: {_COL_DIM}; letter-spacing: 0.5px; background: transparent;"
            )
            return lbl

        def _link(display: str, url: str) -> QLabel:
            lbl = QLabel(
                f'<a href="{url}" style="color:{_LINK_COL};text-decoration:none;">'
                f'{display}</a>'
            )
            lbl.setFont(QFont(_FONT, 11))
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet("background: transparent;")
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            return lbl

        # --- outer page + scroll area ---
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #1a1a1a; width: 5px; border: none; }"
            "QScrollBar::handle:vertical { background: #4a2800;"
            " border-radius: 2px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0px; }"
        )

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 14, 14, 18)
        lay.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────
        hdr = QLabel("INFORMATION")
        hdr.setFont(QFont(_FONT, 14, QFont.Weight.Bold))
        hdr.setStyleSheet(
            f"color: {_COL_ACTIVE}; letter-spacing: 1px; background: transparent;"
        )
        lay.addWidget(hdr)
        lay.addSpacing(8)
        lay.addWidget(_Separator())
        lay.addSpacing(14)

        # ── Branding block ───────────────────────────────────────────────
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(TrayIcon._make_icon().pixmap(36, 36))
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setStyleSheet("background: transparent;")
        brand_row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        name_col = QVBoxLayout()
        name_col.setSpacing(1)
        app_name = QLabel("ED NAVIGATOR")
        app_name.setFont(QFont(_FONT, 13, QFont.Weight.Bold))
        app_name.setStyleSheet(
            f"color: {_COL_ACTIVE}; letter-spacing: 1px; background: transparent;"
        )
        ver_lbl = QLabel(f"v{VERSION}")
        ver_lbl.setFont(QFont(_FONT, 9))
        ver_lbl.setStyleSheet(
            f"color: {_COL_DIM}; letter-spacing: 0px; background: transparent;"
        )
        name_col.addWidget(app_name)
        name_col.addWidget(ver_lbl)
        brand_row.addLayout(name_col)
        brand_row.addStretch(1)
        lay.addLayout(brand_row)
        lay.addSpacing(12)

        # ── Description ─────────────────────────────────────────────────
        desc = QLabel(
            "A free and open-source ED tool designed for planet surface navigation."
        )
        desc.setFont(QFont(_FONT, 9))
        desc.setStyleSheet(f"color: {_COL_LABEL}; background: transparent;")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addSpacing(14)

        # ── Links ────────────────────────────────────────────────────────
        lay.addWidget(_Separator())
        lay.addSpacing(12)

        for cap, display, url in (
            ("SOURCE CODE",
             "github.com/s4nby/ed-nav",
             _GH_BASE),
            ("OFFICIAL WEBSITE",
             "---",
             None),
            ("CONTACT / SUPPORT",
             "95icarus@gmail.com",
             None),
            ("ISSUE TRACKING",
             "github.com/s4nby/ed-nav/issues",
             f"{_GH_BASE}/issues"),
        ):
            lay.addWidget(_section_cap(cap))
            lay.addSpacing(4)
            if url is None:
                plain = QLabel(display)
                plain.setFont(QFont(_FONT, 11))
                plain.setStyleSheet(f"color: {_COL_LABEL}; background: transparent;")
                lay.addWidget(plain)
            else:
                lay.addWidget(_link(display, url))
            lay.addSpacing(14)

        # ── Dependencies & Credits ───────────────────────────────────────
        lay.addWidget(_Separator())
        lay.addSpacing(12)

        deps_hdr = QLabel("DEPENDENCIES & CREDITS")
        deps_hdr.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        deps_hdr.setStyleSheet(
            f"color: {_COL_LABEL}; letter-spacing: 0.5px; background: transparent;"
        )
        lay.addWidget(deps_hdr)
        lay.addSpacing(8)

        for lib, note in (
            ("Python 3",    "Core runtime"),
            ("PyQt6",       "GUI framework — Qt6 bindings"),
            ("PyInstaller", "Windows executable packaging"),
        ):
            dep_row = QHBoxLayout()
            dep_row.setContentsMargins(0, 0, 0, 0)
            dep_row.setSpacing(0)

            lib_lbl = QLabel(lib)
            lib_lbl.setFont(QFont(_FONT, 9, QFont.Weight.DemiBold))
            lib_lbl.setStyleSheet(
                f"color: {_COL_ACTIVE}; background: transparent;"
            )
            note_lbl = QLabel(note)
            note_lbl.setFont(QFont(_FONT, 9))
            note_lbl.setStyleSheet(f"color: {_COL_DIM}; background: transparent;")
            note_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            dep_row.addWidget(lib_lbl)
            dep_row.addWidget(note_lbl, 1)
            lay.addLayout(dep_row)
            lay.addSpacing(5)

        lay.addSpacing(12)

        # ── Disclaimer ───────────────────────────────────────────────────
        lay.addWidget(_Separator())
        lay.addSpacing(10)

        disc_hdr = QLabel("DISCLAIMER")
        disc_hdr.setFont(QFont(_FONT, 9, QFont.Weight.Bold))
        disc_hdr.setStyleSheet(
            f"color: {_COL_LABEL}; letter-spacing: 0.5px; background: transparent;"
        )
        lay.addWidget(disc_hdr)
        lay.addSpacing(4)

        disc_body = QLabel(
            "THIS SOFTWARE IS PROVIDED AS-IS, WITHOUT WARRANTY OF ANY KIND. "
            "NOT AFFILIATED WITH OR ENDORSED BY FRONTIER DEVELOPMENTS PLC. "
            "USE AT YOUR OWN RISK."
        )
        disc_body.setFont(QFont(_FONT, 8))
        disc_body.setStyleSheet(f"color: {_COL_DIM}; background: transparent;")
        disc_body.setWordWrap(True)
        lay.addWidget(disc_body)
        lay.addStretch(1)

        scroll.setWidget(inner)
        page_lay.addWidget(scroll)
        self._content_stack.addWidget(page)

    # ------------------------------------------------------------------
    # Collapsible sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> None:
        """Build the inline sidebar; completely hidden when closed, slides over content."""
        self._sidebar_w_cur = 0

        self._sidebar_panel = _SidebarPanel()
        self._sidebar_panel.setFixedWidth(0)

        s_layout = QVBoxLayout(self._sidebar_panel)
        s_layout.setContentsMargins(8, 8, 8, 8)
        s_layout.setSpacing(2)

        # Nav items — moved to the very top
        self._sidebar_nav_items: list[_SidebarNavItem] = []
        for icon_kind, label, page_idx in (
            (_NavIcon.TARGET, "Target", 0),
            (_NavIcon.BOOKMARKS, "Bookmarks", 1),
        ):
            item = _SidebarNavItem(icon_kind, label, self._sidebar_panel)
            item.set_checked(page_idx == 0)
            item.set_label_visible(False)   # collapsed on startup; shown when expanded
            item.clicked.connect(
                lambda idx=page_idx: self._sidebar_nav_select(idx)
            )
            s_layout.addWidget(item)
            self._sidebar_nav_items.append(item)

        s_layout.addStretch(1)

        self._info_item = _SidebarNavItem(_NavIcon.INFO, "About", self._sidebar_panel)
        self._info_item.set_label_visible(False)
        self._info_item.clicked.connect(lambda: self._sidebar_nav_select(2))
        s_layout.addWidget(self._info_item)

        self._sidebar_anim = QPropertyAnimation(self, b"sidebarWidth")
        self._sidebar_anim.setDuration(220)
        self._sidebar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)
        self._sidebar_open = False

    def _toggle_sidebar(self) -> None:
        if self._sidebar_open:
            self._close_sidebar()
        else:
            self._open_sidebar()

    def _open_sidebar(self) -> None:
        self._sidebar_open = True
        self._title_bar.set_sidebar_open(True)
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(self._sidebar_w_cur)
        self._sidebar_anim.setEndValue(self._SIDEBAR_FULL_W)
        self._sidebar_anim.start()

    def _close_sidebar(self) -> None:
        self._sidebar_open = False
        self._title_bar.set_sidebar_open(False)
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(self._sidebar_w_cur)
        self._sidebar_anim.setEndValue(0)
        self._sidebar_anim.start()

    def _on_sidebar_anim_finished(self) -> None:
        pass

    def _sidebar_nav_select(self, page_idx: int) -> None:
        for i, item in enumerate(self._sidebar_nav_items):
            item.set_checked(i == page_idx)
        if hasattr(self, '_info_item'):
            self._info_item.set_checked(page_idx == 2)
        self._content_stack.setCurrentIndex(page_idx)
        if self._sidebar_open:
            self._close_sidebar()

    # ------------------------------------------------------------------
    # Event filter — Ctrl+V paste intercept on lat field
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if (
            self.isVisible()
            and self._sidebar_open
            and event.type() == QEvent.Type.MouseButtonPress
            and hasattr(event, "globalPosition")
        ):
            global_pos = event.globalPosition().toPoint()
            sidebar_pos = self._sidebar_panel.mapFromGlobal(global_pos)
            icon_pos = self._title_bar._icon_btn.mapFromGlobal(global_pos)
            inside_sidebar = self._sidebar_panel.rect().contains(sidebar_pos)
            inside_toggle = self._title_bar._icon_btn.rect().contains(icon_pos)
            if not inside_sidebar and not inside_toggle:
                self._close_sidebar()

        # Activate 3D preview when focus moves to either coordinate field
        if (event.type() == QEvent.Type.FocusIn
                and hasattr(self, '_lon_input')
                and obj in (self._lat_input, self._lon_input)):
            self._try_activate_preview()

        # Ctrl+V paste intercept on lat field
        if obj is self._lat_input and event.type() == QEvent.Type.KeyPress:
            ke = event
            if (ke.key() == Qt.Key.Key_V
                    and ke.modifiers() & Qt.KeyboardModifier.ControlModifier):
                clipboard_text = QApplication.clipboard().text()
                parsed = _parse_paste(clipboard_text)
                if parsed:
                    lat, lon = parsed
                    self._lat_input.setText(str(lat))
                    self._lon_input.setText(str(lon))
                    return True   # consume — don't fall through to default paste
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_set_or_stop(self) -> None:
        if self._navigating:
            self._on_clear()
        else:
            self._on_set()

    def _on_set(self) -> None:
        lat_text = self._lat_input.text().strip()
        lon_text = self._lon_input.text().strip()

        # Accept a full POI string pasted into the lat field.
        # Round to 4 dp so the result always passes the precision check.
        parsed = _parse_paste(lat_text)
        if parsed:
            lat_text = str(round(parsed[0], 4))
            lon_text = str(round(parsed[1], 4))
            self._lat_input.setText(lat_text)
            self._lon_input.setText(lon_text)

        lat = _validate_coord(lat_text, -90.0, 90.0)
        lon = _validate_coord(lon_text, -180.0, 180.0)

        if lat is None or lon is None:
            self._show_error("Wrong data entered.")
            return

        self._clear_error()
        radius = self._radius_m if self._radius_m else DEFAULT_PLANET_RADIUS_M
        body_name = (self._selected_body.name if self._selected_body
                     else self._body_name_input.text().strip() or None)
        self._save_history(lat, lon, body_name)
        self._navigating = True
        self._set_btn.set_icon(_NavIcon.STOP, "Stop Navigation")
        self._set_btn.setEnabled(True)
        self.target_set.emit(lat, lon, radius, body_name, self._last_system)

    def _on_clear(self) -> None:
        self._lat_input.clear()
        self._lon_input.clear()
        self._body_name_input.clear()
        self._clear_error()
        self._planet_preview.set_target(None, None)
        self._navigating = False
        self._set_btn.set_icon(_NavIcon.SEND, "Set Target")
        # Re-evaluate enabled state based on body name field
        has_name = bool(self._body_name_input.text().strip())
        self._set_btn.setEnabled(has_name)
        self.target_cleared.emit()

    def _update_preview_marker(self) -> None:
        if not self._planet_preview.is_active:
            return
        lat = _validate_coord(self._lat_input.text(), -90.0, 90.0)
        lon = _validate_coord(self._lon_input.text(), -180.0, 180.0)
        self._planet_preview.set_target(lat, lon)

    def _show_error(self, msg: str) -> None:
        self._error_label.setStyleSheet(f"background: transparent; color: {COLOR_ERROR};")
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _show_success(self, msg: str) -> None:
        self._error_label.setStyleSheet(f"background: transparent; color: {_COL_ACTIVE};")
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setVisible(False)
        self._error_label.setText("")

    def _on_coord_picked(self, lat: float, lon: float) -> None:
        """Fill coordinate inputs when the user clicks a point on the planet preview."""
        self._lat_input.setText(str(lat))
        self._lon_input.setText(str(lon))

    def _on_quick_bookmark(self) -> None:
        """Capture current fields and prompt for a name via dialog."""
        lat = _validate_coord(self._lat_input.text(), -90.0, 90.0)
        lon = _validate_coord(self._lon_input.text(), -180.0, 180.0)
        if lat is None or lon is None:
            self._show_error("Cannot bookmark: Invalid or empty coordinates.")
            return

        # Pre-fill data for the dialog
        system = self._last_system or ""
        body = self._selected_body.name if self._selected_body else (self._body_name_input.text().strip() or "")
        
        initial_data = {
            "name": "", # Leave name blank for user to input
            "system": system,
            "body": body,
            "lat": lat,
            "lon": lon
        }

        dlg = _BookmarkDialog(self, initial_data=initial_data)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_b = dlg.get_data()
            if new_b:
                self._bookmarks.append(new_b)
                self._save_bookmarks()
                self._refresh_bookmarks()
                self._show_success("Bookmark saved.")
                QTimer.singleShot(2000, self._clear_error)

    def _on_random(self) -> None:
        """Populate latitude and longitude with random valid values."""
        lat = random.uniform(-90.0, 90.0)
        lon = random.uniform(-180.0, 180.0)
        self._lat_input.setText(f"{lat:.4f}")
        self._lon_input.setText(f"{lon:.4f}")
        self._clear_error()
        self._update_preview_marker()

    def _on_update_clicked(self) -> None:
        """Apply the update if the download is ready; ignore if still downloading."""
        if getattr(self, "_update_new_exe", None):
            self.apply_update.emit(self._update_version, self._update_new_exe)

    def _on_body_name_changed(self, text: str) -> None:
        """Track body selection state as the user types; preview is not shown yet.

        The 3D preview is deferred until the user moves focus to the coordinate
        fields (see _try_activate_preview / eventFilter).
        """
        name = text.strip()
        has_name = bool(name)
        self._set_btn.setEnabled(has_name or self._navigating)
        self._bookmark_btn.setEnabled(has_name)

        if not name:
            self._selected_body = None
            self._radius_m      = 0.0
            return

        match = next(
            (b for b in self._bodies if b.name.lower() == name.lower()),
            None,
        )
        if match is not None:
            self._selected_body = match
            self._radius_m      = match.radius_m
            self._planet_name_label.setText(match.name)
        else:
            self._selected_body = None
            self._radius_m      = 0.0

    def _try_activate_preview(self) -> None:
        """Show the 3D preview when the user moves focus to the coordinate fields.

        Only activates if a body name is present and the preview is not already
        showing (avoids re-triggering the fade-in on repeated focus events).
        """
        if self._planet_preview.is_active:
            return
        if not self._body_name_input.text().strip():
            return
        unknown = self._selected_body is None
        self._planet_preview.reset_rotation(0.0, 0.0)
        self._planet_preview.set_active(True, unknown=unknown)

    # ------------------------------------------------------------------
    # Target history
    # ------------------------------------------------------------------

    def _load_history(self) -> list[dict]:
        s = QSettings("ED-Navigator", "Overlay")
        raw = s.value("target_history", "[]")
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_history(self, lat: float, lon: float, body: str | None) -> None:
        entry = {"lat": lat, "lon": lon, "body": body}
        # Remove duplicate entry if already present
        self._target_history = [
            e for e in self._target_history
            if not (e["lat"] == lat and e["lon"] == lon)
        ]
        self._target_history.insert(0, entry)
        self._target_history = self._target_history[:10]
        s = QSettings("ED-Navigator", "Overlay")
        s.setValue("target_history", json.dumps(self._target_history))
        self._history_btn.setEnabled(True)

    def _show_history_menu(self) -> None:
        if not self._target_history or self._history_menu_open:
            return
        self._history_menu_open = True
        menu = _RoundedMenu(self)

        rows    = []
        actions = []
        for entry in self._target_history:
            lat  = entry["lat"]
            lon  = entry["lon"]
            body = entry.get("body") or "Unknown Body"
            coords = f"{lat:.2f}, {lon:.2f}"
            
            wa = QWidgetAction(menu)
            row = _MenuRow(body, coords)
            wa.setDefaultWidget(row)
            wa.setData(entry)
            menu.addAction(wa)
            rows.append(row)
            actions.append(wa)

        def _on_history_hover(action):
            for r, w in zip(rows, actions):
                r.set_hovered(action is w)

        menu.hovered.connect(_on_history_hover)

        # Dynamic font scaling: shrink until menu fits the window width.
        win_w = self.width()
        font_size = _SZ_LABEL - 1
        _MIN_FONT = 7
        while font_size >= _MIN_FONT:
            for r in rows:
                r.set_font_size(font_size)
            menu.setStyleSheet(_menu_ss(font_size))
            menu.adjustSize()
            hint = menu.sizeHint()
            if hint.width() <= win_w:
                break
            font_size -= 1

        trigger = self._history_btn
        menu.setMinimumWidth(trigger.width())
        menu.adjustSize()
        hint = menu.sizeHint()

        # Centre horizontally under the trigger.
        pos = trigger.mapToGlobal(trigger.rect().bottomLeft())
        pos.setX(pos.x() + (trigger.width() - hint.width()) // 2)

        chosen = menu.exec(pos)
        QTimer.singleShot(200, lambda: setattr(self, '_history_menu_open', False))
        if chosen:
            entry = chosen.data()
            self._lat_input.setText(str(entry["lat"]))
            self._lon_input.setText(str(entry["lon"]))
            body = entry.get("body") or ""
            self._body_name_input.setText(body)

    def _show_body_menu(self) -> None:
        if not self._bodies or self._menu_open:
            return
        self._menu_open = True
        menu = _RoundedMenu(self)

        def _natural_key(b):
            return [int(t) if t.isdigit() else t.lower()
                    for t in re.split(r'(\d+)', b.name)]

        rows    = []
        actions = []
        for body in sorted(self._bodies, key=_natural_key):
            wa = QWidgetAction(menu)
            row = _MenuRow(body.name, f"{body.radius_m / 1000:.0f} km")
            wa.setDefaultWidget(row)
            wa.setData(body)
            menu.addAction(wa)
            rows.append(row)
            actions.append(wa)

        def _on_body_hover(action):
            for r, w in zip(rows, actions):
                r.set_hovered(action is w)

        menu.hovered.connect(_on_body_hover)

        # Dynamic font scaling: shrink until menu fits within the window bounds
        win_tl = self.mapToGlobal(QPoint(0, 0))
        win_w  = self.width()
        win_h  = self.height()

        font_size = _SZ_LABEL - 1
        _MIN_FONT = 7
        while font_size >= _MIN_FONT:
            for row in rows:
                row.set_font_size(font_size)
            menu.setStyleSheet(_menu_ss(font_size))
            menu.adjustSize()
            hint = menu.sizeHint()
            if hint.width() <= win_w and hint.height() <= win_h:
                break
            font_size -= 1

        trigger = self._planet_name_label
        menu.setMinimumWidth(trigger.width())
        menu.adjustSize()
        hint = menu.sizeHint()

        # Centre the menu under the trigger (with a small detach gap), then clamp to window edges
        x   = trigger.mapToGlobal(trigger.rect().bottomLeft()).x()
        x  += (trigger.width() - hint.width()) // 2
        pos = trigger.mapToGlobal(trigger.rect().bottomLeft())
        pos.setX(x)
        pos.setY(pos.y() + 6)  # detach gap between button and menu

        win_right  = win_tl.x() + win_w
        win_bottom = win_tl.y() + win_h
        clamped_x = max(win_tl.x(), min(pos.x(), win_right  - hint.width()))
        clamped_y = max(win_tl.y(), min(pos.y(), win_bottom - hint.height()))
        pos.setX(clamped_x)
        pos.setY(clamped_y)

        chosen = menu.exec(pos)
        QTimer.singleShot(200, lambda: setattr(self, '_menu_open', False))
        if chosen:
            body = chosen.data()
            self._selected_body = body
            self._radius_m      = body.radius_m
            self._planet_name_label.setText(body.name)

            # Clear stale coordinates from any previously selected body
            self._lat_input.clear()
            self._lon_input.clear()
            self._body_name_input.setText(body.name)
            self._clear_error()

            # Activate the 3D preview centred on the new body (no stale marker)
            self._planet_preview.set_target(None, None)
            self._planet_preview.reset_rotation(0.0, 0.0)
            self._planet_preview.set_active(True)

    # ------------------------------------------------------------------
    # Widget factories
    # ------------------------------------------------------------------

    @staticmethod
    def _make_line_edit(placeholder: str) -> QLineEdit:
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        w.setFont(QFont(_FONT_MONO, _SZ_INPUT))
        w.setStyleSheet(
            f"QLineEdit {{ background: {_COL_INPUT_BG}; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_BORDER}; border-radius: 3px;"
            f" padding: 3px 6px; }}"
            f"QLineEdit:hover {{ border-color: {_COL_LABEL}; }}"
            f"QLineEdit:focus {{ border-color: {_COL_ACTIVE}; }}"
            f"QLineEdit::placeholder {{ color: {_COL_DIM}; }}"
        )
        return w

    @staticmethod
    def _make_button(text: str) -> QPushButton:
        w = QPushButton(text)
        w.setFont(QFont(_FONT, _SZ_BTN, QFont.Weight.Bold))
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        w.setStyleSheet(
            f"QPushButton {{ background: {_COL_INPUT_BG}; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 3px;"
            f" padding: 4px 10px; letter-spacing: 0px; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE}; background: #282828; }}"
            f"QPushButton:pressed {{ background: #7A3D00; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        return w
