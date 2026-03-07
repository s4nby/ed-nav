# coord_window.py
# Standalone dark-themed coordinate input window.
# Always-on-top but NOT click-through, so the user can interact with it.
#
# Shows: current body name + auto-detected radius (from tracker NavResult),
#        Lat/Lon inputs with paste-parse support, Set/Clear buttons,
#        live tracking status.
#
# Closing the window hides it instead of destroying it (preserves state).

import ctypes
import json
import re
from typing import Optional

from PyQt6.QtCore    import QEvent, QPoint, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui     import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from constants import (
    COLOR_ERROR, COLOR_ORANGE,
    DEFAULT_PLANET_RADIUS_M,
    FONT_FAMILY,
    VERSION,
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

from tracker import NavResult
from journal import LandableBody
from planet_preview import PlanetPreviewWidget

# ---------------------------------------------------------------------------
# Eliding button — QPushButton that truncates its label with '...' on resize
# ---------------------------------------------------------------------------

class _ElidedButton(QPushButton):
    """QPushButton that elides its label to fit the available width."""

    _H_PAD   = 36         # total horizontal padding (18px × 2 from stylesheet)
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

    def _refresh(self) -> None:
        fm         = QFontMetrics(self.font())
        chevron_w  = fm.horizontalAdvance(self._CHEVRON)
        available  = max(0, self.width() - self._H_PAD - chevron_w)
        elided     = fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available)
        super().setText(elided + self._CHEVRON)


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

    target_set     = pyqtSignal(float, float, float, object)  # lat, lon, radius_m, body_name (str|None)
    target_cleared = pyqtSignal()
    move_overlay   = pyqtSignal()
    toggle_overlay = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("ED Navigator")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("background: #0a0a0a;")

        self._radius_m:      float = 0.0
        self._bodies:        list[LandableBody] = []
        self._selected_body: LandableBody | None = None
        self._last_system:   str = ""
        self._menu_open:         bool = False
        self._history_menu_open: bool = False
        self._target_history: list[dict] = self._load_history()

        self._build_ui()
        self.setFixedSize(420, 630)

    def showEvent(self, event):
        super().showEvent(event)
        self._remove_maximize_button()

    def closeEvent(self, event):
        """Hide instead of destroy so state is preserved."""
        event.ignore()
        self.hide()

    def _remove_maximize_button(self) -> None:
        try:
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

    def set_move_mode(self, active: bool) -> None:
        self._move_btn.setText("Done Moving" if active else "Move Overlay")


    def update_status(self, nav: NavResult, has_target: bool) -> None:
        # Silently absorb live planet radius for Haversine accuracy
        if nav.planet_radius_m and self._selected_body is None:
            self._radius_m = nav.planet_radius_m

        if not nav.has_lat_long:
            self._status_label.setText("Status: No signal")
        elif not has_target:
            self._status_label.setText("Status: Awaiting target")
        elif nav.body_mismatch:
            self._status_label.setText("Status: Approach target body")
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

        # Sync count label and list-button state
        _FSS_TIP = (
            "FSS scan the desired planet, or approach within at least "
            "30 LS of it to be detected."
        )
        n = len(bodies)
        if n:
            self._body_count_label.setText(f"Landable Bodies Detected: {n}")
            self._planet_name_label.setEnabled(True)
            self._planet_name_label.setToolTip("")
            self._body_count_label.setToolTip("")
        elif scan_required:
            self._body_count_label.setText("Scan Required")
            self._planet_name_label.setEnabled(False)
            self._planet_name_label.setToolTip(_FSS_TIP)
            self._body_count_label.setToolTip(_FSS_TIP)
        else:
            self._body_count_label.setText("Landable Bodies Detected: 0")
            self._planet_name_label.setEnabled(False)
            self._planet_name_label.setToolTip(_FSS_TIP)
            self._body_count_label.setToolTip(_FSS_TIP)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Three-column header: [list button] | [planet name] | [body count]
        _flat_btn_ss = (
            f"QPushButton {{ background: transparent; color: {_COL_DIM};"
            f" border: none; padding: 2px 4px;"
            f" font-family: '{_FONT}'; font-size: {_SZ_LABEL}pt;"
            f" font-weight: bold; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ color: {_COL_ACTIVE}; }}"
            f"QPushButton:disabled {{ color: #3D1E00; }}"
        )
        _flat_lbl_ss = (
            f"QLabel {{ background: transparent; border: none; }}"
        )

        self._planet_name_label = _ElidedButton("Select a Planet")
        self._planet_name_label.setFont(QFont(_FONT, _SZ_BTN, QFont.Weight.Bold))
        self._planet_name_label.setStyleSheet(
            f"QPushButton {{ background: #1a1a1a; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 2px;"
            f" padding: 6px 18px; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE}; background: #2a2a2a; }}"
            f"QPushButton:pressed {{ background: #994400; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        self._planet_name_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._planet_name_label.setEnabled(False)
        self._planet_name_label.clicked.connect(self._show_body_menu)

        self._body_count_label = QLabel("Landable Bodies Detected: 0")
        self._body_count_label.setFont(QFont(_FONT, _SZ_LABEL))
        self._body_count_label.setStyleSheet(
            f"QLabel {{ background: transparent; border: none; color: {_COL_DIM}; }}"
        )
        self._body_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        header_row.addWidget(self._planet_name_label, 1)
        header_row.addSpacing(10)
        header_row.addWidget(self._body_count_label)
        layout.addLayout(header_row)


        # 3D planet preview — hidden until a body is selected
        self._planet_preview = PlanetPreviewWidget()
        self._planet_preview.coord_picked.connect(self._on_coord_picked)
        layout.addWidget(self._planet_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"border: none; border-top: 1px solid {_COL_ACTIVE};"
        )
        layout.addWidget(line)

        # Body name row: label on the left, Recent ▾ flat-text trigger on the right
        self._recent_btn = QPushButton("Recent \u25be")
        self._recent_btn.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        self._recent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recent_btn.setStyleSheet(_flat_btn_ss)
        self._recent_btn.setEnabled(bool(self._target_history))
        self._recent_btn.setToolTip("Recently used targets")
        self._recent_btn.clicked.connect(self._show_history_menu)

        body_name_label = QLabel("BODY NAME")
        body_name_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        body_name_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")

        body_name_row = QHBoxLayout()
        body_name_row.setContentsMargins(0, 0, 0, 0)
        body_name_row.setSpacing(0)
        body_name_row.addWidget(body_name_label, 1)
        body_name_row.addWidget(self._recent_btn)
        layout.addLayout(body_name_row)

        self._body_name_input = self._make_line_edit("e.g.  Synuefe XR-H d11-102 1 b")
        layout.addWidget(self._body_name_input)

        # Latitude
        lat_label = QLabel("LATITUDE  (−90 to 90)")
        lat_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lat_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")
        layout.addWidget(lat_label)

        self._lat_input = self._make_line_edit("e.g.  −22.4500")
        self._lat_input.textChanged.connect(self._clear_error)
        self._lat_input.textChanged.connect(self._update_preview_marker)
        self._lat_input.installEventFilter(self)
        layout.addWidget(self._lat_input)

        # Longitude
        lon_label = QLabel("LONGITUDE  (−180 to 180)")
        lon_label.setFont(QFont(_FONT, _SZ_LABEL, QFont.Weight.Bold))
        lon_label.setStyleSheet(f"color: {_COL_LABEL}; letter-spacing: 1px;")
        layout.addWidget(lon_label)

        self._lon_input = self._make_line_edit("e.g.  137.8800")
        self._lon_input.textChanged.connect(self._clear_error)
        self._lon_input.textChanged.connect(self._update_preview_marker)
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

        # Buttons — 2×2 grid, all uniform size and style
        self._set_btn    = self._make_button("Set Target")
        self._clear_btn  = self._make_button("Clear")
        self._move_btn   = self._make_button("Move Overlay")
        self._toggle_btn = self._make_button("Hide/Show Overlay")

        self._set_btn.clicked.connect(self._on_set)
        self._clear_btn.clicked.connect(self._on_clear)
        self._move_btn.clicked.connect(self.move_overlay)
        self._toggle_btn.clicked.connect(self.toggle_overlay)
        self._toggle_btn.setToolTip("Shortcut: Ctrl+Shift+N")

        for btn in (self._set_btn, self._clear_btn, self._move_btn, self._toggle_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(6)
        btn_grid.addWidget(self._clear_btn,  0, 0)
        btn_grid.addWidget(self._set_btn,    0, 1)
        btn_grid.addWidget(self._move_btn,   1, 0)
        btn_grid.addWidget(self._toggle_btn, 1, 1)
        layout.addLayout(btn_grid)

        layout.addStretch(1)

        version_label = QLabel(f"v{VERSION}")
        version_label.setFont(QFont(_FONT, 8))
        version_label.setStyleSheet(f"color: {_COL_DIM};")
        version_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version_label)

    # ------------------------------------------------------------------
    # Event filter — Ctrl+V paste intercept on lat field
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
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
        body_name = self._selected_body.name if self._selected_body else None
        self._save_history(lat, lon, body_name)
        self.target_set.emit(lat, lon, radius, body_name)

    def _on_clear(self) -> None:
        self._lat_input.clear()
        self._lon_input.clear()
        self._body_name_input.clear()
        self._clear_error()
        self._planet_preview.set_target(None, None)
        self.target_cleared.emit()

    def _update_preview_marker(self) -> None:
        if not self._planet_preview.is_active:
            return
        lat = _validate_coord(self._lat_input.text(), -90.0, 90.0)
        lon = _validate_coord(self._lon_input.text(), -180.0, 180.0)
        self._planet_preview.set_target(lat, lon)

    def _fit_to_header(self) -> None:
        """Resize window width to exactly fit the header row, snapping instantly."""
        m = self.layout().contentsMargins()
        h_margins = m.left() + m.right()

        name_w  = QFontMetrics(self._planet_name_label.font()).horizontalAdvance(
            self._planet_name_label.text()
        ) + 16   # button horizontal padding (2×4px stylesheet + 4px buffer)
        count_w = QFontMetrics(self._body_count_label.font()).horizontalAdvance(
            self._body_count_label.text()
        ) + 8

        target_w = max(self.minimumWidth(), name_w + count_w + h_margins + 6)
        if target_w != self.width():
            self.resize(target_w, self.height())

    @staticmethod
    def _try_parse_float(text: str) -> float | None:
        try:
            return float(text.strip())
        except ValueError:
            return None

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setVisible(False)
        self._error_label.setText("")

    def _on_coord_picked(self, lat: float, lon: float) -> None:
        """Fill coordinate inputs when the user clicks a point on the planet preview."""
        self._lat_input.setText(str(lat))
        self._lon_input.setText(str(lon))

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
        self._recent_btn.setEnabled(True)

    def _show_history_menu(self) -> None:
        if not self._target_history or self._history_menu_open:
            return
        self._history_menu_open = True
        menu = QMenu(self)
        for entry in self._target_history:
            lat  = entry["lat"]
            lon  = entry["lon"]
            body = entry.get("body")
            label = f"{lat:+.4f},  {lon:+.4f}"
            if body:
                label += f"   \u2014  {body}"
            action = menu.addAction(label)
            action.setData(entry)

        # Dynamic font scaling: shrink until menu fits the window width.
        # Height is intentionally unconstrained — the menu must be free to
        # overflow the window's bottom edge (see positioning note below).
        win_w = self.width()
        win_h = self.height()

        font_size = _SZ_LABEL
        _MIN_FONT = 7
        while font_size >= _MIN_FONT:
            menu.setStyleSheet(
                f"QMenu {{ background: #0a0a0a; color: {_COL_ACTIVE};"
                f" font-family: '{_FONT}'; font-size: {font_size}pt;"
                f" font-weight: bold; letter-spacing: 1px;"
                f" border: 1px solid {_COL_LABEL}; border-radius: 4px; }}"
                f"QMenu::item {{ padding: 6px 16px; border-radius: 2px;"
                f" margin: 1px 4px; }}"
                f"QMenu::item:selected {{ background: #2a2a2a;"
                f" border: 1px solid {_COL_LABEL}; color: {_COL_ACTIVE}; }}"
                f"QMenu::separator {{ height: 1px; background: {_COL_LABEL};"
                f" margin: 3px 8px; }}"
            )
            menu.adjustSize()
            hint = menu.sizeHint()
            if hint.width() <= win_w:
                break
            font_size -= 1

        trigger = self._recent_btn
        menu.setMinimumWidth(trigger.width())
        menu.adjustSize()
        hint = menu.sizeHint()

        # Centre horizontally under the trigger. No window-boundary clamp — the
        # footer position means clamping to win_bottom would push the menu back
        # up into the window content. Qt's QMenu is a native top-level popup and
        # handles screen-edge overflow (including upward flip) on its own.
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
        menu = QMenu(self)

        def _natural_key(b):
            return [int(t) if t.isdigit() else t.lower()
                    for t in re.split(r'(\d+)', b.name)]

        for body in sorted(self._bodies, key=_natural_key):
            label  = f"{body.name}   (Radius: {body.radius_m / 1000:.0f} km)"
            action = menu.addAction(label)
            action.setData(body)

        # Dynamic font scaling: shrink until menu fits within the window bounds
        win_tl = self.mapToGlobal(QPoint(0, 0))
        win_w  = self.width()
        win_h  = self.height()

        font_size = _SZ_LABEL
        _MIN_FONT = 7
        while font_size >= _MIN_FONT:
            menu.setStyleSheet(
                f"QMenu {{ background: #0a0a0a; color: {_COL_ACTIVE};"
                f" font-family: '{_FONT}'; font-size: {font_size}pt;"
                f" font-weight: bold; letter-spacing: 1px;"
                f" border: 1px solid {_COL_LABEL}; border-radius: 4px; }}"
                f"QMenu::item {{ padding: 6px 16px; border-radius: 2px;"
                f" margin: 1px 4px; }}"
                f"QMenu::item:selected {{ background: #2a2a2a;"
                f" border: 1px solid {_COL_LABEL}; color: {_COL_ACTIVE}; }}"
                f"QMenu::separator {{ height: 1px; background: {_COL_LABEL};"
                f" margin: 3px 8px; }}"
            )
            menu.adjustSize()
            hint = menu.sizeHint()
            if hint.width() <= win_w and hint.height() <= win_h:
                break
            font_size -= 1

        trigger = self._planet_name_label
        menu.setMinimumWidth(trigger.width())
        menu.adjustSize()
        hint = menu.sizeHint()

        # Centre the menu under the trigger, then clamp to window edges
        x   = trigger.mapToGlobal(trigger.rect().bottomLeft()).x()
        x  += (trigger.width() - hint.width()) // 2
        pos = trigger.mapToGlobal(trigger.rect().bottomLeft())
        pos.setX(x)

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
            f" border: 1px solid {_COL_LABEL}; border-radius: 2px;"
            f" padding: 4px 7px; }}"
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
            f"QPushButton {{ background: #1a1a1a; color: {_COL_ACTIVE};"
            f" border: 1px solid {_COL_LABEL}; border-radius: 2px;"
            f" padding: 6px 12px; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ border-color: {_COL_ACTIVE}; background: #2a2a2a; }}"
            f"QPushButton:pressed {{ background: #994400; }}"
            f"QPushButton:disabled {{ color: {_COL_DIM}; border-color: {_COL_DIM}; }}"
        )
        return w
