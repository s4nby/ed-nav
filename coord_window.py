# coord_window.py
# Standalone dark-themed coordinate input window.
# Always-on-top but NOT click-through, so the user can interact with it.
#
# Shows: current body name + auto-detected radius (from tracker NavResult),
#        Lat/Lon inputs with paste-parse support, Set/Clear buttons,
#        live tracking status.
#
# Closing the window hides it instead of destroying it (preserves state).

import re
from typing import Optional

from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtGui     import QFont
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from constants import (
    COLOR_ERROR, COLOR_ORANGE,
    DEFAULT_PLANET_RADIUS_M,
    FONT_FAMILY,
)

# ---------------------------------------------------------------------------
# Coord-window local style constants (ED-style theme)
# ---------------------------------------------------------------------------
_FONT        = "Agency FB"   # condensed geometric — closest Windows built-in to ED's UI font
_FONT_MONO   = "Consolas"    # used for coordinate inputs so numbers stay aligned

_SZ_TITLE    = 14   # "SET TARGET" header
_SZ_LABEL    = 11   # field labels (BODY NAME, LATITUDE…)
_SZ_HINT     = 10   # hint / FSS hint text
_SZ_INPUT    = 11   # line-edit content
_SZ_STATUS   = 10   # status line
_SZ_BTN      = 11   # button text

# Orange palette — three tiers matching ED's UI hierarchy
_COL_ACTIVE  = "#FF8C00"   # bright — title, active elements
_COL_LABEL   = "#CC6600"   # mid    — field labels, button borders
_COL_DIM     = "#7A3D00"   # dim    — hints, inactive text
_COL_INPUT_BG = "#0f0f0f"  # input background
_COL_BORDER  = "#FF8C0055" # subtle orange border

FONT_SIZE_PANEL = 10   # kept so nothing else in the file breaks

from tracker import NavResult
from journal import LandableBody

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


# ---------------------------------------------------------------------------
# CoordWindow
# ---------------------------------------------------------------------------

