"""Hằng số giao thức TouchLink dùng chung cho agent (desktop).

Phiên bản giao thức độc lập với phiên bản ứng dụng — chỉ tăng khi
định dạng wire-format thay đổi không tương thích ngược.
"""

PROTOCOL_VERSION: int = 2
"""Phiên bản giao thức hiện tại gửi trong hello handshake."""

CAPS: list[str] = [
    "screen_locked",   # thông báo trạng thái khóa màn hình
    "keep_awake",      # điều khiển ngăn máy tính sleep
    "multi_monitor",   # chọn màn hình trong đa giám sát
    "clipboard_sync",  # đồng bộ clipboard 2 chiều tự động
    "chat",            # chat dạng text
    "safe_test",       # chế độ không điều khiển thật
    "tiles",           # frame nhị phân 0x02 dirty-rect tile (Sprint 1.1)
    "pairing-v1",      # ghép cặp khóa Ed25519, trust store, challenge/response
    "e2e-v1",          # mã hóa đầu-cuối bằng X25519 + HKDF + AES-256-GCM
]
"""Danh sách tính năng agent hỗ trợ — gửi trong hello.caps."""

HELLO_TIMEOUT: float = 5.0
"""Giây chờ tối đa hello từ bên kia sau khi auth_ok; quá hạn → v1 mode."""

MAX_MSG_SIZE: int = 2 * 1024 * 1024   # 2 MiB — giới hạn JSON message
MAX_FRAME_SIZE: int = 8 * 1024 * 1024 # 8 MiB — giới hạn binary frame

# --- Frame type bytes ---
MSG_FRAME_FULL: int = 0x01
"""Frame toàn khung: [type(B=0x01)] [fw(u16)] [fh(u16)] [JPEG...]"""

MSG_FRAME_TILE: int = 0x02
"""Frame tile dirty-rect: [type(B=0x02)] [fw(u16)] [fh(u16)]
[tile_size(u16)] [n_tiles(u16)] per-tile: [tx(u16)] [ty(u16)] [len(u32)] [JPEG...]
"""

