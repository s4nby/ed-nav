# main.py
# Entry point for ED Surface Navigator.
#
# Object graph:
#   QApplication
#   ├── GameTracker   (background polling thread)
#   ├── OverlayWindow (always-on-top, click-through, 300×300)
#   ├── CoordWindow   (hidden initially; opened from tray / on_settings)
#   ├── GlobalHotkey  (hidden QWidget owning the Win32 hotkey HWND)
#   └── TrayIcon      (system tray)
#

import ctypes
import sys

from PySide6.QtCore    import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from coord_window import CoordWindow
from hotkey       import GlobalHotkey
from journal      import JournalWatcher
from overlay      import InclinationOverlay, OverlayWindow
from tracker      import GameTracker
from tray         import TrayIcon
from updater      import UpdateChecker
from constants    import POLL_INTERVAL_MS, VERSION, GITHUB_REPO


def main():
    # Give this process its own App User Model ID so Windows uses the
    # Qt window icon for the taskbar button instead of python.exe's icon.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ED.Navigator.App")

    app = QApplication(sys.argv)
    app.setApplicationName("ED Surface Navigator")
    # Keep running even when CoordWindow is the last visible window and is closed
    app.setQuitOnLastWindowClosed(False)

    # Global styling for tooltips to match the ED-style theme
    app.setStyleSheet(
        "QToolTip {"
        "  background-color: #1e1f20;"
        "  color: #FF8C00;"
        "  border: 1px solid #CC6600;"
        "  padding: 5px;"
        "  border-radius: 2px;"
        "  font-family: 'Agency FB';"
        "  font-size: 10pt;"
        "}"
    )

    # ------------------------------------------------------------------
    # Core objects
    # ------------------------------------------------------------------
    _startup_settings = QSettings("ED-Navigator", "Overlay")
    _last_system      = _startup_settings.value("journal/last_system", "")

    tracker       = GameTracker()
    journal       = JournalWatcher(last_session_system=_last_system)
    updater       = UpdateChecker(GITHUB_REPO, VERSION)
    overlay       = OverlayWindow()
    incl_overlay  = InclinationOverlay()
    coord_window  = CoordWindow()
    hotkey       = GlobalHotkey()
    tray         = TrayIcon()

    app.setWindowIcon(TrayIcon._make_icon())

    tracker.start()
    journal.start()
    overlay.show()
    incl_overlay.show()
    coord_window.show()
    tray.show()

    # ------------------------------------------------------------------
    # State flags
    # ------------------------------------------------------------------
    _state = {
        "move_mode": False,
    }

    # ------------------------------------------------------------------
    # Toggle overlay visibility
    # ------------------------------------------------------------------
    def _toggle_overlay():
        new_visible = overlay.toggle_visibility()
        incl_overlay.setVisible(new_visible)
        tray.set_overlay_visible(new_visible)
        coord_window.set_overlay_visible(new_visible)
        # If we're hiding while in move mode, exit move mode too
        if not new_visible and _state["move_mode"]:
            _exit_move_mode()

    # ------------------------------------------------------------------
    # Move mode
    # ------------------------------------------------------------------
    def _toggle_move_mode():
        if not _state["move_mode"]:
            _enter_move_mode()
        else:
            _exit_move_mode()

    def _enter_move_mode():
        # Make overlay visible first so the user can see and drag it
        if not overlay.isVisible():
            overlay.show()
            tray.set_overlay_visible(True)
            coord_window.set_overlay_visible(True)
        overlay.enter_move_mode()
        tray.set_move_mode(True)
        coord_window.set_move_mode(True)
        _state["move_mode"] = True

    def _exit_move_mode():
        overlay.exit_move_mode()
        tray.set_move_mode(False)
        coord_window.set_move_mode(False)
        _state["move_mode"] = False

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    # Update checker
    updater.update_available.connect(
        lambda v: coord_window.show_update_available(v, updater.releases_url)
    )
    updater.start()

    hotkey.activated.connect(_toggle_overlay)

    tray.toggle_overlay.connect(_toggle_overlay)
    tray.move_overlay.connect(_toggle_move_mode)
    coord_window.move_overlay.connect(_toggle_move_mode)
    coord_window.toggle_overlay.connect(_toggle_overlay)
    tray.open_settings.connect(lambda: (coord_window.show(), coord_window.raise_()))
    tray.toggle_settings.connect(
        lambda: coord_window.hide() if coord_window.isVisible()
        else (coord_window.show(), coord_window.raise_())
    )

    coord_window.target_set.connect(
        lambda lat, lon, r, body, sys: tracker.set_target(lat, lon, r, body, sys)
    )
    coord_window.target_cleared.connect(tracker.clear_target)

    # ------------------------------------------------------------------
    # Nav update loop (every POLL_INTERVAL_MS)
    # ------------------------------------------------------------------
    nav_timer = QTimer()
    nav_timer.setInterval(POLL_INTERVAL_MS)

    def push_nav():
        nav        = tracker.get_nav()
        has_target = tracker.has_target()
        nav.vehicle_name = journal.get_vehicle_name()
        if has_target:
            target_sys  = tracker.get_target_system()
            current_sys = journal.get_system()
            if target_sys and current_sys:
                nav.system_mismatch = target_sys.lower() != current_sys.lower()
        overlay.update_nav(nav, has_target)
        incl_overlay.update_nav(nav, has_target)
        coord_window.update_status(nav, has_target)
        coord_window.update_bodies(journal.get_bodies(), journal.get_system(), journal.get_scan_required())

    nav_timer.timeout.connect(push_nav)
    nav_timer.start()

    # ------------------------------------------------------------------
    # Clean up on exit
    # ------------------------------------------------------------------
    def _on_quit():
        tracker.stop()
        journal.stop()
        nav_timer.stop()
        settings = QSettings("ED-Navigator", "Overlay")
        settings.remove("overlay/x")
        settings.remove("overlay/y")
        settings.setValue("journal/last_system", journal.get_system())
        hotkey.close()

    app.aboutToQuit.connect(_on_quit)
    tray.quit_app.connect(app.quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
