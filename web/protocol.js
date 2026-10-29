/* TouchLink — hằng số giao thức (mirror của desktop/protocol.py).
 * ES2020 module; import bằng: import { PROTOCOL_VERSION, CAPS } from './protocol.js'
 * Hoặc nạp trực tiếp qua <script type="module"> nếu cần.
 */

/** Phiên bản giao thức hiện tại, gửi trong hello handshake. */
export const PROTOCOL_VERSION = 2;

/** Tính năng PWA hỗ trợ, gửi trong hello.caps. */
export const CAPS = [
  'screen_locked',   // nhận thông báo trạng thái khóa màn hình
  'keep_awake',      // điều khiển ngăn máy tính sleep
  'multi_monitor',   // chọn màn hình trong đa giám sát
  'clipboard_sync',  // đồng bộ clipboard 2 chiều tự động
  'chat',            // chat dạng text
  'e2e-v1',          // mã hóa đầu-cuối trên relay
];

/** Mili giây chờ tối đa hello từ bên kia; quá hạn → v1 mode. */
export const HELLO_TIMEOUT_MS = 5000;
