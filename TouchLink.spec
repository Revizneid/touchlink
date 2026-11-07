# -*- mode: python ; coding: utf-8 -*-
# TouchLink v3.0 — PyInstaller spec (onefile, Windows x64)
#
# Build:  pyinstaller TouchLink.spec
# Target: < 35 MB portable exe (UPX + aggressive excludes)

import sys
from PyInstaller.utils.hooks import collect_submodules

# -- Collect submodules for complex packages that use lazy/dynamic imports ------
_aiortc_hidden = collect_submodules('aiortc')
_av_hidden = collect_submodules('av')

# -- Hidden imports: every third-party package the app touches -----------------
_hidden = [
    # Image / QR
    'qrcode', 'qrcode.image.pil', 'qrcode.image.base',
    'PIL', 'PIL._tkinter_finder', 'PIL.ImageTk',
    # Capture
    'dxcam', 'mss', 'mss.windows',
    'numpy',
    # Clipboard
    'pyperclip',
    # Audio (WASAPI loopback)
    'soundcard', 'soundcard.mediafoundation',
    # WebRTC / media — collected via collect_submodules above
    # Networking
    'aiohttp', 'aiohttp.web',
    # Crypto (Ed25519, AESGCM, HKDF, X25519)
    'cryptography',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.primitives.asymmetric.x25519',
    'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.ciphers.aead',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.kdf.hkdf',
    'cryptography.hazmat.primitives.serialization',
    # System
    'psutil',
    # Win32 (pywin32) — pipe IPC with service
    'win32file', 'win32pipe', 'win32security',
    'win32event', 'win32service', 'win32serviceutil',
    'servicemanager', 'pywintypes', 'win32timezone',
    # Tkinter — GUI
    'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
    # Stdlib that PyInstaller occasionally misses
    'asyncio', 'queue', 'json', 'hashlib', 'struct', 'secrets',
    'fractions', 'dataclasses', 'platform',
]
_hidden += _aiortc_hidden + _av_hidden

# -- Aggressive excludes to trim size below 35 MB ------------------------------
_excludes = [
    # Test / dev tooling
    'pytest', 'unittest', '_pytest', 'doctest', 'pdb', 'pydoc',
    # Unused scientific/data libs often dragged in by numpy
    'scipy', 'pandas', 'matplotlib', 'IPython', 'notebook', 'jupyter',
    'sympy', 'sklearn', 'statsmodels', 'seaborn',
    # Unused network / web frameworks
    'flask', 'django', 'tornado', 'bottle', 'cherrypy', 'fastapi', 'uvicorn',
    'starlette', 'httpx',
    # Unused database
    'sqlite3', 'sqlalchemy', 'psycopg2',
    # Unused image encoders PyInstaller may pull via Pillow
    'PIL.ImageQt',
    # Unused packaging/build tools
    'setuptools', 'pip', 'wheel', 'pkg_resources', 'distutils', 'ensurepip',
    # Misc
    'tkinter.tix', 'lib2to3', 'xmlrpc', 'curses',
    'multiprocessing.popen_spawn_posix',
    'multiprocessing.popen_fork',
    'multiprocessing.popen_forkserver',
]

a = Analysis(
    ['desktop/main.py'],
    pathex=['desktop'],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('assets', 'assets'),
    ],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
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
    name='TouchLink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # UPX corrupts some DLLs — exclude known problematic ones
        'vcruntime140.dll',
        'python3*.dll',
        'libcrypto*.dll',
        'libssl*.dll',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
    version='file_version_info.txt' if __import__('os').path.exists('file_version_info.txt') else None,
)
