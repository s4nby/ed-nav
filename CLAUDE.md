# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

ED Surface Navigator is a Windows desktop overlay for Elite Dangerous. It renders a compass needle pointing toward a player-defined surface target (lat/lon), reads game state from `Status.json` and journal files, and lives in the system tray. Built with PyQt6 + PyInstaller.

## Commands

**Run from source:**
```bash
python main.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Build executable:**
```bash
pyinstaller build.spec
# Output: dist/ed_navigator_v<VERSION>.exe
```

**Generate icon (if icon.ico is missing):**
```bash
python make_icon.py
```

There are no automated tests.

## Architecture

**Entry point:** `main.py` — creates all objects and wires signals together. The object graph is documented at the top of that file.

**Module responsibilities:**

| Module | Role |
|---|---|
| `constants.py` | All magic numbers, paths, colors, timing, hotkey codes |
| `tracker.py` | Polls `Status.json` every 100ms in a background thread. Exposes `NavResult` via `get_nav()`. Contains all navigation math (Haversine, bearing, relative bearing). |
| `journal.py` | Tails the latest `Journal.*.log` file in a background thread. Collects landable body names + radii from `Scan` events. Handles cross-session backfill (searches up to 20 recent journals). |
| `overlay.py` | Always-on-top, click-through (WS_EX_TRANSPARENT) needle canvas. Animated at 30 FPS. Contains `OverlayCanvas` (drawing logic) and `OverlayWindow` (Win32 window management). |
| `coord_window.py` | Settings/input window. Accepts lat/lon manually or via smart paste (`Ctrl+V` parses "lat: X, lon: Y" or "X, Y" formats). Shows body picker from journal data. |
| `tray.py` | System tray icon with context menu. |
| `hotkey.py` | Registers `Ctrl+Shift+N` as a global Win32 hotkey via a hidden `QWidget` that owns the HWND. |
| `updater.py` | Checks GitHub Releases API in a daemon thread. Emits `update_available` signal if newer version found. |

**Data flow:**
1. `GameTracker` polls `Status.json` → stores `PlayerState` under lock
2. `JournalWatcher` tails journal → stores `LandableBody` list under lock
3. `QTimer` fires every 100ms → calls `tracker.get_nav()` → pushes `NavResult` to `OverlayWindow` and `CoordWindow`
4. `OverlayCanvas` renders at 30 FPS independent of the nav timer

**State persistence:** `QSettings("ED-Navigator", "Overlay")` stores the last known star system across sessions (used to seed `JournalWatcher` for cross-session backfill). Overlay position is cleared on exit.

**Version:** Stored in `constants.py` as `VERSION`. To release, bump this string, tag the commit, and publish a GitHub release — the Actions workflow builds and attaches `EDNavigator.exe` automatically.

## Windows-specific details

- Click-through overlay uses `WS_EX_TRANSPARENT | WS_EX_LAYERED` via `ctypes.windll.user32`
- Global hotkey uses `RegisterHotKey` Win32 API
- ED process detection uses `CreateToolhelp32Snapshot`
- Game files live at `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\`
- The app is Windows-only; all Win32 calls fail silently on other platforms
