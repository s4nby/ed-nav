# Changelog

All notable changes to ED Surface Navigator are documented here.
Versions follow [Semantic Versioning](https://semver.org/).

---

## [1.4.7] Released — 2026-03-12

### Added
- **Dynamic Context Menus**: 'Select a Planet' and 'Recent' menus now use a flexible width (320px–480px) and dynamic elision, ensuring long body names are handled gracefully while keeping coordinates visible.
- **Compact Navigation Controls**: Relocated 'Clear' and 'Set Target' buttons to a new icon row beneath the longitude field, featuring custom vector icons: circular reset arrow and right-pointing send arrow.
- **Improved Icon Visibility**: All vector icons scaled up to 20px with increased default opacity and brighter default colors (_COL_LABEL) for better legibility.
- **Input Validation**: The 'Set Target' button is now dynamically enabled only when a valid body name is entered, providing immediate visual feedback for correct usage.

### Changed
- **Standardized UI Dimensions**: Standardized the top navigation bar and sidebar height to 48px, creating a unified visual "frame" for the main interface.
- **Refined Aesthetics**: Updated global border and separator colors to #363636 for a subtler, more professional theme.
- **Refactored Status Bar**: Simplified the top navigation bar with fixed-width labels ("NO SIGNAL", "ARRIVED", and numeric distance like "75.2 KM"), allowing the 'Select a Planet' button to be permanently expanded and centered.
- **Enhanced Planet Preview**: Increased the opacity of 3D placeholder elements (central dot and dashed ring) for significantly better visibility against dark backgrounds.
- **Sidebar Gutter**: Added a 1px right margin to the sidebar layout and an inset to highlights to prevent selection/hover bleed into the vertical separator.

### Fixed
- **Context Menu Hover Regression**: Resolved a persistent issue where planet labels in custom context menus failed to trigger their hover highlight states reliably.
- **Icon Centering**: Perfectly centered the 'About' icon in the sidebar footer and other navigation items within the collapsed 48px width.

---

## [1.4.3] Released — 2026-03-11

### Added
- Sidebar search button: when the sidebar is expanded, a Search icon appears on the opposite side of the hamburger button
- Bookmark search bar: clicking the search icon switches to the Bookmarks page and reveals a filter input
- Bookmark filtering by name, system, body, or coordinates (case-insensitive substring match)
- Add-bookmark placeholder is suppressed during an active search to avoid confusion

### Changed
- Removed "MENU" text label from the expanded sidebar header; replaced with the search icon
- Sidebar collapse now also hides and clears the search bar

### Fixed
- Recent context menu item padding reduced (6 px → 3 px vertical, 16 px → 12 px horizontal) for a denser, desktop-class layout
- Recent context menu font size reduced by 1 pt to match

---

## [1.4.0] Released — 2026-03-11

### Added
- **Sidebar Navigation:** New animated sidebar for switching between Coordinate Entry, History, and Bookmarks panels
- **Custom Title Bar:** Draggable title bar with integrated minimize/maximize/close controls and built-in update notification button (replaces tray balloon notifications)
- **Bookmarks System:** Save and name favourite surface locations for quick access
- **Star System Awareness:** Tracks which star system a target belongs to; "WRONG SYSTEM" overlay warning when in a different system than the target
- **"APPROACH" State:** Displays "APPROACH THE PLANET" immediately after setting a new target until a valid GPS fix is confirmed, preventing stale needle display
- **"WRONG BODY" Warning:** Visual alert when current GPS fix is on a different planet than the selected target
- **Click-to-Set on Planet Preview:** Click directly on the 3D sphere to set navigation coordinates
- **Far-Side Tracking:** Targets on the opposite side of the planet rendered as dashed "ghost" markers
- **Planet Preview Auto-Activation:** Preview activates automatically when focusing coordinate input fields
- **Randomize Button:** Generates random valid coordinates for exploration or testing
- **Persistent History:** History menu now tracks body names and persists across sessions
- Modern aesthetics: rounded corners, Elite Dangerous-themed tooltips, improved element spacing

### Changed
- Planet preview gains auto-rotation when idle and smooth fade-in animations
- Activation threshold increased to 7,000 km for more lead time during orbital approach
- Coordinate validation now strictly enforces 4 decimal places of precision

### Fixed
- GPS grace period tuned for close-range dropouts (< 200 m) to prevent flickering during final landing approach
- Inclination panel alignment issues corrected; missing degree symbols added to readout
- Release workflow: versioned executable filenames now handled correctly in automated build

---

## [1.1.2] Released — 2026-03-07

### Added
- 3D interactive planet preview in the settings window — drag to rotate (click-to-fill coordinate feature removed due to raycasting inaccuracy against atmospheric geometry)
- Heading deadzone: suppresses needle when target bearing falls in the compass blind-spot (−60° to −90°), with per-ship tuning for Caspian Explorer (−75° to −90°)
- Proximity state (< 15 m): replaces needle + distance with a pulsing circle; hysteresis prevents flicker near the threshold
- Natural sort in the body picker menu (numbers sort numerically, not lexicographically)
- Independent inclination overlay: triple-chevron pitch-correction array in its own click-through window, positioned to the left of screen centre to mirror the ED altitude ladder
- Sequential chase animation on chevrons — sine-wave phase offset per chevron, direction matches required correction (up/down)
- Conditional colour state on inclination cluster: cyan/blue (#4499FF) when glide path is aligned, amber/orange when correction is needed — matches the navigation needle's aligned colour exactly
- Degree value displayed adjacent to the chevron column for at-a-glance angle reference
- Staged HUD activation: full needle and distance readout appear within 4,000 km of the orbital zone boundary; approach label shown beyond that threshold
- `AltitudeFromAverageRadius` flag (Status.json bit 29) used as the authoritative gate for orbital-flight UI — no heuristics

### Changed
- Overlay window shrunk to 110 × 80 px; needle re-centred (pivot no longer offset)
- Main navigator restored to top-centre default position after inclination panel decoupling
- Inclination indicators scaled up: larger chevrons, heavier stroke (2.5 px), 11 pt degree text for improved legibility

### Fixed
- Stale coordinate bug: switching planet bodies in the body picker no longer carries over the previous body's lat/lon into the new target
- Wrong planet radius in Haversine: distance was calculated against the player's current physical location planet rather than the selected navigation target body; live radius is now used only as a fallback when no body has been explicitly chosen

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
