# TouchLink v3.0.0 — Điều khiển máy tính từ điện thoại (kiểu UltraViewer)

> **Tác giả / Credit:** [Revizneid](https://github.com/Revizneid) — mã nguồn mở MIT.
> Xây dựng trên các thư viện mở: Python, aiohttp, mss, Pillow, pyautogui, qrcode, pyperclip.

Giao diện desktop v2.0: **control center** tối màu navy/blue chuyên nghiệp — sidebar
điều hướng (Điều khiển từ xa · Màn hình chờ · Lịch sử kết nối · Danh sách thiết bị ·
Cài đặt), dashboard với ID/mật khẩu/QR/trạng thái realtime, nhật ký hoạt động có màu
theo sự kiện. Mobile web dùng chung hệ màu để đồng nhất nhận diện.

**Đã triển khai trực tuyến:**

| Thành phần | Địa chỉ |
|---|---|
| 📱 Mobile web (PWA) | **https://touchlink.vercel.app** |
| 🌐 Relay server (miễn phí, Render) | **https://touchlink-relay.onrender.com** (WebSocket: `wss://touchlink-relay.onrender.com/ws`) |
| 💾 Mã nguồn | https://github.com/Revizneid/touchlink |
| 📦 **Portable exe (Windows)** | https://github.com/Revizneid/touchlink/releases — tải `TouchLink-Portable-win64.zip`, giải nén, chạy `TouchLink.exe` (không cần cài Python) |

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
- **Ngăn máy tính tự sleep** (SetThreadExecutionState, bật/tắt được từ GUI và web)
- **Mở khóa từ xa** (cơ chế UltraViewer/TeamViewer): cài `TouchLinkSvc` (service SYSTEM,
  1 lần duy nhất) — khi màn hình Windows khóa, app tự chuyển sang đường service:
  xem màn hình đăng nhập và gõ mật khẩu Windows để mở khóa
- Stream thích ứng: mỗi viewer có mailbox "frame mới nhất" — mạng yếu bỏ frame cũ,
  không chặn người xem khác hay vòng chụp màn hình
- Bảo mật: mật khẩu (lưu mã hóa DPAPI), khóa IP thử sai 5 lần/5 phút, xác thực trên máy tính
  (relay không thấy mật khẩu dưới dạng kiểm chứng được)
- PWA: cài lên màn hình chính Android, chạy fullscreen; đăng nhập bằng phím Enter
- **Overlay đang-bị-điều-khiển** (Sprint 0.3): thanh nhỏ luôn nổi góc trên màn hình
  hiện tên viewer (IP che bớt) + nút "Ngắt kết nối" khi có ≥1 viewer đã xác thực;
  phím nóng khẩn cấp **Ctrl+Alt+Shift+F12** ngắt tất cả viewer ngay lập tức;
  headless: in cảnh báo console, không có cửa sổ
- **Xác nhận kết nối mới** (Sprint 0.3): hộp thoại Cho phép / Chỉ xem / Từ chối,
  timeout 30 giây → tự từ chối; mặc định BẬT cho relay, TẮT cho LAN
  (cấu hình trong Cài đặt → Xác nhận kết nối)
- **Relay không ngủ** (Sprint 0.3): hướng dẫn deploy lên Fly.io / VPS / Oracle Free;
  PWA tự đánh thức relay (đếm giây + retry backoff 1→2→4→8→15s) khi relay đang ngủ (Render free)
- **Relay client tự kết nối lại** (Sprint 0.3): backoff + jitter tự động, trạng thái
  realtime (Đang kết nối / Đã kết nối / Thử lại / Lỗi) hiển thị trên dashboard

**Mở khóa từ xa hoạt động thế nào:** UltraViewer/TeamViewer đều dùng một Windows
service chạy quyền SYSTEM. TouchLink tương tự: `TouchLinkSvc` gắn vào window
station WinSta0 + desktop nhập liệu hiện hành (khi khóa là Winlogon) để chụp màn
hình đăng nhập và gửi chuột/bàn phím vào đó. App chính phát hiện khóa (mỗi 2 giây)
và tự chuyển đường capture/input qua service qua named pipe nội bộ; mở máy thì
tự quay về đường trực tiếp (nhanh hơn). Cài: trong app → **Cài đặt → Cài service
(cần Admin)** hoặc chạy `install_service.bat`; gỡ: `uninstall_service.bat`.

## Cài đặt & chạy (máy tính Windows)

**Cách 1 — portable exe (khuyên dùng, không cần cài gì):**
tải `TouchLink-Portable-win64.zip` từ [Releases](https://github.com/Revizneid/touchlink/releases),
giải nén và chạy `TouchLink.exe`. File `config.json` tự tạo **cạnh exe** (portable — xóa là
sinh lại ID/mật khẩu mới). Lần đầu Windows Firewall hỏi → chọn Allow (mạng Private).

**Cách 2 — chạy từ mã nguồn:**

```bat
run_desktop.bat
```
(kịch bản tự tạo venv + cài thư viện lần đầu; hoặc tự làm: `python -m venv .venv` rồi
`.venv\Scripts\pip install -r desktop\requirements.txt` rồi `.venv\Scripts\python desktop\main.py`)

**Tự build exe:** sửa code xong, chạy `build_exe.bat` (dùng PyInstaller) → `dist\TouchLink.exe`.
Thư mục `web/` được bundle vào exe; icon `assets/icon.ico`.

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

## Cấu hình relay công khai

Relay hỗ trợ cấu hình qua **tham số CLI** hoặc **biến môi trường** (CLI ưu tiên):

```bash
python3 relay/relay_server.py \
  --port 8430 \
  --trusted-proxy \
  --anonymize-logs \
  --metrics-token "your-secret-token" \
  --max-conns-ip 20 \
  --max-conn-id 10 \
  --max-conn-total 30 \
  --max-auth-fail 5 \
  --auth-ban-s 180 \
  --max-conns-total-ip 10
```

| Tham số CLI | Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|---|
| `--trusted-proxy` | `RELAY_TRUSTED_PROXY=1` | tắt | Tin tưởng `X-Forwarded-For` (chỉ bật sau nginx/Caddy) |
| `--anonymize-logs` | `RELAY_ANONYMIZE_LOGS=1` | tắt | Ẩn octet cuối IP trong log |
| `--metrics-token TOKEN` | `RELAY_METRICS_TOKEN` | trống | Token bảo vệ `/metrics` |
| `--max-conns-ip N` | `RELAY_MAX_CONNS_IP` | 20 | Kết nối WS mới tối đa/phút/IP |
| `--max-conn-id N` | `RELAY_MAX_CONN_ID` | 10 | Lần `connect` tới một ID/phút/IP |
| `--max-conn-total N` | `RELAY_MAX_CONN_TOTAL` | 30 | Lần `connect` tới một ID/phút/ID |
| `--max-auth-fail N` | `RELAY_MAX_AUTH_FAIL` | 5 | Auth fail tối đa trước khi khoá |
| `--auth-ban-s N` | `RELAY_AUTH_BAN_S` | 180 | Giây khoá sau khi vượt ngưỡng |
| `--max-conns-total-ip N` | `RELAY_MAX_CONNS_TOTAL` | 10 | Kết nối đồng thời tối đa/IP |
| `PORT` (env) | `PORT` | 8430 | Cổng lắng nghe (Render/Heroku) |

**Endpoint giám sát:**

| Endpoint | Mô tả |
|---|---|
| `GET /healthz` | Kiểm tra relay sống (không lộ ID) |
| `GET /metrics` | Số kết nối, từ chối, auth fail (bảo vệ bằng Bearer token nếu có) |
| `GET /api/relayinfo` | Số agent online/bận (không lộ device_id cụ thể) |

**Bảo mật relay (Sprint 0.2):** sliding-window rate-limit theo IP và ID, chống dò ID
(tất cả lỗi connect trả cùng message + jitter delay 50–150ms), log JSON Lines
(không log mật khẩu, phím, nội dung frame).

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

- **Không cài `TouchLinkSvc`**: không xem được màn hình khóa (Windows Logon), không gõ
  mật khẩu đăng nhập từ xa được (giống mọi app remote cùng cấp quyền người dùng).
- **Có cài `TouchLinkSvc`**: có thể xem và gửi các phím (kể cả mật khẩu Windows) vào màn
  hình đăng nhập Winlogon. **Không hỗ trợ UAC Secure Desktop** (hộp thoại UAC chạy trên
  WinSta0\Winlogon ring-0, khác với màn hình khóa thông thường).
- Stream dạng JPEG: mượt cho văn bản/quản trị; chơi game/video tốc độ cao không phải mục tiêu.
- Chỉ chạy một viewer qua relay tại một thời điểm (máy đang có người xem thì người khác bị từ chối);
  trong LAN cho phép nhiều viewer cùng lúc.
- PWA/service worker chỉ đăng ký trên `localhost` hoặc HTTPS.
- **Headless + overlay**: khi chạy `--headless`, cửa sổ overlay không xuất hiện —
  thay vào đó in cảnh báo console `⚠ CẢnh BÁO: đang có N viewer…`.
  Hotkey Ctrl+Alt+Shift+F12 vẫn hoạt động trong headless.
- **Relay ngủ (Render free)**: PWA tự retry với backoff đến 30s tổng; thanh vàng đếm giây
  xuất hiện sau 3s chờ, nút Hủy để hủy kết nối.

## Sprint 0.3 — Độ tin cậy relay & overlay an toàn

### Deploy relay không ngủ

Xem hướng dẫn đầy đủ tại [`docs/DEPLOY_RELAY.md`](docs/DEPLOY_RELAY.md).

| Tùy chọn | Chi phí | Relay ngủ? |
|---|---|---|
| **VPS (Hetzner/DO/Vultr)** | ~$4–6/tháng | Không |
| **Fly.io** | ~$0–2/tháng | **Không** (cấu hình `auto_stop=false`) |
| **Oracle Cloud Free** | **Miễn phí vĩnh viễn** | Không |
| Render free tier | $0 | ⚠ Có — ngủ sau 15 phút |

Triển khai Fly.io nhanh:
```bash
cp relay/relay_server.py deploy/relay_server.py
fly launch --no-deploy --config deploy/fly.toml
fly secrets set RELAY_METRICS_TOKEN="$(openssl rand -hex 32)"
fly deploy --config deploy/fly.toml
```

### Overlay đang-bị-điều-khiển

- Khi có ≥1 viewer xác thực: thanh cam nhỏ luôn nổi góc trên phải màn hình:
  `TouchLink: đang được điều khiển từ <IP che bớt> • [Ngắt kết nối]`
- Nút **Ngắt kết nối**: đóng tất cả viewer ngay lập tức
- Phím nóng khẩn cấp: **Ctrl+Alt+Shift+F12** (RegisterHotKey, hoạt động cả khi app không focus)
- `--headless`: không có overlay; in `⚠ CẢnh BÁO` ra console khi có viewer kết nối
- **Không có cơ chế ẩn overlay** (by design)

### Xác nhận kết nối mới (consent)

Khi bật trong Cài đặt → Xác nhận kết nối:
- Hộp thoại Cho phép / Chỉ xem / Từ chối hiện khi có viewer mới muốn kết nối
- Timeout 30 giây → tự động từ chối
- Mặc định: BẬT cho relay, TẮT cho LAN
- `--headless`: luôn từ chối (không thể hiện dialog)

### PWA đánh thức relay

- Relay mode: nếu WS mở > 3s chưa phản hồi → hiện thanh vàng "Đang đánh thức…" + đếm giây
- Retry backoff: 1 → 2 → 4 → 8 → 15s (tổng 5 lần thử)
- Nút Hủy kết nối ngay lập tức
- Sau 5 lần thất bại: hiện thông báo lỗi rõ ràng


## Bảo mật

- Chỉ người có ID + mật khẩu mới kết nối được; sai 5 lần trong 5 phút → khóa IP 3 phút
  (cả ở agent — chế độ LAN — lẫn relay — chế độ internet).
- Mật khẩu lưu mã hóa DPAPI trong `config.json`; không gửi kèm URL/QR.
- **Mô hình xác minh:** **agent (máy tính) xác minh mật khẩu** — relay chỉ chuyển tiếp
  plaintext password từ viewer về agent rồi agent gọi `verify_password()` để kiểm tra
  (DPAPI hash); relay không biết mật khẩu đúng/sai.
- **E2E trên relay (Sprint 2.2):** khi cả hai bên hỗ trợ `e2e-v1`, session sẽ dùng X25519 ephemeral
  + Ed25519 identity signature + HKDF-SHA256 để sinh khóa, rồi AES-256-GCM mã hóa từng message.
  Relay chỉ thấy ciphertext; replay / out-of-order nonce bị từ chối; 1 bit thay đổi làm giải mã thất bại.
- **Mã dùng một lần:** mặc định 10 ký tự, bảng chữ không mơ hồ, thời hạn 10 phút, đổi sau khi dùng.
  Chế độ mật khẩu cố định chỉ cho LAN và phải bật thủ công kèm cảnh báo rõ ràng.
- **Relay rate-limit (Sprint 0.2):** sliding-window giới hạn kết nối mới và số lần connect
  theo IP và ID; chống dò ID — tất cả lỗi connect trả cùng message + jitter delay 50–150ms;
  log JSON Lines không ghi mật khẩu, phím, frame.
- **Cảnh báo bảo mật:** relay công cộng vẫn là tầng trung gian, nhưng với `e2e-v1` nó không thể đọc nội dung
  payload mà chỉ chuyển tiếp ciphertext. Nếu `require_e2e` bật trên relay, mọi kết nối không hỗ trợ E2E sẽ bị từ chối.
- Không có cơ chế ẩn mình/khởi động cùng Windows — app hiện cửa sổ rõ ràng khi đang chạy.
- Khi cho ra internet: bật relay trên VPS riêng + TLS, đặt mật khẩu mạnh (nút tạo mật khẩu).

## License

MIT — dùng cho mục đích hợp pháp, có sự đồng ý của chủ máy tính.
