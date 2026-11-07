"""Pytest test session configuration.

Ensure COM threading mode compatibility between dxcam and soundcard on Windows:
dxcam uses comtypes (STA), while soundcard initializes COM for WASAPI. Pre-importing
dxcam before tests execute ensures COM is initialized in a mode compatible with both.
"""

from __future__ import annotations

import sys

try:
    import dxcam  # noqa: F401
except Exception:
    pass