class CoordWindow(QWidget):
    """
    Always-on-top settings/input window.
    Emits target_set(lat, lon, radius_m) and target_cleared().
    """

    target_set     = pyqtSignal(float, float, float)  # lat, lon, radius_m
    target_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("ED Navigator")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("background: #0a0a0a;")

        self._radius_m:      float = 0.0
        self._bodies:        list[LandableBody] = []
        self._selected_body: LandableBody | None = None
        self._last_system:   str = ""

        self._build_ui()
        self.setMinimumWidth(320)
        self.adjustSize()
        self.setMaximumSize(self.width() * 2, self.height() * 2)

    def showEvent(self, event):
        super().showEvent(event)
        self._remove_maximize_button()

    def closeEvent(self, event):
        """Hide instead of destroy so state is preserved."""
        event.ignore()
        self.hide()

    def _remove_maximize_button(self) -> None:
        try:
            import ctypes
            GWL_STYLE     = -16
            WS_MAXIMIZEBOX = 0x00010000
            hwnd  = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_MAXIMIZEBOX)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API called from main's push_nav()
    # ------------------------------------------------------------------

    def update_status(self, nav: NavResult, has_target: bool) -> None:
        # Silently absorb live planet radius for Haversine accuracy
        if nav.planet_radius_m and self._selected_body is None:
            self._radius_m = nav.planet_radius_m

        if not nav.has_lat_long:
            self._status_label.setText("Status: No signal")
        elif not has_target:
            self._status_label.setText("Status: Awaiting target")
        elif nav.arrived:
            self._status_label.setText("Status: ARRIVED")
        elif nav.distance_m is not None:
            dist = nav.distance_m
            dist_str = f"{dist / 1000:.1f} km" if dist >= 1000 else f"{int(dist)} m"
            self._status_label.setText(f"Status: TRACKING  —  {dist_str}")
        else:
            self._status_label.setText("Status: TRACKING")

    def update_bodies(self, bodies: list[LandableBody], system: str, scan_required: bool = False) -> None:
        """Called from push_nav() with the latest journal body list."""
        self._bodies = bodies

        # Clear selection when the system changes
        if system != self._last_system:
            self._last_system    = system
            self._selected_body  = None
            self._radius_m       = 0.0

        # Always keep the button count in sync with the live body list
        n = len(bodies)
        if n:
            self._body_btn.setText(
                f"{n} landable bod{'y' if n == 1 else 'ies'} detected"
            )
            self._body_btn.setEnabled(True)
        elif scan_required:
            self._body_btn.setText("Scan required")
            self._body_btn.setEnabled(False)
        else:
            self._body_btn.setText("0 landable bodies detected")
            self._body_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Title
        title = QLabel("SET TARGET")
        title.setFont(QFont(_FONT, _SZ_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {_COL_ACTIVE};"
            f" letter-spacing: 3px;"
        )
        layout.addWidget(title)

        # Selected body display — shown at top once user picks a body.
        # Styled as a plain label but is a button so it stays clickable
        # (click to reopen the menu and pick a different target).
        self._selected_label = QPushButton("")
        self._selected_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        self._selected_label.setStyleSheet(
            f"QPushButton {{ color: {_COL_ACTIVE}; background: transparent;"
            f" border: none; padding: 0; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ color: #FFAA33; }}"
        )
        self._selected_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected_label.clicked.connect(self._show_body_menu)
        self._selected_label.hide()
        layout.addWidget(self._selected_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Landable bodies button — centred, directly below title
        self._body_btn = self._make_button("0 landable bodies detected")
        self._body_btn.setEnabled(False)
        self._body_btn.clicked.connect(self._show_body_menu)
        layout.addWidget(self._body_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Body / radius info (updated when body is selected or player is on surface)
        self._body_label = QLabel(
            "FSS scan the desired planet, or approach within at least "
            "30 LS of it to be detected."
        )
        self._body_label.setFont(QFont(_FONT, _SZ_HINT))
        self._body_label.setStyleSheet(f"color: {_COL_DIM};")
        self._body_label.setWordWrap(True)
        layout.addWidget(self._body_label)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"border: none; border-top: 1px solid {COLOR_ORANGE}44;"
        )
        layout.addWidget(line)

        # Body name (optional manual entry)
        body_name_label = QLabel("BODY NAME")
        body_name_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        body_name_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")
        layout.addWidget(body_name_label)

        self._body_name_input = self._make_line_edit("e.g.  Synuefe XR-H d11-102 1 b")
        layout.addWidget(self._body_name_input)

        # Latitude
        lat_label = QLabel("LATITUDE  (−90 to 90)")
        lat_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lat_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")
        layout.addWidget(lat_label)

        self._lat_input = self._make_line_edit("e.g.  −22.4500")
        self._lat_input.textChanged.connect(self._clear_error)
        self._lat_input.installEventFilter(self)
        layout.addWidget(self._lat_input)

        # Longitude
        lon_label = QLabel("LONGITUDE  (−180 to 180)")
        lon_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lon_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")
        layout.addWidget(lon_label)

        self._lon_input = self._make_line_edit("e.g.  137.8800")
        self._lon_input.textChanged.connect(self._clear_error)
        layout.addWidget(self._lon_input)



        # Error label
        self._error_label = QLabel("")
        self._error_label.setFont(QFont(_FONT, _SZ_HINT))
        self._error_label.setStyleSheet(f"color: {COLOR_ERROR};")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # Tracking status
        self._status_label = QLabel("Status: No target set")
        self._status_label.setFont(QFont(_FONT, _SZ_STATUS))
        self._status_label.setStyleSheet(f"color: {_COL_LABEL};")
        layout.addWidget(self._status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._set_btn   = self._make_button("Set Target", primary=True)
        self._clear_btn = self._make_button("Clear")

        self._set_btn.clicked.connect(self._on_set)
        self._clear_btn.clicked.connect(self._on_clear)

        btn_layout.addWidget(self._set_btn)
        btn_layout.addWidget(self._clear_btn)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Event filter — Ctrl+V paste intercept on lat field
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent

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

    def _on_set(self) -> None:
        lat_text = self._lat_input.text().strip()
        lon_text = self._lon_input.text().strip()

        # Accept a full POI string pasted into the lat field
        parsed = _parse_paste(lat_text)
        if parsed:
            lat, lon = parsed
            self._lat_input.setText(str(lat))
            self._lon_input.setText(str(lon))
            lat_text = str(lat)
            lon_text = str(lon)

        errors = []

        try:
            lat = float(lat_text)
        except ValueError:
            errors.append("Latitude must be a number.")
            lat = None

        try:
            lon = float(lon_text)
        except ValueError:
            errors.append("Longitude must be a number.")
            lon = None

        if lat is not None and not (-90.0 <= lat <= 90.0):
            errors.append("Latitude must be between −90 and 90.")
        if lon is not None and not (-180.0 <= lon <= 180.0):
            errors.append("Longitude must be between −180 and 180.")

        if errors:
            self._show_error(" ".join(errors))
            return

        self._clear_error()
        radius = self._radius_m if self._radius_m else DEFAULT_PLANET_RADIUS_M
        self.target_set.emit(lat, lon, radius)

    def _on_clear(self) -> None:
        self._lat_input.clear()
        self._lon_input.clear()
        self._body_name_input.clear()
        self._clear_error()
        self.target_cleared.emit()

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setVisible(False)
        self._error_label.setText("")

    def _show_body_menu(self) -> None:
        if not self._bodies:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: #0f0f0f; color: {_COL_ACTIVE};"
            f" font-family: '{_FONT}'; font-size: {_SZ_LABEL}pt;"
            f" border: 1px solid {_COL_LABEL}; }}"
            f"QMenu::item {{ padding: 4px 14px; }}"
            f"QMenu::item:selected {{ background: {_COL_LABEL}44; color: {_COL_ACTIVE}; }}"
        )
        for body in sorted(self._bodies, key=lambda b: b.name):
            label  = f"{body.name}   ({body.radius_m / 1000:.0f} km)"
            action = menu.addAction(label)
            action.setData(body)

        menu.setMinimumWidth(self._body_btn.width())
        pos    = self._body_btn.mapToGlobal(self._body_btn.rect().bottomLeft())
        chosen = menu.exec(pos)
        if chosen:
            body = chosen.data()
            self._selected_body  = body
            self._radius_m       = body.radius_m
            self._body_name_input.setText(body.name)

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
            f" border: 1px solid {_COL_LABEL}; border-radius: 2px;"
            f" padding: 4px 7px; }}"
            f"QLineEdit:focus {{ border-color: {_COL_ACTIVE}; }}"
            f"QLineEdit::placeholder {{ color: {_COL_DIM}; }}"
        )
        return w

    @staticmethod
    def _make_button(text: str, primary: bool = False) -> QPushButton:
        bg = _COL_ACTIVE  if primary else "#1a1a1a"
        fg = "#050505"    if primary else _COL_ACTIVE
        w  = QPushButton(text)
        w.setFont(QFont(_FONT, _SZ_BTN, QFont.Weight.Bold))
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        w.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 2px;"
            f" padding: 4px 12px; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE};"
            f" background: {'#FFAA33' if primary else '#2a2a2a'}; }}"
            f"QPushButton:pressed {{ background: #994400; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        return w
