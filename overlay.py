# overlay.py
# Minimal compass-needle overlay.
# Draws only when actively tracking: a slim needle pointing at the target
# (relative to player heading) and a distance readout below it.
# Invisible (fully transparent) when there is no target or no GPS signal.
# Always click-through (WS_EX_TRANSPARENT) except when in move mode.

import ctypes
import math
from typing import Optional

from PyQt6.QtCore    import Qt, QTimer, QPoint, QPointF, QRectF
from PyQt6.QtCore    import QSettings
from PyQt6.QtGui     import (QColor, QPainter, QPen, QBrush, QFont,
                              QPainterPath)
from PyQt6.QtWidgets import QWidget, QApplication

from constants import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    NEEDLE_LENGTH, NEEDLE_TAIL, NEEDLE_HALF_W,
    NEEDLE_ALPHA, TEXT_ALPHA,
    COLOR_ORANGE, COLOR_ERROR,
    FONT_FAMILY, FONT_SIZE_DIST,
    RENDER_INTERVAL_MS,
    MAX_ROTATE_PER_FRAME,
    PULSE_SPEED,
    ARRIVAL_DISTANCE_M,
    PROXIMITY_DISTANCE_M, PROXIMITY_EXIT_M,
    ORBITAL_ZONE_NEEDLE_M,
    DEFAULT_PLANET_RADIUS_M,
)

from tracker import NavResult, shortest_arc

# Needle color thresholds (bearing error in degrees)
_BEARING_BLUE_THRESH   = 10.0   # ≤ 10° off → blue (on track)
_BEARING_ORANGE_THRESH = 45.0   # ≤ 45° off → orange (slightly off)
# > 45° → red (way off)
_COLOR_BLUE = "#4499FF"

_SPEED_SCALE_MAX = 80.0    # m/s at which the tail reaches maximum elongation
_NEEDLE_SCALE    = 1.15    # needle geometry multiplier (slightly larger than base)

