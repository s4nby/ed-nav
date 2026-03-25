# hotkey.py
# Registers a system-wide hotkey (Ctrl+Shift+N) using the Win32 API.
# Delivers an `activated` signal when the hotkey is pressed.
#
# Uses a hidden QWidget as the message-only window that owns the HWND
# needed by RegisterHotKey.  The HWND is created lazily via QTimer so
# it is guaranteed to exist before registration.

import ctypes
import ctypes.wintypes

from PySide6.QtCore    import QTimer, Signal
from PySide6.QtWidgets import QWidget

from constants import HOTKEY_ID, HOTKEY_MODIFIERS, HOTKEY_VK, WM_HOTKEY


class GlobalHotkey(QWidget):
    """Hidden widget that owns a Win32 HWND for hotkey message delivery."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep the widget invisible and zero-sized so it doesn't appear
        self.setFixedSize(0, 0)
        # Defer registration until after the event loop starts and the
        # native window handle is guaranteed to exist
        QTimer.singleShot(0, self._register)

    def _register(self) -> None:
        try:
            hwnd = int(self.winId())
            ctypes.windll.user32.RegisterHotKey(
                hwnd, HOTKEY_ID, HOTKEY_MODIFIERS, HOTKEY_VK
            )
        except Exception:
            pass   # Non-Windows or permission error — silently skip

    def nativeEvent(self, event_type, message):
        # message is a Shiboken VoidPtr; cast to MSG struct
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.activated.emit()
                return True, 0
        except Exception:
            pass
        return False, 0

    def closeEvent(self, event):
        try:
            hwnd = int(self.winId())
            ctypes.windll.user32.UnregisterHotKey(hwnd, HOTKEY_ID)
        except Exception:
            pass
        super().closeEvent(event)
