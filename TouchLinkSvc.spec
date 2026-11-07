# -*- mode: python ; coding: utf-8 -*-
# TouchLinkSvc v3.0 — PyInstaller spec (onefile, Windows x64, console)
#
# Build:  pyinstaller TouchLinkSvc.spec
# Service exe for capture & input when desktop is locked (SYSTEM session).

a = Analysis(
    ['desktop/svc_main.py'],
    pathex=['desktop'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Win32 service framework
        'win32timezone', 'servicemanager',
        'win32event', 'win32service', 'win32serviceutil',
        'win32api', 'win32con', 'win32gui',
        'win32file', 'win32pipe', 'win32security',
        'pywintypes',
        # Capture (service does screen grab)
        'dxcam', 'mss', 'mss.windows', 'numpy',
        'PIL', 'PIL._tkinter_finder',
        # Input
        'pyautogui', 'pyautogui._pyautogui_win',
        # Security
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        # System
        'psutil', 'ctypes', 'ctypes.wintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'unittest', '_pytest', 'pdb', 'pydoc',
        'scipy', 'pandas', 'matplotlib', 'IPython', 'notebook',
        'flask', 'django', 'tornado', 'fastapi',
        'setuptools', 'pip', 'wheel', 'pkg_resources', 'distutils',
        'tkinter.tix', 'lib2to3', 'curses',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TouchLinkSvc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        'vcruntime140.dll',
        'python3*.dll',
        'libcrypto*.dll',
        'libssl*.dll',
    ],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)
