# Changelog

All notable changes to ED Surface Navigator are documented here.
Versions follow [Semantic Versioning](https://semver.org/).

---

## [1.0.10] — Unreleased heading to [1.1.0] — 2026-03-06

### Added
- 3D interactive planet preview in the settings window — drag to rotate, click to set coordinates
- Heading deadzone: suppresses needle when target bearing falls in the compass blind-spot (−60° to −90°), with per-ship tuning for "Caspian Explorer" (−75° to −90°)
- Proximity state (< 15 m): replaces needle + distance with a pulsing circle; hysteresis prevents flicker near the threshold
- Natural sort in the body picker menu (numbers sort numerically, not lexicographically)
- Descent pitch guidance panel: shows required approach angle and a single up/down arrow when off the glide path

### Changed
- Overlay window shrunk to 110 × 80 px default to reduce screen footprint
- Needle pivot shifted left to make room for the inclination panel on the right

---

## [1.0.9] — 2024

### Added
- Speed-proportional needle tail: tail elongates as ship speed increases (up to ~1.55× at 80 m/s)
- Altitude and vertical-speed tracking (exponential smoothing)
- Target descent angle computed from live altitude + distance

### Changed
- GPS dropout grace period extended to ~200 ms (~6 frames at 30 FPS) to absorb brief `HasLatLong` flickers

---

## [1.0.8] — 2024

### Fixed
- Context menu label correctly reflects overlay visibility state ("Hide Overlay" / "Show Overlay")
- Header row alignment in settings window

---

## [1.0.7] — 2024

### Added
- Needle colour changes with bearing accuracy: blue (≤ 10° off), orange (≤ 45°), red (> 45°)
- Overlay resize grip in move mode — bottom-right corner, locked to aspect ratio
- Cross-session journal backfill: scans up to 20 recent journals for `Scan` events so previously FSS-scanned bodies persist across restarts

### Changed
- Move mode now shows "DRAG" text with a dashed border instead of a blank transparent box

---

## [1.0.0] — 2024

### Added
- Initial release
- Always-on-top, click-through transparent overlay with compass needle
- Haversine surface navigation from `Status.json`
- `Ctrl+Shift+N` global hotkey to toggle overlay
- System tray icon with context menu
- Settings window with lat/lon inputs and smart paste (parses `Lat: X / Lon: Y` strings)
- Planet body picker populated from journal `Scan` events
- Update checker via GitHub Releases API
- Single-file executable via PyInstaller
