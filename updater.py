# updater.py
# Background update checker for ED Surface Navigator.
#
# Flow:
#   1. start() — spawns a daemon thread; waits 45 s before hitting the network
#      (immediate outbound connections on launch are a heuristic AV trigger).
#   2. If a newer version is found, emits update_available(version).
#   3. On failure at any stage, silently exits — the check is best-effort.
#
# No download or execution is performed. The user is directed to GitHub.

import json
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

class UpdateChecker(QObject):
    """
    Emits update_available(version) when a newer release is detected on GitHub.
    No download or execution is performed.
    """

    update_available = Signal(str)  # version string

    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo    = repo
        self._current = current_version
        self.releases_url = f"https://github.com/{repo}/releases/latest"

    def start(self) -> None:
        threading.Thread(
            target=self._run, daemon=True, name="ed-updater"
        ).start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        time.sleep(45)  # defer — immediate network calls trigger heuristic AV
        try:
            url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ED-Navigator"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            latest = data.get("tag_name", "").lstrip("v")

            if not latest or not self._is_newer(latest):
                return

            self.update_available.emit(latest)

        except Exception:
            pass   # network unavailable, rate-limited, repo not found, etc.

    def _is_newer(self, latest: str) -> bool:
        try:
            return (
                tuple(int(x) for x in latest.split("."))
                > tuple(int(x) for x in self._current.split("."))
            )
        except ValueError:
            return False
