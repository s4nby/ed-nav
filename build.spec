# build.spec
# PyInstaller spec file for ED Surface Navigator.
#
# Usage:
#   pyinstaller build.spec
#
# Output: dist/ed_navigator_v<VERSION>.exe  (single-file, no console window)

import os
import sys

block_cipher = None

# Pull version from constants.py without importing the full module
sys.path.insert(0, os.path.dirname(SPEC))
from constants import VERSION

# Optional icon — include if icon.ico exists in the project root
_icon_path = os.path.join(os.path.dirname(SPEC), "icon.ico")
_icon      = _icon_path if os.path.isfile(_icon_path) else None

a = Analysis(
    ["main.py"],
    pathex=[os.path.dirname(SPEC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f"ed_navigator_v{VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,             # None if ed_nav.ico not present
    version=None,
    uac_admin=False,
)
