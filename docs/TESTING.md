# docs/TESTING.md — Kịch bản kiểm thử TouchLink

## 1. Kiểm thử tự động (pytest)

```bash
# Từ thư mục gốc dự án:
pip install pytest pytest-asyncio
pytest tests/ -v --tb=short
```

Kết quả mong đợi: tất cả test xanh (không có FAILED/ERROR).  
CI tự động chạy trên `windows-latest` qua `.github/workflows/test.yml` khi push/PR.

---

## 2. Kiểm thử thủ công — Hello Handshake v1/v2

### 2.1 Agent v2 + PWA v2 (kịch bản chính)

**Mục đích:** xác nhận hello trao đổi hai chiều thành công.

**Thiết lập:**
1. Chạy agent: `python desktop/main.py --safe-test`
2. Mở DevTools → Console trên PWA (hoặc chạy local: `http://localhost:8420`)
3. Kết nối thành công

**Kiểm tra:**
- [ ] Console agent in: `Viewer hello: v=2 caps=[…]`
- [ ] Trong DevTools → `window.__tl.connected` trả về `true`
- [ ] `window.st.peerV` bằng `2`, `window.st.peerCaps` là mảng có phần tử

**Lệnh DevTools:**
```javascript
// Gõ trong console PWA sau khi kết nối
window.__tl.connected;  // expected: true
```

---

### 2.2 Agent v2 + PWA v1 (giả lập — PWA không gửi hello)

**Mục đích:** agent phải timeout 5 giây và tiếp tục hoạt động (v1 mode).

**Thiết lập:**
1. Tạm thời comment dòng `ws.send(JSON.stringify({ type: 'hello', ... }))` trong `app.js`
2. Kết nối như bình thường

**Kiểm tra:**
- [ ] Sau ~5 giây: agent vẫn gửi frame và nhận input
- [ ] Console agent KHÔNG có dòng "Viewer hello"
- [ ] Stream màn hình chạy bình thường

**Khôi phục:** bỏ comment và reload.

---

### 2.3 Agent v1 (giả lập — không gửi hello) + PWA v2

**Mục đích:** PWA gửi hello nhưng agent bỏ qua → hoạt động bình thường.

**Thiết lập:**
1. Tạm comment khối `hello handshake` trong `server.py` (sau `auth_ok`)
2. Chạy lại agent, kết nối PWA

**Kiểm tra:**
- [ ] `window.st.peerV` vẫn bằng `1` (mặc định — không nhận được hello)
- [ ] Stream và input hoạt động bình thường
- [ ] Không có lỗi gì trong DevTools

**Khôi phục:** bỏ comment và restart agent.

---

## 3. Kiểm thử thủ công — Màn hình khóa

> ⚠ **Yêu cầu:** máy tính thật chạy Windows, quyền Admin để cài service.

### 3.1 Không cài TouchLinkSvc

1. Đảm bảo service chưa được cài: `sc query TouchLinkSvc` → `The specified service does not exist`
2. Kết nối PWA vào agent đang chạy
3. Khóa màn hình Windows: `Win + L`

**Kiểm tra:**
- [ ] PWA hiện toast: *"Máy tính đang KHÓA — chưa cài service nên không xem/điều khiển được"*
- [ ] Canvas không hiện ảnh mới (frame dừng hoặc màu đen)
- [ ] Mở khóa máy tính bình thường từ bàn phím vật lý: stream tiếp tục

### 3.2 Đã cài TouchLinkSvc

1. Cài service: chạy `install_service.bat` với quyền Admin
2. Xác nhận: `sc query TouchLinkSvc` → `STATE: 4 RUNNING`
3. Kết nối PWA, khóa màn hình: `Win + L`

**Kiểm tra:**
- [ ] PWA hiện toast: *"Màn hình máy tính đang khóa — đang điều khiển QUA SERVICE"*
- [ ] Canvas hiển thị màn hình đăng nhập Winlogon
- [ ] Gõ mật khẩu Windows từ bàn phím PWA → máy tính mở khóa

### 3.3 UAC Secure Desktop (giới hạn đã biết)

1. Khi đã cài service, kích hoạt UAC (ví dụ: chạy `regedit.exe` từ Start)
2. **Kết quả mong đợi (giới hạn):** Canvas có thể đóng băng hoặc không thấy hộp thoại UAC
3. Ghi nhận hành vi thực tế vào issue tracker nếu khác mong đợi

---

## 4. Chế độ --safe-test (không điều khiển thật)

```bash
python desktop/main.py --safe-test
```

