# TouchLink — Điều khiển máy tính từ điện thoại (kiểu UltraViewer)

**Đã triển khai trực tuyến:**

| Thành phần | Địa chỉ |
|---|---|
| 📱 Mobile web (PWA) | **https://touchlink.vercel.app** |
| 🌐 Relay server (miễn phí, Render) | **https://touchlink-relay.onrender.com** (WebSocket: `wss://touchlink-relay.onrender.com/ws`) |
| 💾 Mã nguồn | https://github.com/Revizneid/touchlink |

**Cách dùng nhanh:** mở `https://touchlink.vercel.app` trên điện thoại → chọn **🌐 Qua relay** →
nhập ID + mật khẩu từ app trên máy tính → Kết nối. Trên máy tính bật relay:
`python desktop/main.py --relay --relay-url wss://touchlink-relay.onrender.com/ws`
(hoặc nhập trong cửa sổ app). Chế độ **🏠 Trực tiếp (LAN)** dùng khi mở trang do chính
máy tính phục vụ (`http://<IP-máy-tính>:8420`).

TouchLink gồm 2 phần:

- **Desktop app** (Python, chạy trên Windows): chụp màn hình, cho phép điều khiển
  chuột/bàn phím từ xa, kèm cửa sổ hiển thị **Mã máy (ID) + Mật khẩu + mã QR** như UltraViewer.
- **Mobile app** (mobile web / PWA): mở trên trình duyệt điện thoại Android (hoặc
  "Thêm vào Màn hình chính" để dùng như app), xem màn hình và điều khiển.

Hai chế độ kết nối:

1. **LAN (cùng Wi-Fi)** — điện thoại mở địa chỉ `http://<IP-máy-tính>:8420`, không cần server trung gian.
2. **Qua internet** — dùng **relay server** (kèm trong dự án, deploy lên VPS):
   điện thoại chỉ cần nhập ID + mật khẩu, không cần biết IP máy tính (giống UltraViewer).

---

## Tính năng

- Xem màn hình trực tiếp (MJPEG qua WebSocket, 3–30 fps, chỉnh chất lượng/độ phân giải/tỉa mỗi màn hình)
- Điều khiển chuột: chạm = click, giữ lâu = chuột phải, kéo = kéo chuột; hoặc chế độ **Touchpad**
- Bàn phím tiếng Việt (Unicode/IME), phím tắt: Ctrl/Alt/Shift/Win dính (sticky), Alt+Tab,
  Win+D/E/L, Task Manager, media (âm lượng, play/pause…)
- Cuộn dọc/ngang (2 ngón hoặc dải cuộn bên phải), thu phóng/kéo khung nhìn bằng pinch
- Đồng bộ clipboard 2 chiều, chat với người ngồi máy tính
- Bảo mật: mật khẩu (lưu mã hóa DPAPI), khóa IP thử sai 5 lần/5 phút, xác thực trên máy tính
  (relay không thấy mật khẩu dưới dạng kiểm chứng được)
- PWA: cài lên màn hình chính Android, chạy fullscreen

## Cài đặt & chạy (máy tính Windows)

```bat
run_desktop.bat
```
(kịch bản tự tạo venv + cài thư viện lần đầu; hoặc tự làm: `python -m venv .venv` rồi
`.venv\Scripts\pip install -r desktop\requirements.txt` rồi `.venv\Scripts\python desktop\main.py`)

Cửa sổ TouchLink hiện ra với:

- **Mã máy (ID)** 9 số và **Mật khẩu** 6 ký tự
- **Mã QR** — quét bằng điện thoại để mở trang điều khiển
- Các nút: tạo mật khẩu mới, sao chép thông tin, cài đặt FPS/chất lượng/màn hình, bật relay

> Lần đầu chạy Windows Firewall hỏi cho phép — chọn **Allow** cho mạng riêng (Private).

### Kết nối từ điện thoại (cùng Wi-Fi)

1. Mở trình duyệt điện thoại, quét QR hoặc nhập `http://<IP-máy-tính>:8420/?id=<mã máy>`
2. Nhập **ID** + **Mật khẩu** → **Kết nối**
3. (Tùy chọn) Menu Chrome → *Thêm vào Màn hình chính* để dùng như app

### Kết nối qua internet (relay)

Trên VPS (Ubuntu/Debian, có Python 3.10+):

```bash
pip install aiohttp
python3 relay_server.py --port 8430        # hoặc dùng run_relay.bat trên Windows
```

Mở cổng 8430/TCP. Trên app máy tính: nhập `Relay URL` = `ws://<IP-VPS>:8430/ws`, tick **Bật**, nhấn
*Áp dụng relay*. Trên điện thoại: mở `http://<IP-VPS>:8430/`, chỉ cần nhập **ID + mật khẩu**.

**Khuyến nghị bảo mật khi chạy relay công khai:** đặt sau reverse proxy có TLS
(Caddy: `touchlink.example.com { reverse_proxy 127.0.0.1:8430 }`) rồi dùng URL
`https://…` (WebSocket tự chuyển wss). Mật khẩu được chuyển về máy tính để xác minh,
relay chỉ ghép cặp theo ID.

