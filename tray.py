# tray.py
# System tray icon for ED Surface Navigator.
# Provides the primary UI entry point when the overlay is click-through.
#
# The icon is drawn programmatically: an orange ring with a crosshair
# on a 32×32 transparent pixmap — matches the overlay aesthetic.

from PyQt6.QtCore    import Qt, pyqtSignal
from PyQt6.QtGui     import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from constants import COLOR_ORANGE


class TrayIcon(QSystemTrayIcon):
    """System tray icon with context menu for overlay control."""

    toggle_overlay  = pyqtSignal()
    move_overlay    = pyqtSignal()
    open_settings   = pyqtSignal()
    toggle_settings = pyqtSignal()
    quit_app        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setIcon(self._make_icon())
        self.setToolTip("ED Surface Navigator")

        self._menu = QMenu()

        self._toggle_action   = self._menu.addAction("Hide Overlay")
        self._move_action     = self._menu.addAction("Move Overlay")
        self._menu.addSeparator()
        self._settings_action = self._menu.addAction("Open Settings")
        self._menu.addSeparator()
        self._quit_action     = self._menu.addAction("Quit")

        self._toggle_action.triggered.connect(self.toggle_overlay)
        self._move_action.triggered.connect(self.move_overlay)
        self._settings_action.triggered.connect(self.open_settings)
        self._quit_action.triggered.connect(self.quit_app)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # Public helpers called from main
    # ------------------------------------------------------------------

    def set_overlay_visible(self, visible: bool) -> None:
        """Update menu text to reflect current overlay visibility."""
        self._toggle_action.setText("Hide Overlay" if visible else "Show Overlay")

    def set_move_mode(self, active: bool) -> None:
        """Update move menu text to reflect current move mode state."""
        self._move_action.setText("Done Moving" if active else "Move Overlay")

    def show_update_notification(self, version: str) -> None:
        """Show a tray balloon informing the user that an update is available."""
        self.showMessage(
            "ED Navigator — Update Available",
            f"Version {version} is available. Click here to download.",
            QSystemTrayIcon.MessageIcon.Information,
            8000,   # visible for 8 seconds
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_settings.emit()

    # ------------------------------------------------------------------
    # Icon construction
    # ------------------------------------------------------------------

    @staticmethod
    def _make_icon() -> QIcon:
        """Draw an orange ring + crosshair on a 32×32 transparent pixmap."""
        px = QPixmap(32, 32)
        px.fill(QColor(0, 0, 0, 0))

        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        orange = QColor(COLOR_ORANGE)
        pen = QPen(orange, 2.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Outer ring
        p.drawEllipse(3, 3, 26, 26)

        # Crosshair (four arms with gap at centre)
        p.drawLine(16, 4,  16, 12)
        p.drawLine(16, 20, 16, 28)
        p.drawLine(4,  16, 12, 16)
        p.drawLine(20, 16, 28, 16)

        p.end()
        return QIcon(px)
