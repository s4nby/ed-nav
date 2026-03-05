# tracker.py
# Reads Status.json from the Elite Dangerous save directory, parses player
# position/heading, and computes bearing + Haversine distance to a target.
#
# Thread-safe: GameTracker runs a background polling thread and exposes
# state via properties protected by a threading.Lock.

import ctypes
import ctypes.wintypes as _wt
import datetime
import json
import math
import os
import threading
import time
from typing import Optional

from constants import (
    STATUS_JSON_PATH,
    POLL_INTERVAL_MS,
    DEFAULT_PLANET_RADIUS_M,
)

# ---------------------------------------------------------------------------
# Status.json flag bits
# ---------------------------------------------------------------------------
FLAG_HAS_LAT_LONG = 0x200000    # bit 21 — HasLatLong (lat/lon present in Status.json)
FLAG_IN_SRV       = 0x4000000   # bit 26 — InSrv (player is in Surface Rover Vehicle)


# ---------------------------------------------------------------------------
# Win32 process presence check
# ---------------------------------------------------------------------------

class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              _wt.DWORD),
        ("cntUsage",            _wt.DWORD),
        ("th32ProcessID",       _wt.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID",        _wt.DWORD),
        ("cntThreads",          _wt.DWORD),
        ("th32ParentProcessID", _wt.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             _wt.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]

_ED_EXE = b"EliteDangerous64.exe"


def _is_ed_running() -> bool:
    """Return True if EliteDangerous64.exe is present in the process list."""
    try:
        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snap == ctypes.wintypes.HANDLE(-1).value:
            return True  # Can't enumerate; assume running to avoid false negatives
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        found = False
        if kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile == _ED_EXE:
                    found = True
                    break
                if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(snap)
        return found
    except Exception:
        return True  # Fail-safe: don't hide overlay if check errors


class PlayerState:
    """Snapshot of one Status.json read."""
    __slots__ = ("latitude", "longitude", "heading", "altitude",
                 "has_lat_long", "in_srv", "valid", "flags", "timestamp_utc",
                 "body_name", "planet_radius_m")

    def __init__(self):
        self.latitude:      Optional[float]            = None
        self.longitude:     Optional[float]            = None
        self.heading:       Optional[float]            = None
        self.altitude:      Optional[float]            = None
        self.has_lat_long:  bool                       = False
        self.in_srv:        bool                       = False
        self.valid:         bool                       = False
        self.flags:         int                        = 0
        self.timestamp_utc: Optional[datetime.datetime] = None
        self.body_name:     Optional[str]              = None
        self.planet_radius_m: Optional[float]          = None


class NavResult:
    """Computed navigation output for the current frame."""
    __slots__ = ("bearing_to_target", "relative_bearing",
                 "distance_m", "has_lat_long", "arrived",
                 "body_name", "planet_radius_m")

    def __init__(self):
        self.bearing_to_target:  Optional[float] = None
        self.relative_bearing:   Optional[float] = None
        self.distance_m:         Optional[float] = None
        self.has_lat_long:       bool = False
        self.arrived:            bool = False
        self.body_name:          Optional[str]   = None
        self.planet_radius_m:    Optional[float] = None


# ---------------------------------------------------------------------------
# Maths helpers
# ---------------------------------------------------------------------------

def _deg2rad(deg: float) -> float:
    return deg * math.pi / 180.0


def compute_bearing(lat1_deg: float, lon1_deg: float,
                    lat2_deg: float, lon2_deg: float) -> float:
    """
    Return the initial bearing (0–360°) from point 1 to point 2 using the
    forward azimuth formula.
    """
    lat1 = _deg2rad(lat1_deg)
    lat2 = _deg2rad(lat2_deg)
    dlon = _deg2rad(lon2_deg - lon1_deg)

    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360.0) % 360.0


def compute_distance_m(lat1_deg: float, lon1_deg: float,
                       lat2_deg: float, lon2_deg: float,
                       radius_m: float = DEFAULT_PLANET_RADIUS_M) -> float:
    """
    Haversine distance between two surface points in metres.
    """
    lat1 = _deg2rad(lat1_deg)
    lat2 = _deg2rad(lat2_deg)
    dlat = _deg2rad(lat2_deg - lat1_deg)
    dlon = _deg2rad(lon2_deg - lon1_deg)

    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_m * c


def relative_bearing(bearing_to_target: float, player_heading: float) -> float:
    """
    Compute the bearing relative to the player's current heading (0–360°).
    0° means straight ahead; 180° means directly behind.
    """
    return (bearing_to_target - player_heading + 360.0) % 360.0


def shortest_arc(current: float, target: float) -> float:
    """
    Return the signed shortest angular difference from current → target,
    in the range [−180, +180].  Used for smooth heading interpolation.
    """
    diff = (target - current + 540.0) % 360.0 - 180.0
    return diff


