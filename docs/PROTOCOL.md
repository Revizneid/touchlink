# TouchLink — Đặc tả giao thức (Protocol Specification)

> **Trạng thái:** v2 — áp dụng từ Sprint 0.1.  
> Giao thức v1 (không có hello) vẫn được hỗ trợ (backward-compatible).

---

## Tổng quan

TouchLink dùng WebSocket (WS/WSS) cho tất cả kênh truyền thông.  
Dữ liệu truyền theo hai dạng:

| Dạng | Mô tả |
|---|---|
| **Binary frame** | Header 5 byte + JPEG — truyền ảnh màn hình |
| **JSON text** | Mọi lệnh điều khiển, xác thực, cài đặt |

---

## 1. Kết nối trực tiếp (LAN)

```
Điện thoại (PWA) ──WS──► Desktop app (aiohttp, cổng 8420)
```

### 1.1 Handshake xác thực

```
Viewer →  { "type": "auth", "id": "<device_id>", "password": "<mật khẩu>" }
Agent  →  { "type": "auth_ok", "device_id": "…", "hostname": "…",
            "version": "2.3.0", "settings": {…}, "monitors": […],
            "screen_locked": false, "svc_ok": false, "safe_test": false }
Agent  →  { "type": "hello", "v": 2, "caps": ["screen_locked", "keep_awake", …] }
Viewer →  { "type": "hello", "v": 2, "caps": ["screen_locked", "keep_awake", …] }
```

- Sai ID/mật khẩu: `{ "type": "auth_fail", "message": "…" }`
- Sai 5 lần trong 5 phút → IP bị khóa 3 phút.

### 1.2 Handshake phiên bản (hello)

Sau `auth_ok`, **agent gửi** `hello` và **chờ** `hello` ngược từ viewer (timeout 5 giây).  
Nếu viewer không gửi hello → agent chạy **v1 mode** (tương thích ngược hoàn toàn).

```jsonc
// Cấu trúc hello
{
  "type": "hello",
  "v":    2,                    // int — phiên bản giao thức (bắt buộc)
  "caps": ["screen_locked", …]  // list[str] — tính năng hỗ trợ (có thể rỗng)
}
```

**Quy tắc xử lý trường lạ:** bên nhận **bỏ qua** mọi trường ngoài `type`/`v`/`caps`.  
**Thiếu `"v"`:** coi như v1.

---

## 2. Kết nối qua relay (internet)

```
Điện thoại (PWA) ──WSS──► Relay server (port 8430) ──WS──► Desktop app
```

Relay **chỉ chuyển tiếp** — không lưu trữ, không xác minh mật khẩu.

> ⚠️ **Cảnh báo bảo mật (hiện tại):** Relay có thể đọc mật khẩu và nội dung
> truyền qua (bao gồm frame màn hình và lệnh điều khiển) vì chưa có mã hóa
> đầu-cuối (E2E). Dự kiến bổ sung E2E ở Giai đoạn 2–3.  
> **Khuyến nghị:** tự vận hành relay sau reverse proxy TLS (`wss://`), không
> dùng relay công cộng cho thông tin nhạy cảm.

### 2.1 Tin nhắn relay (agent → relay)

| `type` | Ý nghĩa |
|---|---|
| `register` | Đăng ký mã máy: `{ "type": "register", "device_id": "123456789" }` |
| `auth_result` | Trả kết quả xác thực: `{ "type": "auth_result", "ok": true\|false, "data": {…} }` |
| `agent_msg` | Gói JSON trả về viewer: `{ "type": "agent_msg", "data": {…} }` |
| `unbind` | Ngắt phiên viewer hiện tại |

### 2.2 Tin nhắn relay (viewer → relay)

| `type` | Ý nghĩa |
|---|---|
| `connect` | Kết nối tới agent: `{ "type": "connect", "device_id": "…", "password": "…" }` |
| `viewer_msg` | Gói JSON gửi tới agent: `{ "type": "viewer_msg", "data": {…} }` |

### 2.3 Tin nhắn relay (relay → viewer hoặc agent)

