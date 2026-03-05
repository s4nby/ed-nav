# ED  Navigator

A lightweight desktop overlay for **Elite Dangerous** that guides you to any
surface location on a landable planet. It reads your current position and
heading from the game's live `Status.json` file, computes the bearing and
distance to a pair of user-supplied coordinates, and renders a minimal
orange reticle — always on top of the game window, always click-through —
that rotates to point toward your destination. No game memory is touched,
no network requests are made, and no game files are modified.

---

## Requirements

| Requirement | Notes |
|---|---|
| **Windows 10 / 11 x64** | Click-through transparency uses Win32 APIs |
| **Python 3.11 or later** | 3.12 recommended |
| **Elite Dangerous** | Any current version (Odyssey / Legacy) |
| **pip** | For installing Python dependencies |

---

## Installation

```bash
# 1. Clone or extract the project
cd ed-nav

# 2. (Recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

The overlay appears as a small 300 × 300 px transparent window centred on
your primary monitor.  It is always on top and click-through — your mouse
interacts with the game normally.

### Setting a destination

1. Click the **gear icon** (⚙) in the top-right corner of the overlay.
2. Enter **Latitude** and **Longitude** in the input fields.
3. Click **Set Target**.

**Tip:** You can paste a coordinate string straight from the game's POI
clipboard — the panel understands formats like:

```
Lat: -22.45 / Lon: 137.88
```

Paste into the Latitude field; both values fill automatically.

### Moving the overlay

Hover over the top-left corner to reveal the drag handle, then click and
drag the window to any position on screen.

---

## Status indicators

| Label | Meaning |
|---|---|
| `TRACKING` | Live data received; arrow pointing to destination |
| `NO SIGNAL` | `HasLatLong` flag not set (in space, menu, etc.) |
| `SET TARGET` | Planet data live but no destination entered |
| *(pulsing crosshair)* | Within 200 m of destination — you have arrived |

---

## Building the executable

```bash
pyinstaller build.spec
```

The single-file executable `dist\EDNavigator.exe` requires no Python
installation on the target machine.  If you place a file named `ed_nav.ico`
in the project root before building, it will be used as the application icon.

---

## Privacy & safety notice

ED Surface Navigator is a **read-only** tool.  It:

- Reads only `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\Status.json`
- Does **not** access game memory, inject code, or modify any game file
- Does **not** make any network requests or send any telemetry
- Is not affiliated with Frontier Developments plc

Use is consistent with Frontier's player-tool policies for read-only journal
access.
