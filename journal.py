# journal.py
# Tails the latest Elite Dangerous journal file and collects landable
# body data from FSS/Scan events.
#
# Key limitation of ED's journal format:
#   A game session starts with a `Location` event but does NOT re-emit
#   `Scan` events for bodies scanned in previous sessions.  To handle
#   this, whenever the current system is (re)detected we backfill by
#   scanning recent journal files for matching Scan events.
#
# Thread-safe: all state is protected by self._lock.

import glob
import json
import os
import threading
import time
from typing import NamedTuple, Optional

from constants import JOURNAL_DIR, POLL_INTERVAL_MS


class LandableBody(NamedTuple):
    name:     str
    radius_m: float


def _latest_journal(directory: str) -> Optional[str]:
    files = glob.glob(os.path.join(directory, "Journal.*.log"))
    return max(files, key=os.path.getmtime) if files else None


class JournalWatcher:
    """
    Background thread that reads journal events and exposes landable bodies.
    Handles cross-session scans via _backfill().
    """

    def __init__(self, last_session_system: str = ""):
        self._lock                = threading.Lock()
        self._bodies:             list[LandableBody] = []
        self._system:             str = ""
        self._scan_required:      bool = False
        self._last_session_system = last_session_system
        self._thread:             Optional[threading.Thread] = None
        self._running             = False

    # ------------------------------------------------------------------
    # Public API (thread-safe, call from UI thread)
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="ed-journal"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_bodies(self) -> list[LandableBody]:
        with self._lock:
            return list(self._bodies)

    def get_system(self) -> str:
        with self._lock:
            return self._system

    def get_scan_required(self) -> bool:
        with self._lock:
            return self._scan_required

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        interval_s   = POLL_INTERVAL_MS / 1000.0
        current_path = None
        fh           = None

        while self._running:
            latest = _latest_journal(JOURNAL_DIR)

            if latest != current_path:
                # New or first journal file — read from the beginning
                if fh:
                    fh.close()
                current_path = latest
                if latest:
                    try:
                        fh = open(latest, "r", encoding="utf-8", errors="replace")
                        self._ingest(fh.readlines())
                    except OSError:
                        fh = None
                else:
                    fh = None
            elif fh:
                # Tail: pick up lines written since last poll
                try:
                    new = fh.readlines()
                    if new:
                        self._ingest(new)
                except OSError:
                    pass

            time.sleep(interval_s)

        if fh:
            fh.close()

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    def _ingest(self, raw_lines: list[str]) -> None:
        for raw in raw_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._handle(ev)

    def _handle(self, ev: dict) -> None:
        kind = ev.get("event", "")

        if kind in ("FSDJump", "CarrierJump", "Location"):
            system = ev.get("StarSystem", "")
            with self._lock:
                prev = self._system
                self._bodies = []
                self._system = system
                # New system relative to last app session → require a scan
                self._scan_required = (system != self._last_session_system)
            if system and system != prev:
                self._backfill(system)
                # If backfill found bodies we already know this system — no scan needed
                with self._lock:
                    if self._bodies:
                        self._scan_required = False

        elif kind == "Scan" and ev.get("Landable"):
            name   = ev.get("BodyName", "")
            radius = ev.get("Radius")
            if name and radius:
                body = LandableBody(name=name, radius_m=float(radius))
                with self._lock:
                    if not any(b.name == name for b in self._bodies):
                        self._bodies.append(body)
                    self._scan_required = False  # bodies detected, clear the flag

    # ------------------------------------------------------------------
    # Cross-session backfill
    # ------------------------------------------------------------------

    def _backfill(self, system: str) -> None:
        """
        Search up to 20 recent journal files for Scan events whose
        BodyName starts with `system`.  Merges results into self._bodies.

        ED body names are always "<SystemName> <designator>", so the
        prefix check is an exact system match with no false positives.
        """
        prefix = system + " "
        found: dict[str, LandableBody] = {}

        journals = sorted(
            glob.glob(os.path.join(JOURNAL_DIR, "Journal.*.log")),
            key=os.path.getmtime,
            reverse=True,
        )

        for path in journals[:20]:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for raw in f:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if (ev.get("event") == "Scan"
                                and ev.get("Landable")
                                and ev.get("BodyName", "").startswith(prefix)):
                            name = ev["BodyName"]
                            r    = ev.get("Radius")
                            if r and name not in found:
                                found[name] = LandableBody(
                                    name=name, radius_m=float(r)
                                )
            except OSError:
                continue

        if found:
            with self._lock:
                existing = {b.name for b in self._bodies}
                for body in found.values():
                    if body.name not in existing:
                        self._bodies.append(body)
                        existing.add(body.name)
