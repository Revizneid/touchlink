"""Giữ máy tính không tự sleep / tắt màn hình trong khi TouchLink chạy.

Dùng Windows API SetThreadExecutionState từ MỘT thread riêng lâu dài
(API này có hiệu lực theo thread khi dùng cờ ES_CONTINUOUS), tự khẳng
định lại mỗi 60 giây phòng khi app khác xóa trạng thái.

Bật  = không sleep + không tắt màn hình (người xem từ xa cần thấy màn hình)
Tắt  = trả về hành vi tiết kiệm điện bình thường của Windows
"""
import ctypes
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

try:
    ctypes.windll.kernel32.SetThreadExecutionState
    _WIN = True
except Exception:
    _WIN = False


class AwakeKeeper:
    def __init__(self):
        self._enabled = False
        self._cv = threading.Condition()
        self._ok = None  # True/False = kết quả API lần gọi cuối, None = chưa gọi
        if _WIN:
            threading.Thread(target=self._run, daemon=True,
                             name="touchlink-awake").start()

    def _run(self):
        k32 = ctypes.windll.kernel32
        while True:
            with self._cv:
                self._cv.wait(timeout=60)
                enable = self._enabled
            flags = ES_CONTINUOUS
            if enable:
                flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            try:
                prev = k32.SetThreadExecutionState(flags)
                self._ok = bool(prev)  # trả 0 = thất bại
            except Exception:
                self._ok = False

    def set(self, enabled: bool):
        with self._cv:
            self._enabled = bool(enabled)
            self._cv.notify_all()

    @property
    def last_ok(self):
        return self._ok


keeper = AwakeKeeper()


def set_awake(enabled: bool):
    """Bật/tắt chế độ giữ máy thức (an toàn gọi từ mọi thread, mọi nền tảng)."""
    keeper.set(enabled)
