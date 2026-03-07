# constants.py
# All configuration values for ED Surface Navigator.

import os

# ---------------------------------------------------------------------------
# App version & update feed
# ---------------------------------------------------------------------------
VERSION     = "1.1.3"
GITHUB_REPO = "s4nby/ed-nav"

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
JOURNAL_DIR = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "Saved Games",
    "Frontier Developments",
    "Elite Dangerous",
)
STATUS_JSON_PATH = os.path.join(JOURNAL_DIR, "Status.json")

# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------
POLL_INTERVAL_MS = 100          # Status.json polling interval (milliseconds)

# ---------------------------------------------------------------------------
# Window geometry
# ---------------------------------------------------------------------------
WINDOW_WIDTH  = 110
WINDOW_HEIGHT = 80

# ---------------------------------------------------------------------------
# Colours (Elite Dangerous orange palette)
# ---------------------------------------------------------------------------
COLOR_ORANGE     = "#FF6B00"
COLOR_ERROR      = "#FF3300"

# ---------------------------------------------------------------------------
# Opacity / alpha (0–255)
# ---------------------------------------------------------------------------
NEEDLE_ALPHA     = 230   # forward triangle
NEEDLE_TAIL_ALPHA = 70   # rear triangle
TEXT_ALPHA       = 210

# ---------------------------------------------------------------------------
# Needle geometry (pixels)
# ---------------------------------------------------------------------------
NEEDLE_LENGTH    = 24    # centre → tip
NEEDLE_TAIL      = 8     # centre → tail tip
NEEDLE_HALF_W    = 6     # half-width at the base

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------
RENDER_FPS           = 30
RENDER_INTERVAL_MS   = 1000 // RENDER_FPS   # ~33 ms
MAX_ROTATE_PER_FRAME = 25.0                 # degrees/frame
PULSE_SPEED          = 0.08                 # arrival pulse (radians/frame)

# ---------------------------------------------------------------------------
# Arrival threshold
# ---------------------------------------------------------------------------
ARRIVAL_DISTANCE_M   = 200   # metres — glowing circle + distance label
PROXIMITY_DISTANCE_M = 15    # metres — glowing circle only (no needle/distance)
PROXIMITY_EXIT_M     = 20    # metres — hysteresis: exit proximity state above this

# ---------------------------------------------------------------------------
# Orbital-zone activation threshold
# ---------------------------------------------------------------------------
# Orbital zone boundary ≈ 2 × planet_radius altitude above surface
# (orbit at 3× radius from centre = 2× from surface).
# Needle initialises this far before entering the orbital zone.
ORBITAL_ZONE_NEEDLE_M = 7_000_000  # 7,000 km — navigation needle + distance activates

# ---------------------------------------------------------------------------
# Planet default radius (metres)
# ---------------------------------------------------------------------------
DEFAULT_PLANET_RADIUS_M = 3_000_000

# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------
FONT_FAMILY      = "Courier New"
FONT_SIZE_DIST   = 10    # distance readout below needle

# ---------------------------------------------------------------------------
# Global hotkey (Ctrl+Shift+N)
# ---------------------------------------------------------------------------
HOTKEY_ID        = 1
MOD_NOREPEAT     = 0x4000
HOTKEY_MODIFIERS = 0x0002 | 0x0004 | MOD_NOREPEAT  # Ctrl + Shift + NoRepeat
HOTKEY_VK        = 0x4E   # 'N'
WM_HOTKEY        = 0x0312