| `type` | Ý nghĩa |
|---|---|
| `registered` | Xác nhận đăng ký thành công (→ agent) |
| `auth_result` | Kết quả xác thực (→ viewer): `{ "ok": true\|false, "data": {…}, "message": "…" }` |
| `bound` | Thông báo đã ghép cặp (→ agent) |
| `auth` | Chuyển yêu cầu xác thực (→ agent): `{ "type": "auth", "password": "…" }` |
| `viewer_msg` | Chuyển message từ viewer (→ agent) |
| `agent_msg` | Chuyển message từ agent (→ viewer) |
| `unbind` | Phiên bị ngắt |
| `error` | Thông báo lỗi: `{ "type": "error", "message": "…" }` |

### 2.4 Hello handshake qua relay

Sau `auth_result { ok: true }`, agent gửi hello trực tiếp tới viewer qua kênh relay:

```
Agent  →  relay  →  Viewer : { "type": "agent_msg", "data": { "type": "hello", "v": 2, "caps": […] } }
Viewer →  relay  →  Agent  : { "type": "viewer_msg", "data": { "type": "hello", "v": 2, "caps": […] } }
```

Relay chuyển tiếp nguyên vẹn, không xử lý nội dung hello.

---

## 3. Định dạng binary frame (ảnh màn hình)

```
┌─────────┬──────────┬──────────┬──────────────────┐
│ 0x01    │ w uint16 │ h uint16 │ JPEG data…       │
│ 1 byte  │ 2 bytes  │ 2 bytes  │ n bytes          │
└─────────┴──────────┴──────────┴──────────────────┘
Byte order: big-endian (network order)
```

- `0x01`: magic byte (frame type = 1)
- `w`, `h`: kích thước frame JPEG tính bằng pixel
- `JPEG data`: ảnh JPEG sau nén (chất lượng 20–95%, có thể scale)
- Giới hạn kích thước: 8 MiB / frame (server từ chối frame vượt ngưỡng)

---

## 4. Tin nhắn JSON (sau xác thực)

### 4.1 Điều khiển chuột

```jsonc
{
  "type": "input",
  "kind": "mouse",
  "action": "move"|"down"|"up"|"click"|"scroll",
  "x": 1920,          // pixel tuyệt đối trong tọa độ frame (null nếu touchpad rel)
  "y": 1080,
  "button": "left"|"right"|"middle",  // mặc định "left"
  "clicks": 1,        // số lần click (double click = 2)
  "amount": 3,        // bước cuộn dọc (dương = lên)
  "hamount": 0,       // bước cuộn ngang
  "rel": [dx, dy]     // di chuyển tương đối (touchpad mode, thay thế x/y)
}
```

### 4.2 Điều khiển bàn phím

```jsonc
{
  "type": "input",
  "kind": "key",
  "key":  "enter"|"backspace"|"tab"|"escape"|"arrowup"|…|"f1"…"f12",
  "mods": ["ctrl", "alt", "shift", "win"]  // tập con tuỳ ý
}
```

### 4.3 Gõ văn bản Unicode

```jsonc
{ "type": "input", "kind": "text", "text": "Tiếng Việt 🎉" }
```

Giới hạn: 2000 ký tự / message.

### 4.4 Cài đặt stream

```jsonc
// Viewer → Agent
{ "type": "settings", "settings": { "fps": 15, "quality": 70, "scale": 80, "monitor": 2,
                                     "clipboard_sync": true, "keep_awake": true } }
// Agent → Tất cả viewer (broadcast sau khi áp dụng)
{ "type": "settings", "settings": { … } }
```

Giới hạn: `fps` 2–30, `quality` 20–95, `scale` 30–100.

### 4.5 Clipboard

```jsonc
// Lấy clipboard từ máy tính
{ "type": "clipboard_get" }
// Đẩy clipboard lên máy tính
{ "type": "clipboard_set", "text": "nội dung" }
// Máy tính gửi clipboard tới mọi viewer (broadcast)
{ "type": "clipboard", "text": "nội dung" }
```

### 4.6 Chat

```jsonc
// Viewer → Agent
{ "type": "chat", "text": "Xin chào" }  // tối đa 500 ký tự
// Agent → Tất cả viewer (broadcast)
{ "type": "chat", "from": "Relay viewer", "text": "Xin chào" }
```

