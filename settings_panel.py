# settings_panel.py
# Collapsible coordinate input panel that slides in from the right edge
# of the overlay window.  It validates inputs and parses pasted coordinate
# strings from the game's POI clipboard format.
#
# Emits two Qt signals:
#   target_set(lat: float, lon: float)
#   target_cleared()

import re
from typing import Optional

from PyQt6.QtCore    import Qt, QTimer, pyqtSignal
from PyQt6.QtGui     import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame,
)

from constants import (
    COLOR_ORANGE, COLOR_ERROR, FONT_FAMILY, FONT_SIZE_PANEL,
    PANEL_WIDTH, PANEL_ANIM_STEPS, PANEL_ANIM_MS,
    WINDOW_WIDTH, WINDOW_HEIGHT,
)

# ---------------------------------------------------------------------------
# Regex for pasted POI format: "Lat: -22.45 / Lon: 137.88"
# Also accepts simpler forms like "-22.45, 137.88" or "-22.45 137.88"
# ---------------------------------------------------------------------------
_POI_PATTERN = re.compile(
    r"lat[:\s]*([+-]?\d+\.?\d*)\s*[/,]?\s*lon[:\s]*([+-]?\d+\.?\d*)",
    re.IGNORECASE,
)
_SIMPLE_PATTERN = re.compile(
    r"^([+-]?\d+\.?\d*)\s*[,\s]\s*([+-]?\d+\.?\d*)$"
)


def _parse_paste(text: str) -> Optional[tuple[float, float]]:
    """
    Try to extract (lat, lon) from a pasted string.
    Returns None if the text cannot be parsed.
    """
    m = _POI_PATTERN.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _SIMPLE_PATTERN.match(text.strip())
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


# ---------------------------------------------------------------------------
# Styled helpers
# ---------------------------------------------------------------------------

def _styled_line_edit(placeholder: str) -> QLineEdit:
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL))
    w.setStyleSheet(
        f"QLineEdit {{"
        f"  background: #1a1a1a;"
        f"  color: {COLOR_ORANGE};"
        f"  border: 1px solid #FF6B0066;"
        f"  border-radius: 3px;"
        f"  padding: 3px 6px;"
        f"}}"
        f"QLineEdit:focus {{"
        f"  border-color: {COLOR_ORANGE};"
        f"}}"
    )
    return w


def _styled_button(text: str, primary: bool = False) -> QPushButton:
    bg     = COLOR_ORANGE if primary else "#2a2a2a"
    fg     = "#000000"    if primary else COLOR_ORANGE
    border = COLOR_ORANGE
    w = QPushButton(text)
    w.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL, QFont.Weight.Bold))
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.setStyleSheet(
        f"QPushButton {{"
        f"  background: {bg}; color: {fg};"
        f"  border: 1px solid {border};"
        f"  border-radius: 3px; padding: 4px 10px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: {'#FF8C30' if primary else '#3a3a3a'};"
        f"}}"
        f"QPushButton:pressed {{ background: #cc5500; }}"
    )
    return w


# ---------------------------------------------------------------------------
# SettingsPanel widget
# ---------------------------------------------------------------------------