## Dòng lệnh (desktop)

```
python desktop/main.py --help
  --headless            chạy không cửa sổ (in ID/mật khẩu ra console)
  --safe-test           KHÔNG điều khiển chuột/phím thật (kiểm thử an toàn)
  --port 8420           đổi cổng HTTP/WebSocket
  --password ABC123     đặt mật khẩu
  --fps 15 --quality 60 --scale 100 --monitor 1
  --relay --relay-url ws://host:8430/ws
  --reset               sinh lại ID + mật khẩu
```

Cấu hình lưu tại `desktop/config.json` (mật khẩu mã hóa DPAPI theo user Windows).

## Cách dùng màn hình điện thoại

- **Chế độ Trực tiếp**: chạm = click tại điểm chạm; giữ ~0.5s = chuột phải; kéo = kéo chuột.
- **Chế độ Touchpad** (nút 🖱): vuốt = di chuột; chạm = click; chạm nhanh 2 lần = double click;
  chạm-giữ rồi kéo = kéo thả; giữ lâu = chuột phải.
- **2 ngón**: vuốt = cuộn; pinch = thu phóng; khi đã phóng to, kéo 2 ngón = di khung nhìn
  (đổi trong Cài đặt → "Hai ngón khi đã thu phóng").
- **⌨**: mở bàn phím điện thoại (gõ tiếng Việt bình thường, hỗ trợ IME/Telex/VNI/Gboard).
- **⊞**: thanh phím tắt — Ctrl/Alt/Shift/Win kiểu "dính", Alt+Tab, Win+D/E/L, Task Manager,
  media key. *Lưu ý: Windows không cho gửi Ctrl+Alt+Del từ tiến trình người dùng — dùng
  "Task Mgr" (Ctrl+Shift+Esc) thay thế.*
- **⋯**: chất lượng ảnh, FPS, độ phân giải, chọn màn hình (đa giám sát), clipboard, chat,
  toàn màn hình, kết nối lại.
- **Dải cuộn** bên phải màn hình: vuốt để cuộn nhanh.

## Kiến trúc

```
┌─ Điện thoại (PWA: web/index.html + app.js) ─┐        ┌─ Relay server (relay/relay_server.py) ─┐
│  canvas vẽ frame JPEG   ◄──  binary frames  │◄──────►│  ghép cặp theo device_id, chỉ đọc     │
│  pointer → chuột        ──► JSON events     │        │  đường ống WS, không xác minh MK      │
└──────────────┬──────────────────────────────┘        └───────────────────▲───────────────────┘
               │ ws://IP:8420/ws (LAN)                                     │ ws outbound
               ▼                                                           │
┌─ Desktop app (desktop/*.py, aiohttp) ───────────────────────────────────┴──────────────────┐
│  server.py (HTTP+WS) / relay_client.py →  core.py (clients, settings, handlers, stream)   │
│  capture.py: mss + Pillow → JPEG     input_control.py: pyautogui + SendInput Unicode      │
│  secure.py: DPAPI  auth.py: rate-limit   main.py: GUI tkinter (ID/MK/QR/log/cài đặt)      │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

**Giao thức:** frame nhị phân = `0x01 | w(uint16) | h(uint16) | JPEG`. JSON: `auth/auth_ok/auth_fail`,
`input{kind: mouse|key|text}`, `settings`, `clipboard_get/clipboard_set/clipboard`, `chat`, `ping/pong`,
`clients`. Relay: `register` (agent) / `connect` (viewer) / `auth→auth_result` / `viewer_msg` / `agent_msg`.

## Giới hạn đã biết

- **Ctrl+Alt+Del / UAC / màn hình khóa**: Windows chặn gửi từ tiến trình người dùng; không xem
  được màn hình khóa/UAC (đặc điểm chung của các app remote cùng cấp quyền).
- Stream dạng JPEG: mượt cho văn bản/quản trị; chơi game/video tốc độ cao không phải mục tiêu.
- Chỉ chạy một viewer qua relay tại một thời điểm (máy đang có người xem thì người khác bị từ chối);
  trong LAN cho phép nhiều viewer cùng lúc.
- PWA/service worker chỉ đăng ký trên `localhost` hoặc HTTPS (LAN dùng HTTP vẫn cài được shortcut).

## Bảo mật

- Chỉ người có ID + mật khẩu mới kết nối được; sai 5 lần trong 5 phút → khóa IP 3 phút.
- Mật khẩu lưu mã hóa DPAPI trong `config.json`; không gửi kèm URL/QR.
- Không có cơ chế ẩn mình/khởi động cùng Windows — app hiện cửa sổ rõ ràng khi đang chạy
  (đúng mục đích hỗ trợ từ xa chính đáng).
- Khi cho ra internet: bật relay trên VPS riêng + TLS, đặt mật khẩu mạnh (nút tạo mật khẩu).

## License

MIT — dùng cho mục đích hợp pháp, có sự đồng ý của chủ máy tính.
