# overlay.py
# Minimal compass-needle overlay.
# Draws only when actively tracking: a slim needle pointing at the target
# (relative to player heading) and a distance readout below it.
# Invisible (fully transparent) when there is no target or no GPS signal.
# Always click-through (WS_EX_TRANSPARENT) except when in move mode.

import ctypes
import math
from typing import Optional

from PyQt6.QtCore    import Qt, QTimer, QPoint, QRectF
from PyQt6.QtCore    import QSettings
from PyQt6.QtGui     import QColor, QPainter, QPen, QBrush, QFont, QPainterPath
from PyQt6.QtWidgets import QWidget, QApplication

from constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    NEEDLE_LENGTH, NEEDLE_TAIL, NEEDLE_HALF_W,
    NEEDLE_ALPHA, NEEDLE_TAIL_ALPHA, TEXT_ALPHA,
    COLOR_ORANGE,
    FONT_FAMILY, FONT_SIZE_DIST,
    RENDER_INTERVAL_MS,
    MAX_ROTATE_PER_FRAME, PULSE_SPEED,
    ARRIVAL_DISTANCE_M,
)
from tracker import NavResult, shortest_arc

# Win32 constants
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

# Needle pivot point (centre of rotation)
_CX = WINDOW_WIDTH  // 2
_CY = WINDOW_HEIGHT // 2 - 6   # shift slightly up to leave room for text


