"""DxgiCapturer — chụp màn hình bằng DXGI Desktop Duplication qua dxcam.

Ưu điểm so với mss (GDI/BitBlt):
- Chạy ở GPU path, CPU thấp hơn đáng kể.
- Trả về frame ngay khi màn hình thay đổi (event-driven).
- Không bị throttle bởi DWM như GDI.

Phiên bản ghim: dxcam==0.0.5 (xem requirements.txt).
Yêu cầu: Windows 8+, GPU với driver WDDM, không chạy trong session RDP cơ bản.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .base import Frame, Rect

logger = logging.getLogger(__name__)


class DxgiCapturer:
    """Capturer dùng dxcam (DXGI Desktop Duplication API).

    Chạy vòng lặp chụp trong thread nền riêng; thread caller lấy frame
    mới nhất qua grab() mà không chặn.
    """

    name: str = "dxgi"

    # Thời gian tối đa chờ frame đầu tiên (giây).
    _FIRST_FRAME_TIMEOUT: float = 3.0

    def __init__(self) -> None:
        self._camera: Any = None
        self._monitor_idx: int = 1
        self._lock = threading.Lock()
        self._latest_frame: Frame | None = None
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Capturer protocol
    # ------------------------------------------------------------------

    def start(self, monitor: int) -> None:
        """Khởi động camera dxcam và thread chụp nền.

        Args:
            monitor: Index màn hình (1-based theo mss convention;
                     dxcam dùng 0-based → tự chuyển).

        Raises:
            RuntimeError: Khi dxcam không thể tạo camera hoặc không có frame đầu
                (RDP, driver không hỗ trợ, màn hình khóa, hoặc session không có desktop).
        """
        import platform

        if platform.system() != "Windows":
            raise RuntimeError("DXGI Desktop Duplication chỉ hỗ trợ Windows")

        import dxcam  # type: ignore[import-untyped]

        self._monitor_idx = monitor
        device_idx = max(0, monitor - 1)
        try:
            self._camera = dxcam.create(
                device_idx=device_idx,
                output_color="RGB",
            )
            if self._camera is None:
                raise RuntimeError("dxcam.create() trả None")
        except Exception as exc:
            raise RuntimeError(f"dxcam không khởi tạo được: {exc}") from exc

        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="touchlink-dxgi",
        )
        self._started = True
        self._thread.start()

        deadline = time.monotonic() + self._FIRST_FRAME_TIMEOUT
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest_frame is not None:
                    logger.info("DxgiCapturer sẵn sàng (monitor=%d)", monitor)
                    return
            time.sleep(0.05)

        raise RuntimeError(
            f"DxgiCapturer: không có frame đầu sau {self._FIRST_FRAME_TIMEOUT:.1f}s (RDP/driver/session không hợp lệ)"
        )

    def grab(self) -> Frame | None:
        """Trả về frame mới nhất hoặc None nếu chưa có."""
        with self._lock:
            return self._latest_frame

    def dirty_rects(self) -> list[Rect]:
        """dxcam không expose dirty-rect API; tile engine sẽ so hash."""
        return []

    def stop(self) -> None:
        """Dừng thread chụp và giải phóng camera."""
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            self._camera = None
        self._started = False
        logger.debug("DxgiCapturer.stop")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Vòng lặp chụp chạy trong thread nền.

        Dùng dxcam.grab() (non-blocking snapshot) để kiểm soát FPS ở tầng
        stream_loop thay vì để dxcam tự giới hạn FPS.
        """
        cam = self._camera
        if cam is None:
            return
        try:
            cam.start(target_fps=60, video_mode=True)
        except Exception as exc:
            logger.error("dxcam.start() lỗi: %s", exc)
            return

        while not self._stop_evt.is_set():
            try:
                arr = cam.get_latest_frame()
                if arr is None:
                    time.sleep(0.005)
                    continue
                # arr là numpy ndarray RGB shape (H, W, 3)
                h, w = arr.shape[:2]
                frame = Frame(
                    data=arr,
                    width=w,
                    height=h,
                    # dxcam không trả tọa độ màn hình; để tầng factory điền
                    mon_left=0,
                    mon_top=0,
                    mon_width=w,
                    mon_height=h,
                )
                with self._lock:
                    self._latest_frame = frame
            except Exception as exc:
                logger.warning("DxgiCapturer._capture_loop lỗi: %s", exc)
                time.sleep(0.1)

        try:
            cam.stop()
        except Exception:
            pass
