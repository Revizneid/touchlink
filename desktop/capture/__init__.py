"""Package capture — backend chụp màn hình cho TouchLink agent.

Import tương thích ngược::

    from capture import grab_jpeg, list_monitors   # vẫn hoạt động
    from capture import make_capturer               # API mới
"""
from .factory import make_capturer, list_monitors, grab_jpeg
from .base import Capturer, Frame, Rect
from .tile_engine import TileEngine, scale_frame, TILE_SIZE_DEFAULT

__all__ = [
    "make_capturer",
    "list_monitors",
    "grab_jpeg",
    "Capturer",
    "Frame",
    "Rect",
    "TileEngine",
    "scale_frame",
    "TILE_SIZE_DEFAULT",
]