# ---------------------------------------------------------------------------
# Status.json parser
# ---------------------------------------------------------------------------

def _parse_status(path: str) -> PlayerState:
    """
    Read and parse Status.json.  Returns a PlayerState; if the file is
    missing, locked, or malformed, returns state.valid == False.
    """
    state = PlayerState()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        flags = int(data.get("Flags", 0))
        state.flags        = flags
        state.has_lat_long = bool(flags & FLAG_HAS_LAT_LONG)
        state.in_srv       = bool(flags & FLAG_IN_SRV)

        if state.has_lat_long:
            state.latitude  = float(data["Latitude"])
            state.longitude = float(data["Longitude"])
            state.heading   = float(data.get("Heading", 0.0))
            state.altitude  = float(data.get("Altitude", 0.0))

        raw_body = data.get("BodyName")
        if raw_body:
            state.body_name = str(raw_body)

        raw_radius = data.get("PlanetRadius")
        if raw_radius is not None:
            state.planet_radius_m = float(raw_radius)

        raw_ts = data.get("timestamp")
        if raw_ts:
            try:
                state.timestamp_utc = datetime.datetime.fromisoformat(
                    raw_ts.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        state.valid = True

    except (OSError, IOError, KeyError, ValueError, json.JSONDecodeError):
        # Silently skip any read/parse failure
        pass

    return state


# ---------------------------------------------------------------------------
# GameTracker — background polling thread
# ---------------------------------------------------------------------------

class GameTracker:
    """
    Polls Status.json at POLL_INTERVAL_MS and exposes the latest PlayerState.
    Call set_target() to provide destination coordinates.
    Call get_nav() to obtain the latest NavResult.
    Call start() / stop() to control the background thread.
    """

    def __init__(self):
        self._lock        = threading.Lock()
        self._player      = PlayerState()
        self._target_lat: Optional[float] = None
        self._target_lon: Optional[float] = None
        self._planet_radius_m: float = DEFAULT_PLANET_RADIUS_M

        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._ed_running: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="ed-tracker"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the polling thread to stop."""
        self._running = False

    def set_target(self, lat: float, lon: float,
                   planet_radius_m: float = DEFAULT_PLANET_RADIUS_M) -> None:
        """Set the destination surface coordinates."""
        with self._lock:
            self._target_lat = lat
            self._target_lon = lon
            self._planet_radius_m = planet_radius_m

    def clear_target(self) -> None:
        """Remove the destination target."""
        with self._lock:
            self._target_lat = None
            self._target_lon = None

    def has_target(self) -> bool:
        with self._lock:
            return self._target_lat is not None

    def is_in_game(self) -> bool:
        """True when EliteDangerous64.exe is running and Status.json flags are non-zero."""
        with self._lock:
            if not self._ed_running:
                return False
            p = self._player
            return p.valid and p.flags != 0

    def get_player_state(self) -> PlayerState:
        """Return a copy of the latest player state."""
        with self._lock:
            return self._player

    def get_nav(self) -> NavResult:
        """
        Compute and return the latest navigation result.
        Thread-safe snapshot — call from the UI thread.
        """
        result = NavResult()
        with self._lock:
            player = self._player
            target_lat = self._target_lat
            target_lon = self._target_lon
            radius = self._planet_radius_m

        result.has_lat_long   = player.has_lat_long
        result.body_name      = player.body_name
        result.planet_radius_m = player.planet_radius_m

        if not player.has_lat_long or not player.valid:
            return result

        if target_lat is None or target_lon is None:
            return result

        lat1 = player.latitude
        lon1 = player.longitude
        hdg  = player.heading

        # Prefer live planet radius from Status.json over the user-supplied value
        radius = player.planet_radius_m if player.planet_radius_m else radius

        bearing  = compute_bearing(lat1, lon1, target_lat, target_lon)
        distance = compute_distance_m(lat1, lon1, target_lat, target_lon, radius)
        rel_brg  = relative_bearing(bearing, hdg)

        from constants import ARRIVAL_DISTANCE_M
        result.bearing_to_target = bearing
        result.relative_bearing  = rel_brg
        result.distance_m        = distance
        result.arrived           = distance < ARRIVAL_DISTANCE_M

        return result

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        interval_s = POLL_INTERVAL_MS / 1000.0
        poll_count = 0
        ed_running = _is_ed_running()  # check immediately on start
        while self._running:
            state = _parse_status(STATUS_JSON_PATH)
            poll_count += 1
            if poll_count >= 30:        # re-check process every ~3 s
                poll_count = 0
                ed_running = _is_ed_running()
            with self._lock:
                self._player     = state
                self._ed_running = ed_running
            time.sleep(interval_s)
