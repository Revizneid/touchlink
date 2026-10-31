"""Factory: tự động chọn DXGI → MSS fallback.

Logic:
1. Thử khởi tạo DxgiCapturer.
2. Nếu thất bại (RDP, driver cũ, session khác, màn hình khóa) → dùng MssCapturer.
3. Ghi lý do fallback vào logger.
"""
from __future__ import annotations

import logging

from .base import Capturer
from .mss_capturer import MssCapturer, grab_jpeg, list_monitors

logger = logging.getLogger(__name__)

# Re-export cho code khác import từ capture.factory
__all__ = ["grab_jpeg", "list_monitors", "make_capturer"]


def make_capturer(prefer_dxgi: bool = True) -> Capturer:
    """Tạo capturer tốt nhất hiện có.

    Args:
        prefer_dxgi: Nếu True (mặc định) sẽ thử DXGI trước.

    Returns:
        DxgiCapturer hoặc MssCapturer.
    """
    if prefer_dxgi:
        try:
            import dxcam  # noqa: F401 — kiểm tra thư viện có sẵn không

            from .dxgi_capturer import DxgiCapturer
            cap = DxgiCapturer()
            logger.info("Capturer: DXGI Desktop Duplication (dxcam)")
            return cap
        except ImportError:
            logger.info(
                "dxcam chưa cài đặt → fallback MssCapturer. "
                "Cài bằng: pip install dxcam==0.0.5"
            )
        except Exception as exc:
            logger.warning(
                "DxgiCapturer không khởi tạo được (%s) → fallback MssCapturer", exc
            )

    cap = MssCapturer()
    logger.info("Capturer: mss (GDI/BitBlt fallback)")
    return cap