**Kiểm tra:**
- [ ] Console in: `TouchLink core sẵn sàng (safe_test=True)`
- [ ] PWA hiện toast: *"⚠ SAFE-TEST: thao tác không được thực thi thật"*
- [ ] Click/kéo trên PWA: agent nhận event nhưng KHÔNG di chuyển chuột vật lý
- [ ] Gõ phím: KHÔNG xuất hiện ký tự trên máy tính
- [ ] Clipboard lấy về: nhận chuỗi `"[safe-test] clipboard bị tắt khi kiểm thử"`

### 4.1 Kiểm thử input backend — Sprint 1.2

**Thiết lập:** chạy `python desktop/main.py --safe-test` và mở PWA/DevTools.

**Kịch bản:**
- [ ] Gõ `Xin chào Việt Nam` bằng Telex trong ứng dụng soạn thảo bất kỳ; không có ký tự nào xuất hiện trên máy thật khi `--safe-test`.
- [ ] Gõ `Xin chào Việt Nam` bằng Gboard/IME Windows trên máy thật trong một editor; nếu không ở chế độ safe-test thì phải đúng chữ Việt và không mất dấu.
- [ ] Thử `Alt+Tab`, `Win+D`, cuộn ngang trên touchpad/mouse và quan sát vị trí chỉ được log trong SafeBackend.
- [ ] Kéo thả file hoặc cửa sổ; không có treo phím khi rời khỏi session.

---

## 5. Kiểm thử tương thích backward/forward

### 5.1 PWA mới + Agent cũ (qua relay)

Dùng agent từ release trước (không có hello) với PWA v2:

1. Chạy agent cũ (tải từ Releases)
2. Kết nối PWA v2 qua relay
3. **Mong đợi:** kết nối thành công, stream hoạt động, `window.st.peerV === 1`

### 5.2 PWA cũ + Agent mới (qua relay)

Dùng PWA bằng cách tắt hello trong app.js tạm thời:

1. Comment dòng gửi hello trong `ws.onmessage`
2. Kết nối với agent v2
3. **Mong đợi:** agent timeout 5s → v1 mode, hoạt động bình thường

---

## 6. Kiểm thử giới hạn kích thước message

> Dùng DevTools Console trên PWA để gửi trực tiếp:

```javascript
// Gửi message quá lớn (> 2MiB) → server phải đóng kết nối hoặc bỏ qua
var big = JSON.stringify({ type: 'chat', text: 'x'.repeat(3 * 1024 * 1024) });
window.st.ws.send(big);
// Mong đợi: server đóng WS với code 1009 (message too big) hoặc connection reset
```

---

## 7. Ghi chú

- **Tất cả test thủ công** phải chạy trên môi trường `--safe-test` trừ các kịch bản cần điều khiển thật (mục 3).
- **Ghi log kết quả** vào issue hoặc PR comment khi thực hiện test trước mỗi release.
- Xem thêm: [docs/PROTOCOL.md](PROTOCOL.md) cho chi tiết giao thức.

---

## 8. Kiểm thử thủ công — Relay (Sprint 0.2)

> Yêu cầu: relay đang chạy (local hoặc VPS). Dùng `websocat`, `wscat`, hoặc script Python.

### 8.1 Gửi 30 lần connect liên tiếp → bị chặn

```bash
# Cài websocat: https://github.com/vi/websocat/releases
# Gửi 30 lần connect cùng IP trong 1 phút (ngưỡng mặc định --max-conn-id 10):
for i in $(seq 1 30); do
  echo '{"type":"connect","device_id":"234567892","password":"x"}' \
    | websocat ws://localhost:8430/ws --one-message
done
```

**Mong đợi:**
- [ ] Lần 1–3 (ID không tồn tại): `{"type":"auth_result","ok":false,"message":"Máy tính không khả dụng"}`
- [ ] Lần 11 trở đi (vượt ngưỡng IP): `message` chứa "thử lại" hoặc "yêu cầu" (khác unavailable)

Trên Windows dùng script Python:
```python
import asyncio, websockets, json

async def test_rate_limit():
    for i in range(30):
        async with websockets.connect("ws://localhost:8430/ws") as ws:
            await ws.send(json.dumps({
                "type": "connect", "device_id": "234567892", "password": "x"
            }))
            msg = json.loads(await ws.recv())
            print(f"#{i+1}: {msg.get('message')}")

asyncio.run(test_rate_limit())
```

### 8.2 Phản hồi ID sai và ID offline không phân biệt được

```bash
# Terminal 1: agent đăng ký rồi ngắt (ID offline)
echo '{"type":"register","device_id":"234567893"}' | websocat ws://localhost:8430/ws --one-message

# Terminal 2: so sánh response
echo '{"type":"connect","device_id":"999999999","password":"x"}' | websocat ws://localhost:8430/ws --one-message
# → "Máy tính không khả dụng"

echo '{"type":"connect","device_id":"234567893","password":"x"}' | websocat ws://localhost:8430/ws --one-message
# → cũng "Máy tính không khả dụng" (cùng message, không phân biệt offline vs không tồn tại)
```

