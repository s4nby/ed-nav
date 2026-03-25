# build.spec
# PyInstaller spec file for ED Surface Navigator.
#
# Usage:
#   pyinstaller build.spec
#
# Output: dist/ed_navigator.exe  (single-file, no console window)
#
# The exe name is fixed across all releases so that Windows Defender and other
# AV engines accumulate reputation against a stable filename. Version is
# embedded in the PE metadata (FileVersion / ProductVersion) instead.

import os
import sys

block_cipher = None

# Pull version from constants.py without importing the full module
sys.path.insert(0, os.path.dirname(SPEC))
from constants import VERSION

# Optional icon — include if icon.ico exists in the project root
_icon_path = os.path.join(os.path.dirname(SPEC), "icon.ico")
_icon      = _icon_path if os.path.isfile(_icon_path) else None

# ---------------------------------------------------------------------------
# Generate Windows PE version-info file from VERSION
# ---------------------------------------------------------------------------
_ver_parts = VERSION.split(".")
while len(_ver_parts) < 4:
    _ver_parts.append("0")
_ver_tuple = tuple(int(x) for x in _ver_parts[:4])
_ver_str   = ", ".join(str(x) for x in _ver_tuple)
_ver_str_dot = ".".join(str(x) for x in _ver_tuple)

_version_info_path = os.path.join(os.path.dirname(SPEC), "_version_info.txt")
with open(_version_info_path, "w") as _f:
    _f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({_ver_str}),
    prodvers=({_ver_str}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'FileDescription', u'ED Surface Navigator'),
         StringStruct(u'FileVersion', u'{_ver_str_dot}'),
         StringStruct(u'InternalName', u'ed_navigator'),
         StringStruct(u'OriginalFilename', u'ed_navigator.exe'),
         StringStruct(u'ProductName', u'ED Surface Navigator'),
         StringStruct(u'ProductVersion', u'{_ver_str_dot}'),
        ])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""")

a = Analysis(
    ["main.py"],
    pathex=[os.path.dirname(SPEC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
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
    name="ed_navigator",
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
    icon=_icon,             # None if icon.ico not present
    version=_version_info_path,
    uac_admin=False,
)
