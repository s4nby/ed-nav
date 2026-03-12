# planet_preview.py
# Interactive 3D sphere preview for ED Navigator.
#
# Renders a bare-rock planet with a lat/lon grid and a coordinate marker
# using pure QPainter + orthographic projection.  Mouse-drag rotates the
# globe on both axes.

import math

from PyQt6.QtCore    import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui     import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

_GRID_STEP          = 30     # degrees between lat/lon grid lines
_STEPS              = 90     # segments per grid line (higher = smoother arcs)
_ANIM_INTERVAL_MS   = 16     # ~60 fps animation tick
_FADE_DURATION_MS   = 800    # fade-in from transparent to opaque
_AUTOROT_DEG_PER_MS = 1.5 / 1000  # 1.5°/s → one full rotation ≈ 4 min


class PlanetPreviewWidget(QWidget):
    """
    Interactive 3D sphere with lat/lon grid and a surface marker.

    Public API:
        set_target(lat, lon)        — update the coordinate marker (None clears it)
        reset_rotation(lat, lon)    — spin view to show that coordinate front/centre

    Signals:
        coord_picked(lat, lon)  — emitted when the user clicks a point on the surface
    """

    coord_picked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._yaw   =  30.0   # degrees — spin around vertical axis
        self._pitch =  20.0   # degrees — tilt up/down

        self._active    = False
        self._unknown   = False
        self._drag_pos  = None
        self._press_pos = None

        self._target_lat: float | None = None
        self._target_lon: float | None = None

        self._opacity: float = 1.0

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(_ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._tick_anim)

        self.setMinimumSize(210, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip("")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool, unknown: bool = False) -> None:
        """Switch between placeholder (False) and full-sphere (True) rendering."""
        self._active  = active
        self._unknown = unknown if active else False
        if active:
            self._opacity = 0.0
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
            self._opacity = 1.0
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if active else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def _tick_anim(self) -> None:
        if self._opacity < 1.0:
            self._opacity = min(1.0, self._opacity + _ANIM_INTERVAL_MS / _FADE_DURATION_MS)
        if self._drag_pos is None:
            self._yaw = (self._yaw + _AUTOROT_DEG_PER_MS * _ANIM_INTERVAL_MS) % 360.0
        self.update()

    def set_target(self, lat: float | None, lon: float | None) -> None:
        self._target_lat = lat
        self._target_lon = lon
        self.update()

    def reset_rotation(self, center_lat: float = 0.0, center_lon: float = 0.0) -> None:
        """Orient the sphere so the given coordinate faces the viewer."""
        self._yaw   = (-center_lon) % 360
        self._pitch = max(-60.0, min(60.0, center_lat * 0.6))
        self.update()

    # ------------------------------------------------------------------
    # Mouse interaction — drag to rotate, click to pick coordinate
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if not self._active:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self._drag_pos  = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        if not self._active:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._press_pos is not None:
                delta = event.pos() - self._press_pos
                if delta.manhattanLength() < 5:
                    result = self._inverse_project(event.pos().x(), event.pos().y())
                    if result is not None:
                        self.coord_picked.emit(*result)
            self._drag_pos  = None
            self._press_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseMoveEvent(self, event):
        if not self._active:
            return
        if self._drag_pos is not None:
            delta          = event.pos() - self._drag_pos
            self._drag_pos = event.pos()
            self._yaw   = (self._yaw + delta.x() * 0.5) % 360
            self._pitch = max(-85.0, min(85.0, self._pitch + delta.y() * 0.5))
            self.update()

    # ------------------------------------------------------------------
    # Inverse projection — screen coords → lat/lon
    # ------------------------------------------------------------------

    def _inverse_project(self, px: float, py: float) -> tuple[float, float] | None:
        w, h     = self.width(), self.height()
        label_h  = 28
        sphere_h = h - label_h
        cx, cy   = w / 2.0, sphere_h / 2.0
        R        = min(w, sphere_h) / 2.0 - 40.0

        x_ndc = (px - cx) / R
        y_ndc = (cy - py) / R
        r2 = x_ndc ** 2 + y_ndc ** 2
        if r2 > 1.0:
            return None

        z2 = math.sqrt(1.0 - r2)

        yr, pr       = math.radians(self._yaw), math.radians(self._pitch)
        cos_y, sin_y = math.cos(yr), math.sin(yr)
        cos_p, sin_p = math.cos(pr), math.sin(pr)

        x1 = x_ndc
        y1 =  y_ndc * cos_p + z2 * sin_p
        z1 = -y_ndc * sin_p + z2 * cos_p
        x0 =  x1 * cos_y - z1 * sin_y
        z0 =  x1 * sin_y + z1 * cos_y
        y0 =  y1

        lat = math.degrees(math.asin(max(-1.0, min(1.0, y0))))
        lon = math.degrees(math.atan2(x0, z0))
        return round(lat, 4), round(lon, 4)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h     = self.width(), self.height()
        label_h  = 28
        sphere_h = h - label_h
        cx, cy   = w / 2.0, sphere_h / 2.0
        R        = min(w, sphere_h) / 2.0 - 20.0

        if not self._active:
            _draw_placeholder(p, cx, cy, R)
            p.end()
            return

        p.setOpacity(self._opacity)

        yr, pr       = math.radians(self._yaw),   math.radians(self._pitch)
        cos_y, sin_y = math.cos(yr), math.sin(yr)
        cos_p, sin_p = math.cos(pr), math.sin(pr)

        def project(lat_d: float, lon_d: float) -> tuple[float, float, float]:
            """lat/lon → (screen_x, screen_y, z).  z > 0 = visible."""
            la, lo = math.radians(lat_d), math.radians(lon_d)
            x0 = math.cos(la) * math.sin(lo)
            y0 = math.sin(la)
            z0 = math.cos(la) * math.cos(lo)
            
            # Yaw around Y-axis
            x1 =  x0 * cos_y + z0 * sin_y
            z1 = -x0 * sin_y + z0 * cos_y
            y1 =  y0
            # Pitch around X-axis
            y2 =  y1 * cos_p - z1 * sin_p
            z2 =  y1 * sin_p + z1 * cos_p
            return cx + x1 * R, cy - y2 * R, z2

        # ---- Sphere base — warm lit face, dark limb ----
        grad = QRadialGradient(cx - R * 0.28, cy - R * 0.32, R * 1.5)
        grad.setColorAt(0.00, QColor(90,  55,  14))
        grad.setColorAt(0.45, QColor(32,  18,   5))
        grad.setColorAt(1.00, QColor( 4,   2,   0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), R, R)

        # ---- Clip all subsequent drawing to the sphere disc ----
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), R, R)
        p.setClipPath(clip)

        # ---- Lat/lon grid ----
        for lat in range(-90 + _GRID_STEP, 90, _GRID_STEP):       # parallels
            pts = [project(lat, -180 + 360 * i / _STEPS) for i in range(_STEPS + 1)]
            _draw_arc(p, pts)

        for lon in range(-180, 180, _GRID_STEP):                  # meridians
            pts = [project(-90 + 180 * i / _STEPS, lon) for i in range(_STEPS + 1)]
            _draw_arc(p, pts)

        # Equator / prime meridian — slightly brighter for orientation
        eq_pts = [project(0, -180 + 360 * i / _STEPS) for i in range(_STEPS + 1)]
        _draw_arc(p, eq_pts, bright=True)
        pm_pts = [project(-90 + 180 * i / _STEPS, 0) for i in range(_STEPS + 1)]
        _draw_arc(p, pm_pts, bright=True)

        # ---- Surface marker (front hemisphere) or ghost (back) ----
        target_behind = False
        if self._target_lat is not None and self._target_lon is not None:
            sx, sy, tz = project(self._target_lat, self._target_lon)
            if tz > 0.0:
                _draw_marker(p, sx, sy, R)
            else:
                target_behind = True
                _draw_occluded_marker(p, sx, sy, R)

        # ---- Remove clip, draw atmospheric limb ring ----
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 130, 0, 90), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R, R)

        # ---- HUD hint ----
        p.setFont(QFont("Agency FB", 8))
        if target_behind:
            p.setPen(QColor(220, 110, 0, 200))
            _draw_hud(p, w, h, sphere_h, "target on far side \u2014 drag to rotate")
        else:
            p.setPen(QColor(100, 50, 0, 130))
            _draw_hud(p, w, h, sphere_h, "drag to rotate \u2022 click to set coordinates")

        p.end()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _draw_arc(
    painter: QPainter,
    pts: list[tuple[float, float, float]],
    bright: bool = False,
) -> None:
    """Draw a projected grid arc; segment colour follows depth (z)."""
    for i in range(len(pts) - 1):
        sx0, sy0, z0 = pts[i]
        sx1, sy1, z1 = pts[i + 1]
        z_avg = (z0 + z1) * 0.5
        if z_avg >= 0:
            base  = 130 if bright else 90
            alpha = int(min(base, 30 + z_avg * (base - 30) * 2.5))
        else:
            alpha = int(max(0, 18 + z_avg * 25))
        w = 1.0 if bright else 0.7
        painter.setPen(QPen(QColor(200, 100, 0, alpha), w))
        painter.drawLine(QPointF(sx0, sy0), QPointF(sx1, sy1))


