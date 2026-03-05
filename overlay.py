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

# Aspect ratio
_ASPECT = WINDOW_HEIGHT / WINDOW_WIDTH   # ~0.727

# Resize grip size (px) — bottom-right corner hit area
_RESIZE_GRIP = 14


class OverlayCanvas(QWidget):
    """Animated needle canvas."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._display_angle: float = 0.0
        self._pulse_phase:   float = 0.0
        self._idle_phase:    float = 0.0

        self._nav:        NavResult = NavResult()
        self._has_target: bool      = False

        self._move_mode:    bool             = False
        self._drag_start:   Optional[QPoint] = None
        self._resize_start: Optional[QPoint] = None
        self._initial_size: tuple[int, int]  = (0, 0)

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
        self._move_mode    = active
        self._drag_start   = None
        self._resize_start = None
        self.update()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _scale(self) -> float:
        """Scale factor relative to default overlay size."""
        return self.width() / WINDOW_WIDTH

    def _cx(self) -> int:
        return self.width() // 2

    def _cy(self) -> int:
        return self.height() // 2 - int(6 * self._scale())

    def _in_resize_grip(self, pos) -> bool:
        return (pos.x() >= self.width()  - _RESIZE_GRIP
                and pos.y() >= self.height() - _RESIZE_GRIP)

    # ------------------------------------------------------------------
    # Mouse (move mode only)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._move_mode and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._in_resize_grip(pos):
                self._resize_start = event.globalPosition().toPoint()
                self._initial_size = (self.window().width(), self.window().height())
                return
            if 3 <= pos.x() <= self.width() - 3 and 3 <= pos.y() <= self.height() - 3:
                self._drag_start = event.globalPosition().toPoint()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._move_mode:
            pos = event.position()

            # Cursor feedback when hovering (no button held)
            if not (self._drag_start or self._resize_start):
                if self._in_resize_grip(pos):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeAllCursor)

            # Resize — lock to aspect ratio
            if self._resize_start is not None:
                delta = event.globalPosition().toPoint() - self._resize_start
                new_w = max(WINDOW_WIDTH, self._initial_size[0] + delta.x())
                new_h = round(new_w * _ASPECT)
                self.window().resize(new_w, new_h)
                return

            # Drag
            if self._drag_start is not None:
                delta = event.globalPosition().toPoint() - self._drag_start
                win   = self.window()
                win.move(win.pos() + delta)
                self._drag_start = event.globalPosition().toPoint()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._move_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start   = None
            self._resize_start = None
            return
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
        if nav.has_lat_long and not self._has_target and not nav.arrived:
            self._idle_phase += 0.18
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self._move_mode:
            self._draw_move_mode(p)
            p.end()
            return

        nav = self._nav
        if not nav.has_lat_long:
            p.end()
            return

        if nav.arrived:
            self._draw_arrived(p, nav.distance_m)
        elif not self._has_target:
            self._draw_idle(p)
        else:
            self._draw_needle(p, self._display_angle)
            self._draw_distance(p, nav.distance_m)

        p.end()

    # ------------------------------------------------------------------
    # Drawing helpers — all dimensions scaled by self._scale()
    # ------------------------------------------------------------------

    def _draw_needle(self, p: QPainter, angle_deg: float) -> None:
        s   = self._scale()
        rad = math.radians(angle_deg)
        fx  =  math.sin(rad)
        fy  = -math.cos(rad)
        px  =  math.cos(rad)
        py  =  math.sin(rad)

        cx, cy = self._cx(), self._cy()
        nl, nt, hw = NEEDLE_LENGTH * s, NEEDLE_TAIL * s, NEEDLE_HALF_W * s

        # Forward triangle
        tip = (cx + nl * fx,  cy + nl * fy)
        bl  = (cx + hw * px,  cy + hw * py)
        br  = (cx - hw * px,  cy - hw * py)

        fwd_color = QColor(COLOR_ORANGE)
        fwd_color.setAlpha(NEEDLE_ALPHA)
        path = QPainterPath()
        path.moveTo(*tip); path.lineTo(*bl); path.lineTo(*br)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fwd_color))
        p.drawPath(path)

        # Tail triangle
        tail = (cx - nt * fx,      cy - nt * fy)
        tw   = hw * 0.55
        tl   = (cx + tw * px,  cy + tw * py)
        tr   = (cx - tw * px,  cy - tw * py)

        tail_color = QColor(COLOR_ORANGE)
        tail_color.setAlpha(NEEDLE_TAIL_ALPHA)
        path2 = QPainterPath()
        path2.moveTo(*tail); path2.lineTo(*tl); path2.lineTo(*tr)
        path2.closeSubpath()
        p.setBrush(QBrush(tail_color))
        p.drawPath(path2)

        # Pivot dot
        dot_color = QColor(COLOR_ORANGE)
        dot_color.setAlpha(180)
        p.setBrush(QBrush(dot_color))
        r = max(1, round(2 * s))
        p.drawEllipse(QPoint(cx, cy), r, r)

    def _draw_distance(self, p: QPainter, distance_m: Optional[float]) -> None:
        if distance_m is None:
            return
        text = f"{distance_m / 1000.0:.1f} km" if distance_m >= 1000.0 else f"{int(distance_m)} m"
        s    = self._scale()
        color = QColor(COLOR_ORANGE)
        color.setAlpha(TEXT_ALPHA)
        p.setPen(QPen(color))
        p.setFont(QFont(FONT_FAMILY, max(6, round(FONT_SIZE_DIST * s))))
        p.drawText(
            QRectF(0, self.height() - 20 * s, self.width(), 18 * s),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _draw_arrived(self, p: QPainter, distance_m: Optional[float]) -> None:
        s      = self._scale()
        pulse  = 0.55 + 0.45 * abs(math.sin(self._pulse_phase))
        cx, cy = self._cx(), self._cy()

        color = QColor(COLOR_ORANGE)
        color.setAlpha(int(240 * pulse))
        p.setPen(QPen(color, 1.5 * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = int((6 + 4 * pulse) * s)
        p.drawEllipse(QPoint(cx, cy), r, r)

        dot = QColor(COLOR_ORANGE)
        dot.setAlpha(int(200 * pulse))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot))
        rd = max(1, round(3 * s))
        p.drawEllipse(QPoint(cx, cy), rd, rd)

        self._draw_distance(p, distance_m)

    def _draw_idle(self, p: QPainter) -> None:
        s         = self._scale()
        cx, cy    = self._cx(), self._cy()
        r         = max(2, round(3 * s))
        spacing   = round(11 * s)
        amplitude = 4 * s

        color = QColor(COLOR_ORANGE)
        color.setAlpha(TEXT_ALPHA)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))

        for i in range(3):
            phase = self._idle_phase + i * (2 * math.pi / 3)
            x = cx + (i - 1) * spacing
            y = cy - round(amplitude * math.sin(phase))
            p.drawEllipse(QPoint(x, y), r, r)

    def _draw_move_mode(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        s    = self._scale()

        # Near-zero alpha fill so Win32 hit-testing works on transparent pixels
        p.fillRect(self.rect(), QColor(0, 0, 0, 8))

        orange = QColor(COLOR_ORANGE)
        orange.setAlpha(200)
        p.setPen(QPen(orange, 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(3, 3, w - 6, h - 6)

        font = QFont(FONT_FAMILY, max(6, round(9 * s)))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(font)
        p.setPen(QPen(orange))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "DRAG")

        # Resize grip — diagonal lines at bottom-right corner
        grip = QColor(COLOR_ORANGE)
        grip.setAlpha(180)
        p.setPen(QPen(grip, 1.5))
        for i in range(3):
            offset = 4 + i * 4
            p.drawLine(w - 4, h - 4 - offset, w - 4 - offset, h - 4)


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
        self.setMinimumSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._canvas.setGeometry(0, 0, self.width(), self.height())

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_click_through()

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

    def exit_move_mode(self) -> None:
        self._canvas.set_move_mode(False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
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
    # Position persistence (kept for future use)
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