# Heading deadzone — forbidden relative-bearing ranges (0–360° representation)
# Global:          -60° to -90°  →  270° to 300°
# Caspian Explorer: -75° to -90° →  270° to 285°
_DZ_GLOBAL_LOW    = 270.0
_DZ_GLOBAL_HIGH   = 300.0
_DZ_CASPIAN_LOW   = 270.0
_DZ_CASPIAN_HIGH  = 285.0
_DZ_CASPIAN_NAME  = "caspian explorer"   # player-given ship name (case-insensitive)
_DZ_HYSTERESIS    = 5.0    # degrees — must clear boundary by this much to exit deadzone


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
        self._speed_scale:   float = 1.0   # tail length multiplier from speed
        self._pulse_phase:   float = 0.0
        self._idle_phase:    float = 0.0
        self._last_target_epoch: int = 0
        # True from the moment a new target is set until the overlay receives a
        # valid bearing for it.  Forces "APPROACH THE PLANET" in the interim so
        # the previous planet's stale needle is never shown.
        self._pending_approach: bool = False

        # GPS dropout grace period — absorbs brief has_lat_long flickers
        self._gps_lost_frames: int = 0
        # Last known good nav values — used to keep drawing during grace period
        self._last_valid_distance_m:  Optional[float] = None
        self._last_valid_rel_bearing: Optional[float] = None

        self._nav:        NavResult = NavResult()
        self._has_target: bool      = False

        # Proximity state (< PROXIMITY_DISTANCE_M) — hysteresis prevents flicker
        self._proximity_active: bool = False

        # Heading deadzone — suppresses needle when target is in forbidden arc
        self._in_deadzone:   bool = False
        self._vehicle_name:  str  = ""

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
        self._nav          = nav
        self._has_target   = has_target
        self._vehicle_name = (nav.vehicle_name or "").strip().lower()

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

    def _needle_cx(self) -> float:
        """X pivot of the needle — horizontally centred."""
        return float(self._cx())

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

        # ── Proximity state (hysteresis prevents flicker near 15 m) ───
        # Based on raw distance — independent of nav.arrived (200 m threshold).
        dist = nav.distance_m
        if nav.has_lat_long and dist is not None:
            if dist < PROXIMITY_DISTANCE_M:
                self._proximity_active = True
            elif self._proximity_active and dist > PROXIMITY_EXIT_M:
                self._proximity_active = False
        else:
            self._proximity_active = False

        # ── Heading deadzone ──────────────────────────────────────────
        # Active whenever a bearing exists and the player is not already at the target.
        if nav.relative_bearing is not None and not self._proximity_active:
            rb = nav.relative_bearing
            if self._vehicle_name == _DZ_CASPIAN_NAME:
                dz_low, dz_high = _DZ_CASPIAN_LOW, _DZ_CASPIAN_HIGH
            else:
                dz_low, dz_high = _DZ_GLOBAL_LOW, _DZ_GLOBAL_HIGH
            in_zone = dz_low <= rb <= dz_high
            if in_zone:
                self._in_deadzone = True
            elif self._in_deadzone:
                # Exit only when clearly outside the forbidden arc
                if rb < dz_low - _DZ_HYSTERESIS or rb > dz_high + _DZ_HYSTERESIS:
                    self._in_deadzone = False
        else:
            self._in_deadzone = False

        # ── New-target detection ───────────────────────────────────────
        # Runs unconditionally so the flag is set even when the bearing block
        # below is skipped (body_mismatch, no GPS, etc.).
        if nav.target_epoch != self._last_target_epoch:
            self._pending_approach       = True
            # Wipe stale grace-period values so the old needle cannot bleed
            # through during GPS dropout on the new body.
            self._last_valid_distance_m  = None
            self._last_valid_rel_bearing = None

        # ── Bearing tracking (clamped rate, snap on new target) ───────
        # Skip when the player's GPS fix is on a different body than the target —
        # the bearing would be computed across mismatched coordinate spaces.
        if (nav.relative_bearing is not None
                and not self._proximity_active
                and not self._in_deadzone
                and not nav.body_mismatch):
            if nav.target_epoch != self._last_target_epoch:
                # New target set — snap immediately instead of animating
                self._display_angle      = nav.relative_bearing
                self._last_target_epoch  = nav.target_epoch
            else:
                err  = shortest_arc(self._display_angle, nav.relative_bearing)
                step = max(-MAX_ROTATE_PER_FRAME, min(MAX_ROTATE_PER_FRAME, err))
                self._display_angle = (self._display_angle + step) % 360.0

        # ── Clear pending-approach once a valid bearing is confirmed ───
        if nav.has_lat_long and not nav.body_mismatch and nav.relative_bearing is not None:
            self._pending_approach = False

        # Save last good nav values for GPS dropout grace rendering
        if nav.has_lat_long and not nav.body_mismatch:
            if nav.distance_m is not None:
                self._last_valid_distance_m = nav.distance_m
            if nav.relative_bearing is not None:
                self._last_valid_rel_bearing = nav.relative_bearing

        # ── Speed scale — tail elongates with ship speed ───────────────
        spd = nav.speed_ms or 0.0
        self._speed_scale = 1.0 + min(1.0, spd / _SPEED_SCALE_MAX) * 0.55

        # ── Misc ──────────────────────────────────────────────────────
        if self._proximity_active or nav.arrived:
            self._pulse_phase += PULSE_SPEED
        if not self._has_target and not self._proximity_active:
            self._idle_phase += 0.2094  # 2π / (1.0 s × 30 FPS) → 1 s left-to-right sweep
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

        # Idle dots: show as long as no target is set — GPS not required.
        # This ensures the user always sees the app is active.
        if not self._has_target and not nav.arrived:
            self._draw_idle(p)
            p.end()
            return

        # ── New target set — show approach text immediately, bypass GPS grace ──
        if self._pending_approach:
            self._gps_lost_frames = 0
            self._draw_approach_planet(p)
            p.end()
            return

        if not nav.has_lat_long:
            self._gps_lost_frames += 1
            # Shorten grace period at close range: stale data is more noticeable
            # when distance changes rapidly (e.g. SRV at ~28 m/s moves 5 m in 166 ms).
            close_range = (self._last_valid_distance_m or float("inf")) < ARRIVAL_DISTANCE_M
            grace_limit = 5 if close_range else 30
            if self._gps_lost_frames < grace_limit:
                # Keep drawing the last known needle state so brief GPS flickers
                # are invisible to the user rather than showing blank.
                if self._has_target and self._last_valid_distance_m is not None:
                    needle_color = self._bearing_color(self._last_valid_rel_bearing)
                    self._draw_needle(p, self._display_angle, needle_color)
                    self._draw_distance(p, self._last_valid_distance_m)
                p.end()
                return
            self._draw_approach_planet(p)
            p.end()
            return
        else:
            self._gps_lost_frames = 0

        # ── Body mismatch — player's GPS is on a different body than the target ─
        if nav.body_mismatch:
            self._draw_wrong_body(p)
            p.end()
            return

        # ── Altitude-based activation gate ────────────────────────────────
        # Orbital zone boundary ≈ 2 × planet_radius altitude above the surface
        # (orbit is at 3× radius from the planet's centre).
        # Beyond 4,000 km of orbital zone → approach label only.
        # Within 4,000 km → full needle + distance.
        if nav.altitude_m is not None:
            planet_radius = nav.planet_radius_m or DEFAULT_PLANET_RADIUS_M
            orbital_zone_alt = 2.0 * planet_radius
            if nav.altitude_m > orbital_zone_alt + ORBITAL_ZONE_NEEDLE_M:
                self._draw_approach_planet(p)
                p.end()
                return

        if self._proximity_active:
            # Within 15 m: glowing circle only — no needle, no distance label
            self._draw_arrived(p, None)
        elif nav.arrived:
            # Within 200 m: glowing circle + distance label, no needle
            self._draw_arrived(p, nav.distance_m)
        elif self._in_deadzone:
            # Target bearing is in forbidden arc — show distance only, no needle
            self._draw_distance(p, nav.distance_m)
        else:
            needle_color = self._bearing_color(nav.relative_bearing)
            self._draw_needle(p, self._display_angle, needle_color)
            self._draw_distance(p, nav.distance_m)

        p.end()

    # ------------------------------------------------------------------
    # Bearing → needle colour
    # ------------------------------------------------------------------

    def _bearing_color(self, rel_bearing: Optional[float]) -> QColor:
        """Return blue / orange / red based on how far off the heading is."""
        if rel_bearing is None:
            return QColor(COLOR_ORANGE)
        # shortest error from dead-ahead (0°)
        error = min(rel_bearing, 360.0 - rel_bearing)
        if error <= _BEARING_BLUE_THRESH:
            return QColor(_COLOR_BLUE)
        elif error <= _BEARING_ORANGE_THRESH:
            return QColor(COLOR_ORANGE)
        else:
            return QColor(COLOR_ERROR)

    # ------------------------------------------------------------------
    # Drawing helpers — all dimensions scaled by self._scale()
    # ------------------------------------------------------------------

    def _draw_needle(self, p: QPainter, angle_deg: float, color: QColor) -> None:
        """
        2D flat arrow pointing toward the target bearing.
        0° = tip up (target straight ahead); degrees increase clockwise.
        Arrow: filled triangle head + dimmer rectangular shaft + pivot dot.
        """
        s   = self._scale()
        ns  = s * _NEEDLE_SCALE   # needle-specific scale (slightly larger)
        cx  = self._needle_cx()
        cy  = float(self._cy())

        fwd = NEEDLE_LENGTH * ns
        aft = NEEDLE_TAIL   * ns * self._speed_scale
        hw  = NEEDLE_HALF_W * ns  # arrowhead half-width
        sw  = hw * 0.38           # shaft half-width

        # Clockwise rotation from "up" in screen space.
        # Local +y axis = forward (up on screen when angle=0).
        rad   = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        def rot(lx: float, ly: float):
            rx =  lx * cos_a + ly * sin_a
            ry = -lx * sin_a + ly * cos_a
            return cx + rx, cy - ry   # flip ry: screen y is down

        tip = rot(0,    fwd)
        bl  = rot(-hw,  0)
        br  = rot( hw,  0)
        sl  = rot(-sw,  0)
        sr  = rot( sw,  0)
        tl  = rot(-sw, -aft)
        tr  = rot( sw, -aft)

        p.setPen(Qt.PenStyle.NoPen)

        # Shaft — dimmer fill
        shaft = QPainterPath()
        shaft.moveTo(*sl)
        shaft.lineTo(*tl)
        shaft.lineTo(*tr)
        shaft.lineTo(*sr)
        shaft.closeSubpath()
        shaft_color = QColor(color)
        shaft_color.setAlpha(int(NEEDLE_ALPHA * 0.40))
        p.setBrush(QBrush(shaft_color))
        p.drawPath(shaft)

        # Arrowhead triangle
        head = QPainterPath()
        head.moveTo(*tip)
        head.lineTo(*bl)
        head.lineTo(*br)
        head.closeSubpath()
        head_color = QColor(color)
        head_color.setAlpha(NEEDLE_ALPHA)
        p.setBrush(QBrush(head_color))
        p.drawPath(head)

        # Pivot dot
        dot_r = max(1.5, 2.0 * ns)
        dot_color = QColor(color)
        dot_color.setAlpha(220)
        p.setBrush(QBrush(dot_color))
        p.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

    def _draw_distance(self, p: QPainter, distance_m: Optional[float]) -> None:
        if distance_m is None:
            return
        text = f"{distance_m / 1000.0:.1f} km" if distance_m >= 1000.0 else f"{int(distance_m)} m"
        s     = self._scale()
        font  = QFont(FONT_FAMILY, max(6, round(FONT_SIZE_DIST * s)))
        rect  = QRectF(0, self.height() - 16 * s, self.width(), 18 * s)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter

        p.setFont(font)
        # Drop shadow
        shadow = QColor(0, 0, 0, 100)
        p.setPen(QPen(shadow))
        p.drawText(QRectF(rect.x() + 1, rect.y() + 1, rect.width(), rect.height()),
                   flags, text)
        # Main text
        color = QColor(COLOR_ORANGE)
        color.setAlpha(TEXT_ALPHA)
        p.setPen(QPen(color))
        p.drawText(rect, flags, text)

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
        s       = self._scale()
        cx, cy  = self._cx(), self._cy()
        r       = max(2, round(3 * s))
        spacing = round(11 * s)

        p.setPen(Qt.PenStyle.NoPen)

        # Wave travels left→right: dot i peaks when phase = i × 2π/3.
        # Alpha sweeps from dim (50) to full (TEXT_ALPHA) as the wave passes.
        for i in range(3):
            wave  = 0.5 * (1.0 + math.cos(self._idle_phase - i * (2.0 * math.pi / 3.0)))
            alpha = int(50 + (TEXT_ALPHA - 50) * wave)
            color = QColor(COLOR_ORANGE)
            color.setAlpha(alpha)
            p.setBrush(QBrush(color))
            p.drawEllipse(QPoint(cx + (i - 1) * spacing, cy), r, r)

    def _draw_approach_planet(self, p: QPainter) -> None:
        """Shown when a target is set but the player has no GPS (not near/on planet)."""
        self._draw_text_overlay(p, "APPROACH\nTHE PLANET")

    def _draw_wrong_body(self, p: QPainter) -> None:
        """Shown when the player's GPS fix is on a different body than the target."""
        self._draw_text_overlay(p, "WRONG\nBODY")

    def _draw_text_overlay(self, p: QPainter, msg: str) -> None:
        s     = self._scale()
        font  = QFont(FONT_FAMILY, max(7, round(10 * s)))
        rect  = QRectF(4, 0, self.width() - 8, self.height())
        flags = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                 | Qt.TextFlag.TextWordWrap)

        p.setFont(font)
        shadow = QColor(0, 0, 0, 100)
        p.setPen(QPen(shadow))
        p.drawText(QRectF(rect.x() + 1, rect.y() + 1, rect.width(), rect.height()),
                   flags, msg)
        color = QColor(COLOR_ORANGE)
        color.setAlpha(TEXT_ALPHA)
        p.setPen(QPen(color))
        p.drawText(rect, flags, msg)

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

        # Default position: top-centre of primary screen
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