**Mong đợi:** cả hai message PHẢI giống hệt nhau.

### 8.3 Kiểm tra /healthz và /metrics

```bash
# healthz
curl http://localhost:8430/healthz
# → {"status":"ok","app":"touchlink-relay"}

# metrics (không có token)
curl http://localhost:8430/metrics
# → {"total_connections":...,"rejected":...}

# metrics với token
curl -H "Authorization: Bearer your-token" http://localhost:8430/metrics

# metrics token sai → 401
curl -H "Authorization: Bearer wrong" http://localhost:8430/metrics
# → HTTP 401
```

### 8.4 JSON quá lớn → server đóng kết nối

```python
import asyncio, websockets

async def test_large():
    async with websockets.connect("ws://localhost:8430/ws") as ws:
        big = '{"type":"ping","data":"' + 'x' * 70_000 + '"}'
        await ws.send(big)
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print("Recv:", msg[:100])
        except Exception as e:
            print("Closed/Error:", e)

asyncio.run(test_large())
```

**Mong đợi:** WebSocket bị đóng (code 1009) hoặc nhận được close frame.

### 8.5 Log có cấu trúc JSON Lines

```bash
python3 relay/relay_server.py --port 8430 2>&1 | head -20
# Mỗi dòng phải là JSON hợp lệ:
# {"t":"2026-...","level":"INFO","msg":"ws_connect","ip":"1.2.3.4"}
# Không được thấy: password, frame content, keystroke
```

**Kiểm tra:**
- [ ] Mỗi dòng log parse được bằng `json.loads()`
- [ ] Không có trường "password" hay "data" chứa nội dung nhạy cảm
- [ ] Với `--anonymize-logs`: IP hiện dạng `1.2.3.x` (không có octet cuối)

---

## 9. Sprint 0.3 — Relay đánh thức, Overlay, Consent

### 9.1 PWA đánh thức relay đang ngủ (Render free tier)

**Mục đích:** xác nhận UX đếm giây + retry backoff hiển thị đúng.

**Thiết lập:**
1. Dùng relay Render free: `wss://touchlink-relay.onrender.com/ws`
2. Đợi relay ngủ (không dùng ≥ 15 phút)
3. Mở PWA → chọn **Qua relay** → nhập ID + mật khẩu → Kết nối

**Kiểm tra:**
- [ ] Sau **3 giây**: thanh vàng gradient xuất hiện ở đầu trang:
  `⏳ Đang đánh thức máy chủ relay… (Xs)`
- [ ] Đồng hồ tăng dần mỗi giây
- [ ] Khi relay tỉnh dậy (thường 20–60s): thanh biến mất, kết nối thành công
- [ ] Nút **Hủy** ẩn thanh và hiện thông báo "Đã hủy kết nối relay."
- [ ] Nếu relay không phản hồi sau 5 lần retry (1+2+4+8+15=30s chờ):
  hiện "Không kết nối được relay sau 5 lần thử. Kiểm tra URL relay."

**Lệnh mô phỏng relay không phản hồi:**
```javascript
// DevTools Console — giả lập WS không bao giờ mở
var _origWS = WebSocket;
WebSocket = function(url) {
  var ws = new _origWS(url);
  ws.onopen = null; // block onopen
  return ws;
};
```

---

### 9.2 Relay client tự kết nối lại với backoff

**Mục đích:** agent tự retry khi relay mất kết nối, trạng thái GUI cập nhật đúng.

**Thiết lập:**
1. Chạy `python desktop/main.py --relay --relay-url wss://localhost:9999/ws --safe-test`
   (URL không tồn tại → lỗi ngay)
2. Quan sát dashboard

**Kiểm tra:**
- [ ] Badge "Relay internet": `Đang nối` (vàng)
- [ ] Sau khi fail: `Thử lại` (vàng) + log "Relay: thử lại sau Xs"
- [ ] Khoảng cách giữa các lần thử tăng dần (backoff + jitter)
- [ ] Badge không bao giờ treo ở trạng thái sai

---

### 9.3 Overlay đang-bị-điều-khiển

**Mục đích:** overlay xuất hiện/ẩn đúng lúc, không lấy focus.

**Thiết lập:**
1. Chạy `python desktop/main.py --safe-test`
2. Mở PWA → kết nối thành công

