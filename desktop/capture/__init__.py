"""Package capture — backend chụp màn hình cho TouchLink agent.

Import tương thích ngược::

    from capture import grab_jpeg, list_monitors   # vẫn hoạt động
    from capture import make_capturer               # API mới
"""
from .base import Capturer, Frame, Rect
from .factory import grab_jpeg, list_monitors, make_capturer
from .tile_engine import TILE_SIZE_DEFAULT, TileEngine, scale_frame

__all__ = [
    "TILE_SIZE_DEFAULT",
    "Capturer",
    "Frame",
    "Rect",
    "TileEngine",
    "grab_jpeg",
    "list_monitors",
    "make_capturer",
    "scale_frame",
]