# ---------------------------------------------------------------------------
# Inclination overlay — independent window for the chevron pitch-correction cue
# ---------------------------------------------------------------------------

_INCL_W = 76   # px — fixed window width (chevrons + degree text)
_INCL_H = 58   # px — fixed window height


class InclinationCanvas(QWidget):
    """
    Draws the triple-chevron pitch-correction array.
    Runs its own 30 FPS timer and flight-angle tracker.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._nav:          NavResult      = NavResult()
        self._vehicle_name: str            = ""
        self._flight_angle: Optional[float] = None
        self._prev_alt:     Optional[float] = None
        self._prev_dist:    Optional[float] = None
        self._chevron_phase: float          = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(RENDER_INTERVAL_MS)

    def update_nav(self, nav: NavResult, _has_target: bool) -> None:
        self._nav          = nav
        self._vehicle_name = (nav.vehicle_name or "").strip().lower()

        # Compute flight-path angle from sequential altitude/distance deltas.
        # Called at the nav-timer rate (~100 ms); only meaningful when position changes.
        alt  = nav.altitude_m
        dist = nav.distance_m
        if alt is not None and dist is not None:
            if self._prev_alt is not None and self._prev_dist is not None:
                d_alt  = alt  - self._prev_alt
                d_dist = self._prev_dist - dist
                if abs(d_alt) > 0.5 or abs(d_dist) > 0.5:
                    raw = math.degrees(math.atan2(-d_alt, max(d_dist, 0.1)))
                    self._flight_angle = (
                        0.5 * self._flight_angle + 0.5 * raw
                        if self._flight_angle is not None else raw
                    )
            self._prev_alt  = alt
            self._prev_dist = dist
        else:
            self._flight_angle = None
            self._prev_alt     = None
            self._prev_dist    = None

    def _tick(self) -> None:
        self._chevron_phase = (self._chevron_phase + 0.04) % 1.0
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        nav = self._nav
        if not nav.in_orbital_flight:
            p.end()
            return

        angle = nav.target_descent_angle_deg
        if angle is None or nav.altitude_m is None or nav.altitude_m < 10.0:
            p.end()
            return

        dz_limit   = 75.0 if self._vehicle_name == _DZ_CASPIAN_NAME else 60.0
        in_unsafe  = angle >= dz_limit
        raw_angle  = angle
        angle      = min(angle, dz_limit)

        # Shared geometry (needed for both unsafe and normal paths)
        aw      = 8     # chevron half-width (px)
        ch      = 8     # chevron arm height (px)
        gap     = 6     # gap between chevrons (px)
        pad     = 5     # left-edge padding
        total_h = 3 * ch + 2 * gap
        ax      = float(pad + aw)
        top_y   = (self.height() - total_h) / 2.0

        deg_text   = f"{raw_angle:.0f}\u00b0"
        font       = QFont(FONT_FAMILY, 11)
        text_x     = ax + aw + 6
        text_rect  = QRectF(text_x, top_y, self.width() - text_x - 2, total_h)
        text_flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if in_unsafe:
            # Angle is too steep — suppress chevrons, keep degree value in red
            p.setFont(font)
            shadow = QColor(0, 0, 0, 90)
            p.setPen(QPen(shadow))
            p.drawText(QRectF(text_rect.x() + 1, text_rect.y() + 1,
                              text_rect.width(), text_rect.height()), text_flags, deg_text)
            col = QColor(COLOR_ERROR)
            col.setAlpha(TEXT_ALPHA)
            p.setPen(QPen(col))
            p.drawText(text_rect, text_flags, deg_text)
            p.end()
            return

        # No flight-angle data yet — nothing meaningful to display
        if self._flight_angle is None:
            p.end()
            return

        need_up   = self._flight_angle > min( 89.0, angle + 2.0)
        need_down = self._flight_angle < max(-89.0, angle - 2.0)
        on_target = not need_up and not need_down

        # Colour: cyan/blue when aligned, amber/orange when correction required
        base_hex = _COLOR_BLUE if on_target else COLOR_ORANGE

        pw = 2.5
        p.setBrush(Qt.BrushStyle.NoBrush)

        for i in range(3):
            if on_target:
                wave = 0.65   # static equal glow — no directional chase
            else:
                offset = ((2 - i) if need_up else i) / 3.0
                wave   = 0.5 * (1.0 + math.sin(2.0 * math.pi * (self._chevron_phase - offset)))

            alpha = int(30 + (TEXT_ALPHA - 30) * wave)
            cy_i  = top_y + i * (ch + gap)

            for dx, dy, a in ((1, 1, int(70 * wave)), (0, 0, alpha)):
                col = QColor(0, 0, 0, a) if dx else QColor(base_hex)
                if not dx:
                    col.setAlpha(a)
                p.setPen(QPen(col, pw))
                path = QPainterPath()
                if need_up or on_target:   # up-pointing chevrons: pull up / aligned
                    path.moveTo(ax - aw + dx, cy_i + ch + dy)
                    path.lineTo(ax      + dx, cy_i      + dy)
                    path.lineTo(ax + aw + dx, cy_i + ch + dy)
                else:
                    path.moveTo(ax - aw + dx, cy_i      + dy)
                    path.lineTo(ax      + dx, cy_i + ch + dy)
                    path.lineTo(ax + aw + dx, cy_i      + dy)
                p.drawPath(path)

        # Degree value — immediately right of the chevron column
        p.setFont(font)
        shadow = QColor(0, 0, 0, 90)
        p.setPen(QPen(shadow))
        p.drawText(QRectF(text_rect.x() + 1, text_rect.y() + 1,
                          text_rect.width(), text_rect.height()), text_flags, deg_text)
        col = QColor(base_hex)
        col.setAlpha(TEXT_ALPHA)
        p.setPen(QPen(col))
        p.drawText(text_rect, text_flags, deg_text)

        p.end()


class InclinationOverlay(QWidget):
    """
    Independent always-on-top click-through window for the chevron pitch cue.
    Positioned on the right side to mirror the ED altitude ladder.
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(_INCL_W, _INCL_H)

        self._canvas = InclinationCanvas(self)
        self._canvas.setGeometry(0, 0, _INCL_W, _INCL_H)

        # Default position: right side, ~42 % down — ED altitude ladder area
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            self.move(
                sg.left() + (sg.width() // 2) - _INCL_W - 160,
                sg.top()  + int(sg.height() * 0.42),
            )

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_click_through()

    def update_nav(self, nav: NavResult, has_target: bool) -> None:
        self._canvas.update_nav(nav, has_target)

    def _apply_click_through(self) -> None:
        try:
            hwnd     = int(self.winId())
            user32   = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        except Exception:
            pass