def _draw_marker(painter: QPainter, sx: float, sy: float, R: float) -> None:
    """ED-style crosshair marker — four gapped arms and a central dot."""
    arm = max(7.0, R * 0.09)
    gap = arm * 0.30
    dot = arm * 0.20

    painter.setPen(QPen(QColor(255, 165, 0), 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(sx - arm, sy), QPointF(sx - gap, sy))
    painter.drawLine(QPointF(sx + gap, sy), QPointF(sx + arm, sy))
    painter.drawLine(QPointF(sx, sy - arm), QPointF(sx, sy - gap))
    painter.drawLine(QPointF(sx, sy + gap), QPointF(sx, sy + arm))

    painter.setBrush(QBrush(QColor(255, 165, 0)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(sx, sy), dot, dot)


def _draw_occluded_marker(painter: QPainter, sx: float, sy: float, R: float) -> None:
    """Ghost crosshair for a target on the far side of the planet."""
    arm  = max(6.0, R * 0.085)
    gap  = arm * 0.30
    ring = arm * 0.38

    pen = QPen(QColor(255, 140, 0, 50), 1.1, Qt.PenStyle.DashLine)
    pen.setDashPattern([2.5, 2.5])
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(sx - arm, sy), QPointF(sx - gap, sy))
    painter.drawLine(QPointF(sx + gap, sy), QPointF(sx + arm, sy))
    painter.drawLine(QPointF(sx, sy - arm), QPointF(sx, sy - gap))
    painter.drawLine(QPointF(sx, sy + gap), QPointF(sx, sy + arm))

    painter.setPen(QPen(QColor(255, 140, 0, 45), 1.0, Qt.PenStyle.DashLine))
    painter.drawEllipse(QPointF(sx, sy), ring, ring)


def _draw_placeholder(painter: QPainter, cx: float, cy: float, R: float) -> None:
    """Minimal placeholder drawn before any planet is selected."""
    pr = R * 0.60
    painter.setPen(QPen(QColor(120, 60, 0, 110), 2.0, Qt.PenStyle.DashLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), pr, pr)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(160, 80, 0, 220)))
    painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)


def _draw_hud(painter: QPainter, w: int, h: int, sphere_h: float, text: str) -> None:
    painter.drawText(
        QRectF(0, sphere_h, w, h - sphere_h),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        text,
    )