class SettingsPanel(QWidget):
    """
    Collapsible panel shown at the right side of the overlay window.
    Slides in/out with a simple timer-based animation.
    """

    target_set     = pyqtSignal(float, float)  # emitted when user sets target
    target_cleared = pyqtSignal()              # emitted when user clears target

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._visible_state = False   # True = panel is open
        self._anim_step     = 0
        self._anim_timer    = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_tick)

        self._build_ui()
        self._position_hidden()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def toggle(self) -> None:
        """Open the panel if closed; close it if open."""
        self._visible_state = not self._visible_state
        self._anim_step = 0
        self._anim_timer.start(PANEL_ANIM_MS)

    def is_open(self) -> bool:
        return self._visible_state

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(
            "background: rgba(10, 10, 10, 220);"
            f"border-left: 1px solid {COLOR_ORANGE}44;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title = QLabel("SET TARGET")
        title.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL + 1, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_ORANGE}; border: none;")
        layout.addWidget(title)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLOR_ORANGE}44; border: none; border-top: 1px solid {COLOR_ORANGE}44;")
        layout.addWidget(line)

        # Latitude input
        lat_label = QLabel("Latitude  (−90 to 90)")
        lat_label.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL - 1))
        lat_label.setStyleSheet(f"color: {COLOR_ORANGE}99; border: none;")
        layout.addWidget(lat_label)

        self._lat_input = _styled_line_edit("e.g.  −22.4500")
        self._lat_input.textChanged.connect(self._clear_error)
        layout.addWidget(self._lat_input)

        # Longitude input
        lon_label = QLabel("Longitude  (−180 to 180)")
        lon_label.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL - 1))
        lon_label.setStyleSheet(f"color: {COLOR_ORANGE}99; border: none;")
        layout.addWidget(lon_label)

        self._lon_input = _styled_line_edit("e.g.  137.8800")
        self._lon_input.textChanged.connect(self._clear_error)
        layout.addWidget(self._lon_input)

        # Paste hint
        paste_hint = QLabel("Paste 'Lat: x / Lon: y' to auto-fill")
        paste_hint.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL - 2))
        paste_hint.setStyleSheet(f"color: {COLOR_ORANGE}55; border: none;")
        paste_hint.setWordWrap(True)
        layout.addWidget(paste_hint)

        # Error label (hidden until needed)
        self._error_label = QLabel("")
        self._error_label.setFont(QFont(FONT_FAMILY, FONT_SIZE_PANEL - 1))
        self._error_label.setStyleSheet(f"color: {COLOR_ERROR}; border: none;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._set_btn   = _styled_button("Set Target", primary=True)
        self._clear_btn = _styled_button("Clear")

        self._set_btn.clicked.connect(self._on_set)
        self._clear_btn.clicked.connect(self._on_clear)

        btn_layout.addWidget(self._set_btn)
        btn_layout.addWidget(self._clear_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

        # Install paste intercept on lat field to handle full POI strings
        self._lat_input.installEventFilter(self)

    # ------------------------------------------------------------------
    # Event filter — intercept paste on lat field for POI auto-parse
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui  import QKeyEvent, QClipboard
        from PyQt6.QtWidgets import QApplication

        if obj is self._lat_input and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event
            # Ctrl+V paste
            if ke.key() == Qt.Key.Key_V and ke.modifiers() & Qt.KeyboardModifier.ControlModifier:
                clipboard_text = QApplication.clipboard().text()
                parsed = _parse_paste(clipboard_text)
                if parsed:
                    lat, lon = parsed
                    self._lat_input.setText(str(lat))
                    self._lon_input.setText(str(lon))
                    return True   # consume event, don't do default paste
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_set(self):
        lat_text = self._lat_input.text().strip()
        lon_text = self._lon_input.text().strip()

        # Try to parse as POI paste if lat field looks like a full string
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
        self.target_set.emit(lat, lon)

    def _on_clear(self):
        self._lat_input.clear()
        self._lon_input.clear()
        self._clear_error()
        self.target_cleared.emit()

    def _show_error(self, msg: str):
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _clear_error(self):
        self._error_label.setVisible(False)
        self._error_label.setText("")

    # ------------------------------------------------------------------
    # Slide animation
    # ------------------------------------------------------------------

    def _position_hidden(self):
        """Place the panel fully off-screen to the right."""
        self.move(WINDOW_WIDTH, 0)
        self.setFixedHeight(WINDOW_HEIGHT)

    def _anim_tick(self):
        self._anim_step += 1
        progress = self._anim_step / PANEL_ANIM_STEPS
        progress = min(progress, 1.0)

        # Ease-out cubic
        t = 1.0 - (1.0 - progress) ** 3

        if self._visible_state:
            # Slide in: from WINDOW_WIDTH to WINDOW_WIDTH - PANEL_WIDTH
            x = int(WINDOW_WIDTH - t * PANEL_WIDTH)
        else:
            # Slide out: from WINDOW_WIDTH - PANEL_WIDTH to WINDOW_WIDTH
            x = int(WINDOW_WIDTH - PANEL_WIDTH + t * PANEL_WIDTH)

        self.move(x, 0)
        self.setFixedHeight(WINDOW_HEIGHT)

        if self._anim_step >= PANEL_ANIM_STEPS:
            self._anim_timer.stop()