class OverlayCanvas(QWidget):
    """Animated needle canvas."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)

        self._display_angle: float = 0.0
        self._pulse_phase:   float = 0.0

        self._nav:        NavResult = NavResult()
        self._has_target: bool      = False

        self._move_mode:  bool            = False
        self._drag_start: Optional[QPoint] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(RENDER_INTERVAL_MS)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update_nav(self, nav: NavResult, has_target: bool) -> None:
        self._nav        = nav
        self._has_target = has_target

    def set_move_mode(self, active: bool) -> None:
        self._move_mode  = active
        self._drag_start = None
        self.update()

    # ------------------------------------------------------------------
    # Mouse (move mode only)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._move_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._move_mode and self._drag_start is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            win   = self.window()
            win.move(win.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._move_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
        else:
            super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        nav = self._nav
        if nav.relative_bearing is not None and not nav.arrived:
            arc = shortest_arc(self._display_angle, nav.relative_bearing)
            arc = max(-MAX_ROTATE_PER_FRAME, min(MAX_ROTATE_PER_FRAME, arc))
            self._display_angle = (self._display_angle + arc) % 360.0
        if nav.arrived:
            self._pulse_phase += PULSE_SPEED
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Always clear to fully transparent first
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self._move_mode:
            self._draw_move_mode(p)
            p.end()
            return

        nav = self._nav

        # Nothing to show — stay invisible
        if not nav.has_lat_long or not self._has_target:
            p.end()
            return

        if nav.arrived:
            self._draw_arrived(p, nav.distance_m)
        else:
            self._draw_needle(p, self._display_angle)
            self._draw_distance(p, nav.distance_m)

        p.end()

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_needle(self, p: QPainter, angle_deg: float) -> None:
        """Slim two-part compass needle at angle_deg (0 = up = straight ahead)."""
        rad = math.radians(angle_deg)
        # Forward unit vector (screen: up is −y)
        fx =  math.sin(rad)
        fy = -math.cos(rad)
        # Perpendicular
        px =  math.cos(rad)
        py =  math.sin(rad)

        cx, cy = _CX, _CY

        # ── Forward triangle (bright) ──────────────────────────────────
        tip = (cx + NEEDLE_LENGTH * fx,  cy + NEEDLE_LENGTH * fy)
        bl  = (cx + NEEDLE_HALF_W * px,  cy + NEEDLE_HALF_W * py)
        br  = (cx - NEEDLE_HALF_W * px,  cy - NEEDLE_HALF_W * py)

        fwd_color = QColor(COLOR_ORANGE)
        fwd_color.setAlpha(NEEDLE_ALPHA)

        path = QPainterPath()
        path.moveTo(*tip)
        path.lineTo(*bl)
        path.lineTo(*br)
        path.closeSubpath()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fwd_color))
        p.drawPath(path)

        # ── Tail triangle (dim) ────────────────────────────────────────
        tail  = (cx - NEEDLE_TAIL * fx,        cy - NEEDLE_TAIL * fy)
        tw    = NEEDLE_HALF_W * 0.55
        tl    = (cx + tw * px,  cy + tw * py)
        tr    = (cx - tw * px,  cy - tw * py)

        tail_color = QColor(COLOR_ORANGE)
        tail_color.setAlpha(NEEDLE_TAIL_ALPHA)

        path2 = QPainterPath()
        path2.moveTo(*tail)
        path2.lineTo(*tl)
        path2.lineTo(*tr)
        path2.closeSubpath()

        p.setBrush(QBrush(tail_color))
        p.drawPath(path2)

        # ── Centre pivot dot ───────────────────────────────────────────
        dot_color = QColor(COLOR_ORANGE)
        dot_color.setAlpha(180)
        p.setBrush(QBrush(dot_color))
        p.drawEllipse(QPoint(cx, cy), 2, 2)

    def _draw_distance(self, p: QPainter, distance_m: Optional[float]) -> None:
        """Small distance label below the needle."""
        if distance_m is None:
            return
        if distance_m >= 1000.0:
            text = f"{distance_m / 1000.0:.1f} km"
        else:
            text = f"{int(distance_m)} m"

        color = QColor(COLOR_ORANGE)
        color.setAlpha(TEXT_ALPHA)
        p.setPen(QPen(color))
        p.setFont(QFont(FONT_FAMILY, FONT_SIZE_DIST))
        p.drawText(
            QRectF(0, WINDOW_HEIGHT - 20, WINDOW_WIDTH, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _draw_arrived(self, p: QPainter, distance_m: Optional[float]) -> None:
        """Pulsing dot + distance when within arrival threshold."""
        pulse = 0.55 + 0.45 * abs(math.sin(self._pulse_phase))
        cx, cy = _CX, _CY

        color = QColor(COLOR_ORANGE)
        color.setAlpha(int(240 * pulse))
        p.setPen(QPen(color, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = int(6 + 4 * pulse)
        p.drawEllipse(QPoint(cx, cy), r, r)

        dot = QColor(COLOR_ORANGE)
        dot.setAlpha(int(200 * pulse))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot))
        p.drawEllipse(QPoint(cx, cy), 3, 3)

        self._draw_distance(p, distance_m)

    def _draw_move_mode(self, p: QPainter) -> None:
        """Dashed border + DRAG label when repositioning."""
        orange = QColor(COLOR_ORANGE)
        orange.setAlpha(200)
        p.setPen(QPen(orange, 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(3, 3, WINDOW_WIDTH - 6, WINDOW_HEIGHT - 6)

        font = QFont(FONT_FAMILY, 9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(font)
        p.setPen(QPen(orange))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "DRAG")


# ---------------------------------------------------------------------------
# Top-level overlay window
# ---------------------------------------------------------------------------

class OverlayWindow(QWidget):

    _SETTINGS_ORG = "ED-Navigator"
    _SETTINGS_APP = "Overlay"

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._canvas = OverlayCanvas(self)
        self._canvas.setGeometry(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)

        # Default position: upper-centre of primary screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            self.move(
                sg.left() + (sg.width() - WINDOW_WIDTH) // 2,
                sg.top()  + 80,
            )

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_click_through()
        self._restore_position()

    def toggle_visibility(self) -> bool:
        if self.isVisible():
            self.hide()
            return False
        self.show()
        return True

    def enter_move_mode(self) -> None:
        if not self.isVisible():
            self.show()
        self._remove_click_through()
        self._canvas.set_move_mode(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def exit_move_mode(self) -> None:
        self._canvas.set_move_mode(False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._save_position()
        self._apply_click_through()

    def update_nav(self, nav: NavResult, has_target: bool) -> None:
        self._canvas.update_nav(nav, has_target)

    # ------------------------------------------------------------------
    # Win32
    # ------------------------------------------------------------------

    def _apply_click_through(self) -> None:
        try:
            hwnd     = int(self.winId())
            user32   = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        except Exception:
            pass

    def _remove_click_through(self) -> None:
        try:
            hwnd     = int(self.winId())
            user32   = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Position persistence
    # ------------------------------------------------------------------

    def _save_position(self) -> None:
        s = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
        s.setValue("overlay/x", self.x())
        s.setValue("overlay/y", self.y())

    def _restore_position(self) -> None:
        s = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
        x = s.value("overlay/x", None)
        y = s.value("overlay/y", None)
        if x is not None and y is not None:
            try:
                self.move(int(x), int(y))
            except (ValueError, TypeError):
                pass