**Kiểm tra:**
- [ ] Thanh overlay cam xuất hiện ở góc trên phải màn hình
- [ ] Hiển thị: `🔴 TouchLink: đang được điều khiển từ <IP che bớt>  [Ngắt kết nối]`
- [ ] Thanh **không** lấy focus (có thể gõ bình thường vào cửa sổ khác)
- [ ] Nhấn **Ngắt kết nối**: overlay ẩn, PWA hiện "Mất kết nối"
- [ ] Khi viewer ngắt từ phía PWA: overlay tự ẩn trong ≤1s
- [ ] Kết nối lại: overlay hiện lại với đúng tên viewer

**Kiểm tra IP được che:**
- [ ] IP trong overlay không hiện octet cuối (dạng `1.2.3.x` thay vì `1.2.3.4`)

---

### 9.4 Hotkey khẩn cấp Ctrl+Alt+Shift+F12

**Mục đích:** phím nóng ngắt viewer ngay cả khi app không focus.

**Thiết lập:**
1. Kết nối PWA thành công → overlay đang hiện
2. Chuyển sang cửa sổ khác (Word, trình duyệt...)
3. Nhấn **Ctrl+Alt+Shift+F12**

**Kiểm tra:**
- [ ] Overlay ẩn ngay lập tức
- [ ] PWA hiện thông báo "Mất kết nối với máy tính."
- [ ] Log agent: `Overlay: hotkey Ctrl+Alt+Shift+F12 — ngắt toàn bộ viewer`
- [ ] Sau khi ngắt, agent vẫn chạy bình thường (có thể kết nối lại)

---

### 9.5 Hộp thoại xác nhận kết nối (consent)

**Mục đích:** hộp thoại hiện đúng, các nút hoạt động, timeout tự từ chối.

**Thiết lập:**
1. Mở **Cài đặt → Xác nhận kết nối** → bật "Yêu cầu xác nhận cho kết nối qua relay" → Lưu
2. Thử kết nối từ PWA qua relay

**Kịch bản A — Cho phép:**
- [ ] Hộp thoại xuất hiện trên máy tính trước khi viewer thấy màn hình
- [ ] Nhấn **✓ Cho phép**: viewer thấy màn hình và điều khiển được
- [ ] Overlay xuất hiện ngay sau khi cho phép

**Kịch bản B — Từ chối:**
- [ ] Nhấn **✗ Từ chối**: PWA nhận thông báo "Người dùng từ chối kết nối"
- [ ] Overlay không xuất hiện

**Kịch bản C — Timeout 30 giây:**
- [ ] Không nhấn gì — đếm ngược chạy từ 30 về 0
- [ ] Sau 30s: hộp thoại tự đóng, viewer bị từ chối
- [ ] Log: `Consent: 'viewer_ip' → deny`

**Kịch bản D — Chỉ xem (view_only):**
- [ ] Nhấn **👁 Chỉ xem**: viewer thấy màn hình nhưng input bị bỏ qua

---

### 9.6 Headless mode — cảnh báo console + hotkey

**Mục đích:** headless không có overlay GUI nhưng vẫn cảnh báo và hotkey hoạt động.

```bash
python desktop/main.py --headless --safe-test --relay --relay-url wss://...
```

**Kiểm tra:**
- [ ] Khi khởi động in: `[Headless] ⚠ Overlay không hiện khi chạy --headless.`
- [ ] Khi có viewer kết nối in: `⚠ CẢNH BÁO: đang có 1 viewer điều khiển máy tính này!`
- [ ] Khi viewer ngắt in: `· viewers: 0`
- [ ] Nhấn **Ctrl+Alt+Shift+F12**: viewer bị ngắt (log xuất hiện trong console)
- [ ] Consent headless: không hiện hộp thoại, tự từ chối (log: `Consent: headless mode → tự động từ chối`)

---

### 9.7 Kiểm tra deploy/ artifacts

**Kiểm tra file có đúng cú pháp:**

```bash
# Dockerfile
docker build -f deploy/Dockerfile -t touchlink-relay . --no-cache --dry-run 2>&1 | head -5
# Nếu không có Docker: kiểm tra syntax thủ công

# fly.toml — cần flyctl
fly config validate --config deploy/fly.toml

# DEPLOY_RELAY.md tồn tại và có đủ 4 mục
ls docs/DEPLOY_RELAY.md && grep -c "^##" docs/DEPLOY_RELAY.md
# → 7 (7 mục heading)
```

**Kiểm tra:**
- [ ] `deploy/Dockerfile` build được (hoặc cú pháp đúng)
- [ ] `deploy/fly.toml` có `auto_stop_machines = false` và `min_machines_running = 1`
- [ ] `docs/DEPLOY_RELAY.md` có bảng so sánh 4 tùy chọn hosting