### 4.7 Ping / Pong

```jsonc
{ "type": "ping", "t": 1700000000000 }  // timestamp ms
{ "type": "pong", "t": 1700000000000 }
```

### 4.8 Trạng thái màn hình khóa

```jsonc
// Agent → Tất cả viewer (broadcast khi trạng thái thay đổi)
{ "type": "screen_locked", "locked": true, "svc": true }
// svc: true nếu TouchLinkSvc đang chạy và có thể xem/điều khiển màn hình khóa
```

### 4.9 Số viewer

```jsonc
// Agent → Tất cả viewer (broadcast khi viewer kết nối/ngắt)
{ "type": "clients", "n": 2 }
```

### 4.10 Pairing bằng QR / Trust Store (Sprint 2.1)

```jsonc
// Viewer → Agent: bắt đầu ghép cặp
{ "type": "pair_request", "device_id": "123456789", "device_name": "Pixel 9",
  "public_key": "base64-raw-32-byte-ed25519-public-key",
  "relay_url": "wss://relay.example/ws",
  "pairing_secret": "hex-128-bit-secret",
  "nonce": "random-128-bit-nonce" }

// Agent → Viewer: yêu cầu chấp thuận và gửi nonce để đối chiếu SAS
{ "type": "pair_challenge", "device_id": "123456789", "nonce": "random-128-bit-nonce",
  "agent_pubkey": "base64-agent-public-key", "sas": "123456" }

// Viewer → Agent: xác nhận SAS + proof
{ "type": "pair_confirm", "device_id": "123456789", "nonce": "random-128-bit-nonce",
  "proof": "base64-signature-of-nonce", "accept": true }

// Sau khi ghép cặp: challenge/response xác thực thiết bị tin cậy
{ "type": "auth_key", "challenge": "hex-random-32-byte", "signature": "base64-ed25519-signature" }
```

- `pairing_secret` là ngẫu nhiên 128-bit, sống 2 phút, dùng một lần.
- `sas` là mã xác nhận 6 chữ số (ứng với SHA-256 của 2 public key + nonce).
- `pair_confirm` chỉ được chấp nhận khi `proof` khớp `nonce` và `sas` khớp ở cả hai phía.
- Agent lưu `trust store` dưới dạng JSON mã hóa DPAPI với `{ device_id, device_name, public_key_b64, created_at, last_seen, permission, expires_at, revoked }`.
- Caps mới: `"pairing-v1"`.

---

## 5. Quy tắc tương thích

| Tình huống | Hành vi |
|---|---|
| Agent v2 + Viewer v1 (không gửi hello) | Agent timeout 5s → v1 mode, hoạt động bình thường |
| Agent v1 (không gửi hello) + Viewer v2 | Viewer gửi hello, agent bỏ qua (type lạ), hoạt động bình thường |
| Agent v2 + Viewer v2 | Cả hai trao đổi hello, ghi nhận caps chung |
| Trường lạ trong bất kỳ message | Bên nhận bỏ qua |
| Thiếu trường `"v"` trong hello | Coi như v1 |

---

## 6. Giới hạn kích thước message

| Loại | Giới hạn |
|---|---|
| JSON message (LAN WS) | 2 MiB |
| Binary frame (relay WS) | 8 MiB |
| Văn bản gõ (`text`) | 2 000 ký tự |
| Chat | 500 ký tự |
| Clipboard broadcast | 20 000 ký tự |

---

## 7. Mô hình xác minh mật khẩu

```
Viewer → [password] → Relay → [password] → Agent → verify_password() → OK/Fail
```

**Agent xác minh** bằng `secure.verify_password()` (DPAPI-encrypted hash).  
Relay chỉ chuyển tiếp plaintext password — **không hash, không lưu trữ**.  
Mật khẩu không bao giờ đi kèm URL/QR code và không ghi vào log.

---

## 8. Lịch sử phiên bản

| Phiên bản | Thay đổi |
|---|---|
| **v1** (implicit) | Giao thức gốc — không có hello handshake |
| **v2** (Sprint 0.1) | Thêm `hello { v, caps }` sau auth; tương thích ngược hoàn toàn với v1 |
