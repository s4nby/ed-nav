# updater.py
# Background update checker for ED Surface Navigator.
#
# On start() it spawns a daemon thread that calls the GitHub Releases API.
# If a newer version is found it emits update_available(version, url).
# All network errors are silently swallowed — the check is best-effort.

import json
import threading
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal


class UpdateChecker(QObject):
    """Emits update_available(latest_version, release_url) when an update exists."""

    update_available = pyqtSignal(str, str)   # (version string, release page URL)

    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo    = repo
        self._current = current_version

    def start(self) -> None:
        threading.Thread(
            target=self._run, daemon=True, name="ed-updater"
        ).start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ED-Navigator"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            latest      = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")

            if latest and release_url and self._is_newer(latest):
                self.update_available.emit(latest, release_url)
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
