"""Kiểu dữ liệu và Protocol dùng chung cho mọi capturer.

Không import bất kỳ thư viện capture cụ thể nào tại đây.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class Rect:
    """Vùng chữ nhật (pixel-space của frame sau khi scale)."""

    x: int
    y: int
    w: int
    h: int

    def union(self, other: "Rect") -> "Rect":
        """Gộp hai rect thành rect bao ngoài."""
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.w, other.x + other.w)
        y2 = max(self.y + self.h, other.y + other.h)
        return Rect(x1, y1, x2 - x1, y2 - y1)


@dataclass
class Frame:
    """Một khung ảnh đã chụp.

    Attributes:
        data: Mảng numpy RGBA/RGB hoặc bytes thô (tuỳ capturer).
        width: Chiều rộng frame (pixel).
        height: Chiều cao frame (pixel).
        mon_left: Tọa độ trái màn hình (toàn bộ desktop ảo).
        mon_top: Tọa độ trên màn hình.
        mon_width: Chiều rộng vật lý màn hình.
        mon_height: Chiều cao vật lý màn hình.
    """

    data: object          # numpy ndarray hoặc bytes
    width: int
    height: int
    mon_left: int = 0
    mon_top: int = 0
    mon_width: int = 0
    mon_height: int = 0


@runtime_checkable
class Capturer(Protocol):
    """Giao diện chung cho mọi backend chụp màn hình."""

    name: str

    def start(self, monitor: int) -> None:
        """Khởi động capturer, chuẩn bị chụp màn hình ``monitor``.

        Args:
            monitor: Index màn hình (0 = toàn bộ desktop ảo, 1..n = từng màn hình).
        """
        ...

    def grab(self) -> Frame | None:
        """Chụp một frame. Trả về None nếu chưa có dữ liệu.

        Hàm này được gọi từ thread riêng — không chặn event-loop.
        """
        ...

    def dirty_rects(self) -> list[Rect]:
        """Trả về danh sách vùng thay đổi so với frame trước.

        - Trả về list rỗng nếu không có vùng nào thay đổi hoặc backend
          không hỗ trợ (caller sẽ so sánh tile bằng hash).
        - Trả về None nếu cần keyframe (toàn bộ màn hình).
        """
        ...

    def stop(self) -> None:
        """Dừng capturer, giải phóng tài nguyên."""
        ...
