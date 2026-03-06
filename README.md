# ED Surface Navigator

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/s4nby/ed-nav)](https://github.com/s4nby/ed-nav/releases/latest)

A lightweight, always-on-top overlay for **Elite Dangerous** that guides you to any
surface location on a landable planet.

It reads your position and heading from the game's live `Status.json` file, computes
bearing and distance to a pair of coordinates you supply, and renders a minimal
compass needle — always above the game window, always click-through, never touching
game memory.

---

## Features

- **Compass needle** — rotates in real time, colour-coded by heading accuracy (blue / orange / red)
- **Distance readout** — switches between metres and kilometres automatically
- **Pitch guidance** — shows the required descent angle and whether to pull up or push down
- **Arrival detection** — pulsing circle replaces the needle when you're within 200 m; proximity ring at 15 m
- **Heading deadzone** — suppresses the needle when the target falls in the compass blind-spot so the reading is never misleading
- **Planet picker** — populated automatically from your FSS scan history, including across game sessions
- **3D globe preview** — drag to rotate, click to drop a coordinate marker directly on the planet surface
- **Smart paste** — paste `Lat: -22.45 / Lon: 137.88` strings from POI tools and both fields fill at once
- **Global hotkey** — `Ctrl+Shift+N` toggles the overlay without leaving the game
- **Auto-updater** — checks GitHub Releases on startup and shows a tray notification when a new version is available
- **Zero footprint** — read-only access to two local files; no network calls during play, no telemetry

---

## Requirements

| | |
|---|---|
| **OS** | Windows 10 or 11 (64-bit) |
| **Python** | 3.11 or later (3.12 recommended) |
| **Game** | Elite Dangerous — any current version (Odyssey / Legacy) |

Or just [download the pre-built `.exe`](https://github.com/s4nby/ed-nav/releases/latest) — no Python required.

---

## Installation (from source)

```bash
# 1. Clone the repository
git clone https://github.com/s4nby/ed-nav.git
cd ed-nav

# 2. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

---

## Usage

### Setting a destination

1. Double-click the tray icon, or right-click it and choose **Open Settings**.
2. Select a planet from the **planet picker** (populated after an FSS scan), or type a body name manually.
3. Enter **Latitude** and **Longitude**, then click **Set Target**.

**Tip:** paste a coordinate string directly — the app understands formats like:

```
Lat: -22.45 / Lon: 137.88
-22.45, 137.88
```

Paste into the Latitude field; both values fill automatically.

### Moving or resizing the overlay

Right-click the tray icon and choose **Move Overlay**. The overlay gains a dashed
border and a drag handle. Grab the bottom-right corner to resize (aspect ratio is
locked). Click **Done Moving** in the settings window when finished.

### Keyboard shortcut

`Ctrl+Shift+N` toggles overlay visibility at any time, even while the game has focus.

---

## Status indicators

| Display | Meaning |
|---|---|
| Compass needle | Live tracking — arrow points toward destination |
| `XX° ▲ / ▼` | Pitch guidance — pull up or push down to hit the glide path |
| Pulsing ring (large) | Within 200 m — arrival zone |
| Pulsing dot (small) | Within 15 m — you are on-target |
| Three animated dots | App is running but no target is set |
| `APPROACH THE PLANET` | Target set but no GPS signal (in space or in menus) |

---

## Building the executable

```bash
pyinstaller build.spec
# Output: dist\EDNavigator.exe
```

The single-file executable requires no Python installation on the target machine.
GitHub Actions builds and attaches it automatically on every tagged release.

---

## Privacy & safety

ED Surface Navigator is **read-only**. It:

- Reads only `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\Status.json` and `Journal.*.log`
- Does **not** access game memory, inject code, or modify any game file
- Makes one HTTPS request at startup to check for updates (GitHub Releases API); no data is sent
- Is not affiliated with Frontier Developments plc

Use is consistent with Frontier's player-tool policies for read-only journal access.

---

## Architecture

The source is split into single-responsibility modules:

| Module | Role |
|---|---|
| `main.py` | Entry point — wires all objects together |
| `constants.py` | All magic numbers, colours, timing, hotkey codes |
| `tracker.py` | Polls `Status.json`; all navigation maths (Haversine, bearing) |
| `journal.py` | Tails journal files; collects landable body names and radii |
| `overlay.py` | Click-through needle canvas, 30 FPS animation loop |
| `coord_window.py` | Settings window — input, planet picker, status display |
| `planet_preview.py` | Interactive 3D globe with orthographic projection |
| `tray.py` | System tray icon and context menu |
| `hotkey.py` | Win32 global hotkey registration |
| `updater.py` | GitHub Releases version check |

See [CLAUDE.md](CLAUDE.md) for the full data-flow diagram and architectural notes.

---

## Contributing

Bug reports and feature requests are welcome via [GitHub Issues](https://github.com/s4nby/ed-nav/issues).

If you want to submit a pull request:
1. Keep changes focused — one concern per PR.
2. Run the app against a live game session and confirm nothing regresses.
3. Update `CHANGELOG.md` under the `[Unreleased]` heading.

---

## License

[MIT](LICENSE) — do whatever you like, just keep the copyright notice.
