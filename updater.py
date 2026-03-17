# updater.py
# Background update checker and downloader for ED Surface Navigator.
#
# Flow:
#   1. start() — spawns a daemon thread; waits 45 s before hitting the network
#      (immediate outbound connections on launch are a heuristic AV trigger).
#   2. If a newer version is found, emits update_available(version) and begins
#      downloading ed_navigator.exe from the release assets in the same thread.
#   3. On successful download, emits update_ready(version, path_to_new_exe).
#   4. On failure at any stage, silently exits — the check is best-effort.
#
# The caller (main.py) applies the update via _do_apply_update().

import json
import os
import sys
import threading
import time
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

# Name of the release asset to download — must match what CI uploads.
_ASSET_NAME = "ed_navigator.exe"


class UpdateChecker(QObject):
    """
    Emits update_available(version) when a newer release is detected and the
    download has started, then emits update_ready(version, new_exe_path) when
    the download is complete and the file is ready to swap in.
    """

    update_available = pyqtSignal(str)       # version string — download in progress
    update_ready     = pyqtSignal(str, str)  # (version, absolute path to downloaded exe)

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
        time.sleep(45)  # defer — immediate network calls trigger heuristic AV
        try:
            url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ED-Navigator"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            latest      = data.get("tag_name", "").lstrip("v")
            asset_url   = next(
                (a["browser_download_url"] for a in data.get("assets", [])
                 if a.get("name") == _ASSET_NAME),
                None,
            )

            if not latest or not asset_url or not self._is_newer(latest):
                return

            self.update_available.emit(latest)
            self._download(latest, asset_url)

        except Exception:
            pass   # network unavailable, rate-limited, repo not found, etc.

    def _download(self, version: str, url: str) -> None:
        """Download the new exe next to the running exe, then signal readiness."""
        # In development (python main.py) sys.executable is python.exe — skip.
        if not getattr(sys, "frozen", False):
            return

        dest = os.path.join(os.path.dirname(sys.executable), "ed_navigator_new.exe")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ED-Navigator"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(dest, "wb") as fh:
                    fh.write(resp.read())
            self.update_ready.emit(version, dest)
        except Exception:
            # Clean up a partial download so it doesn't linger.
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except OSError:
                pass

    def _is_newer(self, latest: str) -> bool:
        try:
            return (
                tuple(int(x) for x in latest.split("."))
                > tuple(int(x) for x in self._current.split("."))
            )
        except ValueError:
            return False
