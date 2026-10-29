# TouchLink v2.1 → v3.0 — Báo cáo kế hoạch tổng hợp & Kế hoạch triển khai theo Sprint

> Tài liệu gồm 3 phần: (A) báo cáo tổng hợp, (B) kế hoạch theo giai đoạn, (C) bộ prompt chi tiết theo Sprint để giao cho AI IDE (Cursor, Windsurf, Claude Code, Copilot Agent...).
> Ngày lập: 28/10/2026. Phạm vi: dự án `touchlink` (desktop Python + mobile PWA + relay).

## Mục lục

1. [Báo cáo tổng hợp](#phần-a--báo-cáo-tổng-hợp)
2. [Kế hoạch theo giai đoạn](#phần-b--kế-hoạch-theo-giai-đoạn)
3. [Cách dùng bộ prompt](#phần-c--cách-dùng-bộ-prompt)
4. [Prompt theo Sprint](#phần-d--prompt-theo-sprint)
5. [Phụ lục](#phụ-lục)

---

# Phần A — Báo cáo tổng hợp

## A1. Hiện trạng v2.1

| Khối | Công nghệ | Vai trò |
|---|---|---|
| Desktop agent | Python, aiohttp, mss + Pillow, pyautogui + SendInput, tkinter, DPAPI | Chụp màn hình, nhận lệnh chuột/phím, hiện ID/MK/QR |
| Mobile PWA | HTML/JS, canvas | Vẽ frame JPEG, đổi cử chỉ thành sự kiện chuột/phím |
| Relay | aiohttp WebSocket, host Render free | Ghép cặp theo `device_id` để đi qua NAT |
| TouchLinkSvc (tùy chọn) | Windows service SYSTEM + named pipe | Xem/nhập liệu ở màn hình khóa |

Điểm mạnh: mailbox "frame mới nhất" cho mạng yếu; gõ tiếng Việt Unicode; MK lưu DPAPI; có LAN + relay; có bản portable exe; PWA cài được lên màn hình chính.

## A2. Vấn đề cần giải quyết

### Tài liệu / thiết kế
- **D1.** README mâu thuẫn: "không xem được màn hình khóa" vs. "mở khóa từ xa bằng service".
- **D2.** README mâu thuẫn: relay "không xác minh MK" vs. "MK chuyển về máy tính để xác minh".

### Bảo mật
- **S1.** Frame và phím đi qua relay ở dạng đọc được (kể cả mật khẩu Windows khi mở khóa). TLS chỉ bảo vệ từng chặng, không phải đầu-cuối.
- **S2.** Khóa IP chỉ nằm ở desktop; qua relay nhiều viewer có thể trông như một IP. ID 9 số có thể bị dò.
- **S3.** MK 6 ký tự, dùng lại nhiều phiên → dễ brute-force phân tán.
- **S4.** Service SYSTEM mở named pipe: nếu ACL lỏng, tiến trình thường có thể lợi dụng leo quyền.
- **S5.** Không có xác nhận "cho phép thiết bị này?" và không có chỉ báo luôn nổi khi đang bị điều khiển.

### Hiệu năng / độ tin cậy
- **P1.** Render free ngủ sau ~15 phút → lần kết nối đầu mất 30–60 giây, dễ báo lỗi.
- **P2.** Relay là nút nghẽn băng thông, chỉ 1 viewer.
- **P3.** Gửi JPEG toàn khung mỗi frame, lãng phí khi màn hình ít đổi.
- **P4.** `mss` (GDI) chậm; pyautogui có pause/failsafe gây trễ.

### Phát hành
- **R1.** exe PyInstaller dễ bị Defender/SmartScreen báo nhầm (càng nghi vì có service SYSTEM + điều khiển từ xa).
- **R2.** Chưa có CI, test tự động, ký số, auto-update.

## A3. Mục tiêu v3.0

| Nhóm | Mục tiêu đo được |
|---|---|
| Bảo mật | Relay/TURN không đọc được nội dung (E2E); pairing bằng khóa; MK dùng một lần; 0 lỗi nghiêm trọng trong checklist ở Phụ lục B |
| Độ trễ | LAN ≤ 80 ms; internet P2P ≤ 200 ms (glass-to-glass, đo bằng chỉ báo trong app) |
| Hiệu năng | CPU agent ≤ 15% (màn hình tĩnh ≤ 3%) trên máy văn phòng i5 gen 8; 15–30 fps khi cuộn |
| Băng thông | Màn hình tĩnh < 50 kbps; văn bản cuộn 1–3 Mbps |
| Tin cậy | Kết nối thành công ≥ 95% (P2P + TURN fallback); tự kết nối lại < 10 giây khi mất mạng ngắn |
| Phát hành | Installer ký số; CI tạo Release tự động; tỉ lệ AV báo nhầm giảm (kiểm tra VirusTotal) |

## A4. Kiến trúc mục tiêu

```
Điện thoại (PWA)  ──WebRTC (DTLS-SRTP + DataChannel, E2E)──  Desktop agent
        │                                                        │
        └──── Signaling (WS, chỉ SDP/ICE + xác thực) ───────────┘
                         │
                Relay (signaling) + coturn (TURN, chỉ khi P2P hỏng)

Desktop agent (module hóa):
  transport/  lan_ws, relay_ws, webrtc, jpeg_fallback
  capture/    dxgi (dxcam), mss_fallback, dirty_rect
  encode/     h264 (hw/sw), vp8, jpeg_tiles
  input/      sendinput (ctypes), layout/unicode
  security/   pairing, trust_store, otp, ratelimit, audit
  service/    TouchLinkSvc (SYSTEM, tối giản) + pipe ACL
  ui/         tkinter (ID/MK/QR/overlay/log)
```

Nguyên tắc: (1) an toàn trước tối ưu; (2) giao thức có `version` + `capabilities`; (3) luôn có đường lùi (JPEG/WS) khi WebRTC hỏng; (4) không ẩn mình, mọi kết nối phải hiện rõ trên máy bị điều khiển.

## A5. Mô hình bảo mật mới (tóm tắt)

1. **Pairing QR một lần** → trao đổi khóa công khai Ed25519 (ký) + X25519 (thỏa thuận khóa). Lần sau điện thoại tin cậy xác thực bằng khóa, không cần gõ MK.
2. **MK dùng một lần theo phiên** cho người lạ: 8–10 ký tự (hoặc 3 từ), hết hạn sau N phút, đổi sau mỗi phiên.
3. **Rate-limit ở relay** theo ID/IP/toàn cục; phản hồi giống nhau dù ID có tồn tại hay không.
4. **Xác nhận trên desktop** khi thiết bị mới kết nối; chế độ chỉ xem; thanh overlay luôn nổi + nút ngắt ngay.
5. **Service**: pipe ACL chặt, kiểm tra caller, log mọi lần mở khóa, chỉ bật khi người dùng chủ động.
6. **Audit log** cục bộ (ai, lúc nào, từ đâu, loại thao tác tổng quát — không ghi nội dung phím).
7. **TOTP 2FA** tùy chọn cho truy cập không giám sát.

## A6. Rủi ro chính

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| aiortc encode nặng CPU | Cao | Đo sớm (Sprint 3.1); dùng ffmpeg/NVENC qua PyAV; giữ JPEG fallback |
| Service SYSTEM là bề mặt tấn công lớn | Cao | Tối giản 2 chức năng; ACL; fuzz test pipe; review bảo mật Sprint 2.4 |
| AV báo nhầm | Trung bình | Ký số, Nuitka, nộp mẫu Microsoft, công khai SHA-256 |
| Phạm vi trượt (scope creep) | Trung bình | Mỗi sprint có "Không làm"; Definition of Done bắt buộc |
| Phụ thuộc nền tảng free (Render/Vercel) | Trung bình | Chuyển relay sang host không ngủ ở Sprint 0.3 |
| Lạm dụng công cụ | Cao (đạo đức) | Giữ nguyên nguyên tắc hiển thị rõ; overlay bắt buộc; chỉ dùng khi có sự đồng ý của chủ máy |

## A7. So sánh nhanh để định vị

| Giải pháp | Ghi chú |
|---|---|
| RustDesk | Mã nguồn mở, tự host server, có mobile; mạnh nhưng nặng và không tối ưu PWA |
| Sunshine/Moonlight | Độ trễ rất thấp cho game/video; không phải công cụ quản trị |
| MeshCentral | Quản trị nhiều máy; giao diện web, cấu hình phức tạp |
| **TouchLink** | **PWA nhẹ, tối ưu thao tác cảm ứng + gõ tiếng Việt, tự host đơn giản** → giữ làm điểm khác biệt |

---

# Phần B — Kế hoạch theo giai đoạn

Giả định: 1 lập trình viên + AI IDE, Sprint = 1 tuần. Có thể rút ngắn nếu chạy song song.

| GĐ | Tên | Sprint | Thời gian | Kết quả bàn giao |
|---|---|---|---|---|
| 0 | Dọn nền | 0.1–0.3 | 1 tuần | Tài liệu nhất quán, relay an toàn + không ngủ, protocol versioning, overlay |
| 1 | Hiệu năng | 1.1–1.3 | 2 tuần | DXGI + dirty rect, SendInput trực tiếp, chỉ báo FPS/độ trễ, auto-reconnect |
| 2 | Bảo mật đầu-cuối | 2.1–2.4 | 3 tuần | Pairing QR, MK một lần, xác nhận desktop, audit log, service hardening |
| 3 | WebRTC | 3.1–3.4 | 4 tuần | Signaling, aiortc, H.264, DataChannel, TURN, fallback JPEG |
| 4 | Tính năng | 4.1–4.4 | 4 tuần | Âm thanh, truyền file, đa viewer, macro, WoL, iOS |
| 5 | Phát hành | 5.1–5.3 | 2 tuần | CI/CD, ký số, installer, auto-update, tài liệu v3.0 |

**Thứ tự ưu tiên nếu thiếu thời gian:** GĐ0 → GĐ2 → GĐ1 → GĐ3 → GĐ5 → GĐ4.

**Cổng chất lượng giữa các giai đoạn (Gate):**
- Gate 0: test giao thức xanh, README đã thống nhất, relay có rate-limit.
- Gate 2: checklist bảo mật (Phụ lục B) đạt toàn bộ mục "Bắt buộc".
- Gate 3: benchmark đạt mục tiêu A3 trên máy mục tiêu; fallback JPEG vẫn chạy.
- Gate 5: cài sạch trên Windows 10/11 VM, chạy end-to-end, VirusTotal ghi nhận.

---

# Phần C — Cách dùng bộ prompt

1. Mở repo trong AI IDE. Dán **Prompt nền (Master Context)** bên dưới vào phần Rules/Project Instructions (hoặc đầu mỗi phiên chat).
2. Mỗi Sprint: dán đúng prompt của Sprint, để AI làm theo thứ tự "Kế hoạch → Code → Test → Báo cáo".
3. Sau mỗi Sprint: chạy test, review diff, commit trên nhánh `sprint/x.y-ten`, rồi mới sang Sprint tiếp.
4. Nếu AI đề xuất đi lệch phạm vi, nhắc lại mục **Không làm** của Sprint đó.

## Prompt nền (Master Context)

```text
Bạn là kỹ sư phần mềm cấp cao đang nâng cấp dự án TouchLink (điều khiển máy tính Windows từ điện thoại, mã nguồn mở MIT, mục đích hỗ trợ từ xa hợp pháp có sự đồng ý của chủ máy).

CẤU TRÚC HIỆN TẠI:
- desktop/: main.py (GUI tkinter), server.py (aiohttp HTTP+WS, cổng 8420), relay_client.py, core.py (clients, settings, handlers, stream), capture.py (mss+Pillow→JPEG), input_control.py (pyautogui + SendInput Unicode), secure.py (DPAPI), auth.py (rate-limit)
- web/: index.html + app.js (PWA, canvas vẽ frame JPEG)
- relay/relay_server.py (aiohttp WS, ghép cặp theo device_id)
- TouchLinkSvc: Windows service SYSTEM, named pipe nội bộ
- Giao thức hiện tại: frame nhị phân 0x01|w(u16)|h(u16)|JPEG; JSON: auth/auth_ok/auth_fail, input{kind: mouse|key|text}, settings, clipboard_get/set, chat, ping/pong, clients; relay: register/connect/auth→auth_result/viewer_msg/agent_msg.

QUY TẮC BẮT BUỘC:
1. Python 3.10+, type hints, docstring ngắn, tuân PEP8. JS: ES2020, không framework nặng.
2. Không phá tương thích: agent cũ + PWA mới (và ngược lại) vẫn chạy được thông qua trường "version" và "capabilities".
3. An toàn trước: không log mật khẩu/nội dung phím; không hard-code bí mật; kiểm tra mọi đầu vào từ mạng; giới hạn kích thước message.
4. Không thêm tính năng ẩn mình, tự khởi động ngầm hay che giấu việc đang bị điều khiển. Mọi kết nối phải hiển thị rõ trên máy tính.
5. Mỗi thay đổi đi kèm test (pytest) hoặc kịch bản kiểm thử thủ công ghi rõ trong docs/TESTING.md. Chế độ --safe-test không được điều khiển chuột/phím thật.
6. Commit nhỏ, thông điệp theo Conventional Commits.
7. Chỉ thêm thư viện khi cần, ghi rõ lý do + phiên bản ghim trong requirements.txt.
8. Trước khi code: đọc các file liên quan và tóm tắt kế hoạch (file nào sửa/thêm). Sau khi code: chạy test, liệt kê kết quả, những gì chưa làm, rủi ro còn lại.
9. Nếu yêu cầu mơ hồ: chọn phương án an toàn nhất, ghi giả định vào cuối báo cáo, không hỏi lan man.
```

---

# Phần D — Prompt theo Sprint

Mỗi Sprint gồm: **Mục tiêu · Phụ thuộc · Prompt · Tiêu chí hoàn thành (DoD)**.

---

## GIAI ĐOẠN 0 — DỌN NỀN (1 tuần)

### Sprint 0.1 — Thống nhất tài liệu + protocol versioning

**Mục tiêu:** Hết mâu thuẫn README; giao thức có `version`/`capabilities`; có bộ test giao thức đầu tiên.
**Phụ thuộc:** không.

```text
NHIỆM VỤ: Sprint 0.1 — Thống nhất tài liệu và thêm versioning cho giao thức.

BỐI CẢNH: README hiện mâu thuẫn ở 2 điểm: (1) "không xem được màn hình khóa" vs "mở khóa từ xa bằng TouchLinkSvc"; (2) "relay không xác minh MK" vs "MK chuyển về máy tính xác minh". Giao thức chưa có version.

VIỆC CẦN LÀM:
1. Đọc README.md, desktop/core.py, desktop/server.py, desktop/relay_client.py, relay/relay_server.py, web/app.js. Xác định hành vi THỰC TẾ của code cho 2 điểm mâu thuẫn trên.
2. Sửa README.md cho đúng hành vi thật:
   - Mục "Giới hạn đã biết": ghi rõ "Không cài TouchLinkSvc → không xem được khóa/UAC/Ctrl+Alt+Del; có service → xem và nhập mật khẩu ở màn hình khóa (không hỗ trợ UAC secure desktop nếu code thực tế không hỗ trợ)".
   - Mục kiến trúc/bảo mật: chốt một mô hình xác minh MK (agent xác minh, relay chỉ chuyển tiếp) và nói rõ relay CÓ THỂ thấy dữ liệu truyền qua cho tới khi có mã hóa đầu-cuối (sẽ làm ở Giai đoạn 2–3).
3. Tạo docs/PROTOCOL.md mô tả giao thức hiện tại (binary frame, JSON message, relay message) và giao thức v2: thêm trường "v" (int) và "caps" (list[str]) trong bắt tay. Quy tắc: bên nhận bỏ qua trường lạ; thiếu "v" coi như v1.
4. Cài đặt trong code:
   - Thêm hằng PROTOCOL_VERSION = 2 và CAPS ở một module chung (desktop/protocol.py; web/protocol.js tương ứng).
   - Agent và PWA gửi {"type":"hello","v":2,"caps":[...]} sau khi mở WS; nhận hello của bên kia để chọn tính năng chung. Nếu bên kia không gửi hello → chạy chế độ v1 hiện tại.
   - Relay chuyển tiếp hello nguyên vẹn (không cần hiểu nội dung).
5. Tạo thư mục tests/, thêm pytest + tests/test_protocol.py: parse frame nhị phân, parse JSON hợp lệ/không hợp lệ, hello v1/v2, trường lạ bị bỏ qua, message quá lớn bị từ chối.
6. Thêm .github/workflows/test.yml chạy pytest trên windows-latest.

KHÔNG LÀM: không đổi cơ chế capture/input, không đụng mã hóa, không refactor lớn.

DoD: README nhất quán; docs/PROTOCOL.md đầy đủ; pytest xanh; PWA mới + agent cũ (và ngược lại) vẫn kết nối được (ghi cách kiểm tra thủ công vào docs/TESTING.md).
```

### Sprint 0.2 — Gia cố relay (rate-limit, chống dò ID, giới hạn)

**Mục tiêu:** Relay chống brute-force/dò ID, có giới hạn tài nguyên.
**Phụ thuộc:** 0.1.

```text
NHIỆM VỤ: Sprint 0.2 — Gia cố relay_server.py.

BỐI CẢNH: Relay ghép cặp theo device_id (9 số). Hiện chưa có rate-limit ở relay; qua relay mọi viewer có thể mang cùng IP của proxy; ID có thể bị dò.

VIỆC CẦN LÀM:
1. Lấy IP thật của client: ưu tiên header X-Forwarded-For/Forwarded CHỈ khi cấu hình --trusted-proxy; mặc định dùng peername.
2. Rate-limit (token bucket hoặc sliding window), cấu hình qua CLI/biến môi trường, mặc định:
   - kết nối WS mới: 20/phút/IP
   - thao tác "connect" tới ID: 10/phút/IP và 30/phút/ID
   - auth thất bại: 5 lần/5 phút/(IP,ID) → khóa 3 phút; tổng thất bại toàn cục tăng thì tăng độ trễ (exponential backoff, tối đa 60s)
3. Chống dò ID: khi ID không tồn tại, agent offline, hoặc agent bận → trả CÙNG một lỗi chung ("unavailable") với thời gian phản hồi gần như nhau (thêm jitter 50–150ms).
4. Giới hạn: kích thước message tối đa (JSON 64KB, frame 4MB), số kết nối đồng thời/IP, thời gian chờ ghép cặp (30s), ping/pong định kỳ và đóng kết nối chết.
5. Chỉ chấp nhận agent "register" khi device_id đúng định dạng và chưa bị agent khác giữ (agent mới chỉ thay thế nếu agent cũ đã mất kết nối).
6. Log có cấu trúc (JSON lines): kết nối, từ chối, khóa. KHÔNG log nội dung frame/phím/mật khẩu. Ẩn bớt IP (che octet cuối) nếu có cờ --anonymize-logs.
7. Endpoint /healthz (không lộ danh sách ID) và /metrics tối giản (số kết nối, số bị từ chối) bảo vệ bằng token tùy chọn.
8. Viết tests/test_relay.py (aiohttp test client): vượt rate-limit bị chặn, lỗi chung cho ID sai/offline, message quá lớn bị đóng, thay thế agent.

KHÔNG LÀM: không thêm E2E (Giai đoạn 2), không đổi giao thức ghép cặp.

DoD: tests xanh; thử thủ công: gửi 30 lần connect liên tiếp bị chặn; phản hồi cho ID sai và ID offline không phân biệt được; README có mục "Cấu hình relay công khai".
```

### Sprint 0.3 — Relay không ngủ + "đang đánh thức" + overlay đang-bị-điều-khiển

**Mục tiêu:** Hết lỗi kết nối do Render ngủ; người ngồi máy luôn biết đang bị điều khiển.
**Phụ thuộc:** 0.1.

```text
NHIỆM VỤ: Sprint 0.3 — Độ tin cậy relay và overlay an toàn.

PHẦN A — Relay không ngủ + UX đánh thức:
1. Viết deploy/ gồm: Dockerfile cho relay, fly.toml (Fly.io), hướng dẫn VPS (systemd unit + Caddy TLS), và docs/DEPLOY_RELAY.md so sánh: VPS ~$4–6/tháng, Fly.io, Oracle free tier. Giữ Render làm tùy chọn nhưng ghi rõ giới hạn ngủ.
2. PWA: khi WS mở quá 3 giây chưa phản hồi, hiện "Đang đánh thức máy chủ relay (có thể mất tới 60 giây)…" kèm đếm giây, tự retry với backoff (1,2,4,8,15s) thay vì báo lỗi. Có nút Hủy.
3. Agent (relay_client.py): tự kết nối lại relay với backoff + jitter; hiển thị trạng thái (Đang kết nối / Đã kết nối / Lỗi) trên GUI.

PHẦN B — Overlay đang-bị-điều-khiển (desktop):
1. Khi có ≥1 viewer đã xác thực: hiện thanh overlay nhỏ luôn-nổi (tkinter Toplevel, topmost, không focus) góc trên màn hình: "TouchLink: đang được điều khiển từ <tên thiết bị/IP che bớt> • [Ngắt kết nối]".
2. Nút "Ngắt kết nối" ngắt toàn bộ viewer ngay. Có phím nóng toàn cục Ctrl+Alt+Shift+F12 (đăng ký bằng RegisterHotKey) để ngắt khẩn cấp.
3. Thêm tùy chọn trong Cài đặt: "Yêu cầu xác nhận khi có kết nối mới" (mặc định BẬT cho kết nối qua relay): hiện hộp thoại Cho phép/Từ chối/Chỉ xem, timeout 30s = từ chối.
4. Overlay phải xuất hiện cả khi ứng dụng chạy --headless? Không: ở headless chỉ in cảnh báo console. Ghi rõ trong docs.
5. Tests: logic xác nhận (mock UI) trong tests/test_consent.py.

KHÔNG LÀM: không thêm cơ chế ẩn overlay.

DoD: demo thủ công: relay ngủ → PWA hiện đếm giây rồi kết nối được; overlay hiện/ẩn đúng; phím nóng ngắt viewer; README cập nhật.
```

---

## GIAI ĐOẠN 1 — HIỆU NĂNG (2 tuần)

### Sprint 1.1 — Capture DXGI + dirty rect

**Mục tiêu:** Giảm CPU và băng thông, tăng FPS.
**Phụ thuộc:** Gate 0.

```text
NHIỆM VỤ: Sprint 1.1 — Thay capture bằng DXGI Desktop Duplication, thêm dirty-rect.

VIỆC CẦN LÀM:
1. Tạo desktop/capture/ với giao diện chung:
   class Capturer(Protocol): start(monitor:int), grab() -> Frame|None, dirty_rects() -> list[Rect], stop(), name:str
   Cài đặt: DxgiCapturer (dùng dxcam hoặc thư viện tương đương; ghim phiên bản; chạy trong thread riêng), MssCapturer (giữ code cũ làm fallback).
2. Tự chọn: thử DXGI trước; nếu lỗi (RDP, driver, session khác, màn hình khóa) → fallback mss và ghi log lý do. Hỗ trợ đa màn hình (monitor index), đổi độ phân giải/DPI giữa chừng không crash.
3. Dirty rect + JPEG theo tile:
   - Chia khung thành tile 64x64 hoặc 128x128; so sánh hash nhanh (numpy) với frame trước; chỉ mã hóa tile đổi.
   - Frame nhị phân mới 0x02: header (w,h,tile_size,n_tiles) + danh sách (x,y,len,jpeg). Chỉ gửi khi đối tác khai caps "tiles" trong hello; ngược lại giữ 0x01 toàn khung.
   - Gửi keyframe toàn khung mỗi N giây và khi viewer mới vào hoặc yêu cầu.
   - Màn hình tĩnh: không gửi gì ngoài heartbeat.
4. Giữ cơ chế mailbox "frame mới nhất" cho từng viewer; với tile, khi bỏ frame phải gộp dirty rect (hoặc ép keyframe) để không bị lệch hình.
5. PWA: vẽ tile vào canvas (drawImage từng tile, createImageBitmap), xử lý 0x01 và 0x02.
6. Benchmark: scripts/bench_capture.py in CPU%, FPS, byte/s với 3 kịch bản (tĩnh, cuộn văn bản, phát video 720p). Ghi kết quả vào docs/BENCHMARK.md (trước/sau).
7. Tests: so sánh tile; dirty rect rỗng khi không đổi; fallback khi DXGI ném lỗi (mock).

KHÔNG LÀM: chưa làm H.264/WebRTC; chưa đụng pipe service.

DoD: màn hình tĩnh < 3% CPU và gần 0 băng thông; cuộn văn bản ≥ 15 fps; fallback mss hoạt động; benchmark ghi lại.
```

### Sprint 1.2 — Input trực tiếp bằng SendInput

**Mục tiêu:** Giảm trễ nhập liệu, chính xác bàn phím/Unicode.
**Phụ thuộc:** 0.1.

```text
NHIỆM VỤ: Sprint 1.2 — Viết lại input_control.py dùng ctypes SendInput, bỏ pyautogui.

VIỆC CẦN LÀM:
1. Tạo desktop/input/sendinput.py (ctypes): move (tuyệt đối theo MOUSEEVENTF_ABSOLUTE|VIRTUALDESK, chuẩn hóa 0..65535, hỗ trợ đa màn hình + DPI awareness per-monitor v2), click trái/phải/giữa, down/up, wheel dọc/ngang, key down/up theo scancode (KEYEVENTF_SCANCODE) và Unicode (KEYEVENTF_UNICODE) cho gõ tiếng Việt, cặp surrogate cho ký tự ngoài BMP.
2. Bảng ánh xạ phím từ tên JSON hiện có (ctrl, alt, shift, win, enter, f1…, media keys) sang VK/scancode, kèm cờ KEYEVENTF_EXTENDEDKEY khi cần (mũi tên, Home/End, Insert/Delete, numpad enter).
3. Cơ chế "dính" (sticky) cho Ctrl/Alt/Shift/Win giữ nguyên; thêm bộ theo dõi phím đang giữ và KHI viewer ngắt kết nối thì nhả toàn bộ phím/nút chuột đang giữ (tránh kẹt phím).
4. Hàng đợi sự kiện + gộp mouse-move liên tiếp (chỉ giữ vị trí mới nhất) để giảm trễ; không có sleep/pause cố định.
5. Dán văn bản dài: ưu tiên clipboard + Ctrl+V (khôi phục clipboard cũ) khi > 20 ký tự; ngắn thì gõ Unicode.
6. Giữ chế độ --safe-test: lớp trừu tượng InputBackend có SafeBackend chỉ ghi log. Gỡ pyautogui khỏi requirements nếu không còn dùng.
7. Tests (dùng SafeBackend + mock user32): ánh xạ phím, chuẩn hóa tọa độ đa màn hình, nhả phím khi ngắt kết nối, surrogate pair.
8. Kịch bản kiểm thử thủ công trong docs/TESTING.md: gõ "Xin chào Việt Nam" bằng Telex và Gboard; Alt+Tab; Win+D; cuộn ngang; kéo thả.

KHÔNG LÀM: không cố gửi Ctrl+Alt+Del hay tương tác UAC.

DoD: gõ tiếng Việt đúng; không kẹt phím khi rớt mạng; độ trễ xử lý input trong agent < 10 ms (đo bằng log timestamp); pytest xanh.
```

### Sprint 1.3 — Chỉ báo chất lượng + tự thích ứng + auto-reconnect

**Mục tiêu:** Người dùng thấy rõ FPS/độ trễ; kết nối bền.
**Phụ thuộc:** 1.1.

```text
NHIỆM VỤ: Sprint 1.3 — Telemetry, thích ứng chất lượng, kết nối lại.

VIỆC CẦN LÀM:
1. Đo RTT: PWA gửi ping có timestamp, agent trả pong; tính RTT trung bình trượt. Agent đo fps thực gửi, byte/s, số frame bỏ.
2. PWA: HUD nhỏ bật/tắt (FPS, RTT ms, kbps, độ phân giải, chế độ capture); màu xanh/vàng/đỏ theo ngưỡng.
3. Bộ điều khiển thích ứng ở agent (desktop/adaptive.py): dựa vào RTT, tỉ lệ bỏ frame, kích thước hàng đợi gửi → tự giảm/tăng JPEG quality (30–85), scale (50–100%), fps (5–30). Có histeresis để không dao động; người dùng có thể chọn "Tự động / Cố định".
4. Auto-reconnect trong PWA: khi mất WS, hiện "Mất kết nối — thử lại sau Ns" với backoff + jitter, giữ nguyên trạng thái giao diện (chế độ, zoom); xác thực lại bằng token phiên ngắn hạn (agent cấp resume_token sống 2 phút, dùng một lần) để không phải nhập lại MK.
5. Wake Lock API trên PWA (navigator.wakeLock) khi đang xem; xử lý visibilitychange.
6. Tests: adaptive controller (mô phỏng chuỗi RTT/drop → quyết định), resume_token hết hạn/dùng lại bị từ chối.

KHÔNG LÀM: chưa đổi mã hóa video.

DoD: HUD hiển thị số đúng; rút/cắm Wi-Fi trên điện thoại → tự nối lại < 10s không cần nhập MK; mạng giả lập chậm (clumsy/tc) vẫn dùng được nhờ tự giảm chất lượng.
```

---

## GIAI ĐOẠN 2 — BẢO MẬT ĐẦU-CUỐI (3 tuần)

### Sprint 2.1 — Pairing QR + kho thiết bị tin cậy

**Mục tiêu:** Ghép cặp một lần bằng khóa; lần sau không cần MK.
**Phụ thuộc:** Gate 0.

```text
NHIỆM VỤ: Sprint 2.1 — Pairing bằng QR và Trust Store.

THIẾT KẾ:
- Mỗi agent có cặp khóa định danh Ed25519 (lưu DPAPI trong config). Mỗi điện thoại tạo cặp khóa Ed25519 bằng WebCrypto (lưu IndexedDB, extractable=false nếu trình duyệt hỗ trợ; nếu không thì ghi cảnh báo).
- QR pairing chứa: device_id, fingerprint (SHA-256) khóa công khai agent, pairing_secret ngẫu nhiên 128-bit sống 2 phút dùng một lần, URL relay. KHÔNG chứa MK.
- Luồng: điện thoại quét QR → kết nối → gửi pubkey điện thoại + chứng minh biết pairing_secret (HMAC trên nonce) → agent hiện hộp thoại "Ghép cặp thiết bị <tên>? Mã xác nhận: 123-456" (SAS 6 số tính từ hai pubkey + nonce, hiển thị trên cả hai bên để người dùng đối chiếu) → đồng ý → lưu pubkey vào trust store.
- Lần sau: điện thoại tin cậy kết nối bằng thử thách–đáp ứng (agent gửi nonce, điện thoại ký bằng khóa riêng) → không cần MK.

VIỆC CẦN LÀM:
1. desktop/security/pairing.py, trust_store.py (JSON mã hóa DPAPI: id thiết bị, tên, pubkey, thời điểm ghép/lần cuối, quyền: control|view_only, hạn tùy chọn).
2. Thông điệp mới trong docs/PROTOCOL.md: pair_request, pair_challenge, pair_confirm, auth_key (challenge/response). Caps: "pairing-v1".
3. PWA: màn hình quét/nhập mã ghép cặp (dùng BarcodeDetector nếu có, ngược lại nhập tay), tạo/lưu khóa, danh sách "Máy đã ghép".
4. GUI desktop: tab "Thiết bị tin cậy": xem, đổi quyền (điều khiển/chỉ xem), thu hồi ngay (và ngắt phiên đang chạy).
5. Rate-limit pairing (3 lần sai → hủy pairing_secret).
6. Tests: pairing đúng/sai secret, secret hết hạn/dùng lại, SAS khớp hai phía, thu hồi, chữ ký sai bị từ chối, replay nonce bị từ chối.

KHÔNG LÀM: chưa mã hóa luồng dữ liệu (Sprint 2.2), chưa bỏ đường MK cũ.

DoD: ghép cặp thành công qua LAN và relay; kết nối lại không cần MK; thu hồi có hiệu lực tức thì; pytest xanh.
```

### Sprint 2.2 — Mã hóa đầu-cuối qua relay + MK một lần

**Mục tiêu:** Relay không đọc được nội dung; MK mạnh, dùng một lần.
**Phụ thuộc:** 2.1.

```text
NHIỆM VỤ: Sprint 2.2 — E2E encryption cho đường relay (giải pháp tạm trước WebRTC) và MK dùng một lần.

VIỆC CẦN LÀM:
1. Kênh mật mã giữa viewer và agent chạy BÊN TRONG đường ống relay:
   - Thỏa thuận khóa: X25519 ephemeral + chữ ký Ed25519 của agent (và của viewer nếu đã ghép cặp) lên transcript; dẫn xuất khóa bằng HKDF-SHA256 (hai khóa theo hai chiều).
   - Mã hóa từng message: AES-256-GCM hoặc ChaCha20-Poly1305, nonce đếm tăng dần theo chiều, từ chối nonce lặp/lùi (chống replay), giới hạn kích thước.
   - Python: thư viện cryptography. Web: WebCrypto (X25519 có thể cần fallback tweetnacl/noble-curves bản vendored, ghim phiên bản + SRI).
   - Với MK (người lạ chưa ghép cặp): dùng PAKE (SPAKE2 hoặc OPAQUE-lite; nếu quá nặng thì dùng X25519 + HMAC(MK, transcript) và ghi rõ giới hạn trong docs) để relay không học được MK và không brute-force offline được dễ dàng.
2. Hiển thị mã xác thực (fingerprint ngắn) trên overlay agent để người dùng đối chiếu khi cần.
3. MK dùng một lần theo phiên: mặc định 10 ký tự (bảng chữ bỏ ký tự dễ nhầm 0/O/1/l), hạn 10 phút, đổi sau khi dùng; tùy chọn "mã 3 từ". Nút "Tạo mã mới" giữ nguyên. Chế độ "MK cố định" chỉ cho LAN và phải bật thủ công kèm cảnh báo.
4. Caps: "e2e-v1". Nếu hai bên đều hỗ trợ thì BẮT BUỘC dùng; có cờ cấu hình "Chỉ chấp nhận E2E" (mặc định bật cho relay).
5. Relay không cần đổi logic, chỉ chuyển tiếp byte; cập nhật test để xác nhận relay nhìn thấy toàn ciphertext (test_relay_sees_only_ciphertext).
6. Tests: vector mã hóa, replay, sửa 1 bit → giải mã thất bại, MITM giả (chữ ký sai) bị từ chối, MK sai.
7. Cập nhật README + docs/SECURITY.md (mô hình mối đe dọa: relay độc hại, kẻ nghe lén, kẻ dò MK, thiết bị bị mất).

KHÔNG LÀM: không tự chế thuật toán; chỉ dùng primitive chuẩn của thư viện.

DoD: bắt gói tại relay chỉ thấy dữ liệu mã hóa; kết nối bằng MK sai/replay thất bại; hiệu năng giảm < 10% so với trước.
```

### Sprint 2.3 — Xác nhận desktop, chế độ chỉ xem, audit log, TOTP

**Mục tiêu:** Kiểm soát và truy vết.
**Phụ thuộc:** 2.1.

```text
NHIỆM VỤ: Sprint 2.3 — Consent, view-only, audit log, TOTP.

VIỆC CẦN LÀM:
1. Chính sách kết nối (desktop/security/policy.py): với mỗi lần kết nối quyết định theo (đã ghép cặp?, nguồn LAN/relay?, có người ngồi máy không?). Mặc định: thiết bị tin cậy qua LAN → cho phép luôn; người lạ/relay → hỏi xác nhận (Cho phép điều khiển / Chỉ xem / Từ chối).
2. Chế độ chỉ xem: agent loại bỏ mọi input/clipboard_set/file từ viewer view-only (kiểm tra ở agent, KHÔNG tin cờ phía client). Overlay hiển thị "Chỉ xem".
3. "Truy cập không giám sát" (tùy chọn, mặc định TẮT): chỉ cho thiết bị đã ghép cặp + bắt buộc TOTP (RFC 6238; secret lưu DPAPI, hiện QR để thêm vào app Authenticator, 10 mã khôi phục băm). Nếu bật phải có cảnh báo rõ và ghi vào audit.
4. Audit log: SQLite (hoặc JSON lines xoay vòng) tại %APPDATA%/TouchLink/audit: thời điểm, thiết bị, IP (che bớt khi qua relay), phương thức xác thực, quyền, bắt đầu/kết thúc phiên, sự kiện nhạy cảm (mở khóa qua service, bật không giám sát, đổi MK, truyền file). KHÔNG ghi nội dung phím/clipboard. Có tab "Nhật ký" trong GUI + nút Xuất.
5. Giới hạn số phiên đồng thời, thời gian tối đa mỗi phiên (tùy chọn), tự ngắt khi không hoạt động X phút (tùy chọn).
6. Tests: ma trận chính sách, view-only chặn input, TOTP đúng/sai/trôi giờ ±1 bước, mã khôi phục dùng một lần, log không chứa nội dung nhạy cảm.

DoD: người lạ qua relay luôn bị hỏi xác nhận; view-only thực sự không điều khiển được (kiểm thử bằng client giả mạo gửi input); audit ghi đủ sự kiện.
```

### Sprint 2.4 — Gia cố TouchLinkSvc + rà soát bảo mật

**Mục tiêu:** Thu hẹp bề mặt tấn công của service SYSTEM.
**Phụ thuộc:** 2.3.

```text
NHIỆM VỤ: Sprint 2.4 — Hardening service SYSTEM và review bảo mật toàn diện.

VIỆC CẦN LÀM:
1. Named pipe của TouchLinkSvc:
   - Tạo bằng SECURITY_ATTRIBUTES/SDDL chỉ cho SYSTEM + Administrators + SID của user cài đặt (không cho Everyone/Authenticated Users); FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_REJECT_REMOTE_CLIENTS.
   - Xác thực caller: lấy PID client (GetNamedPipeClientProcessId), kiểm tra đường dẫn exe nằm trong thư mục cài đặt, chữ ký/hash khớp danh sách cho phép; từ chối nếu không.
   - Giao thức pipe: message có độ dài tiền tố, giới hạn kích thước, whitelist đúng 2 nhóm lệnh: capture_secure_desktop, send_input (mouse/key/unicode). Từ chối mọi lệnh khác (không có chạy lệnh, không đọc/ghi file, không clipboard).
2. Chỉ bật "mở khóa từ xa" khi người dùng chủ động bật trong Cài đặt (mặc định TẮT); mọi lần dùng ghi audit; hiển thị overlay/cảnh báo trước khi gửi phím vào màn hình đăng nhập; hạn chế tần suất.
3. Service chạy với đặc quyền tối thiểu có thể (bỏ privilege thừa), tự khôi phục khi lỗi, log vào Event Log.
4. Cài/gỡ: install_service.bat và nút trong GUI hiện UAC rõ ràng; uninstall dọn sạch pipe/registry/file.
5. Fuzz test pipe (scripts/fuzz_pipe.py): gửi dữ liệu rác/quá lớn/ngắt giữa chừng → service không crash, không treo.
6. Rà soát toàn bộ theo docs/SECURITY_CHECKLIST.md (xem Phụ lục B của kế hoạch): tạo file checklist, tự đánh giá từng mục, ghi kết quả + việc còn tồn đọng. Chạy bandit và pip-audit; sửa lỗi mức cao.
7. Thêm SECURITY.md (cách báo lỗi bảo mật có trách nhiệm).

DoD: tiến trình user thường không mở được pipe; tiến trình không hợp lệ bị từ chối; fuzz 10 phút không lỗi; checklist đạt toàn bộ mục "Bắt buộc"; bandit/pip-audit không còn lỗi cao.
```

---

## GIAI ĐOẠN 3 — WEBRTC (4 tuần)

### Sprint 3.1 — Spike hiệu năng + khung transport

**Mục tiêu:** Chứng minh khả thi; tách transport thành module.
**Phụ thuộc:** Gate 2.

```text
NHIỆM VỤ: Sprint 3.1 — Refactor transport/ và spike WebRTC bằng aiortc.

VIỆC CẦN LÀM:
1. Refactor: tạo desktop/transport/ với giao diện Transport (start, send_video(frame), send_data(msg), on_data, on_peer_change, stats(), close). Cài đặt LanWsTransport và RelayWsTransport từ code hiện có (không đổi hành vi). core.py chỉ nói chuyện qua giao diện này.
2. Spike: desktop/transport/webrtc.py với aiortc — RTCPeerConnection, 1 video track (VideoStreamTrack nhận frame từ Capturer), 1 DataChannel "ctrl" (ordered, reliable) cho chuột/phím/clipboard và 1 DataChannel "mouse" (unordered, maxRetransmits=0) cho di chuyển chuột.
3. Trang thử web/webrtc-spike.html: kết nối cục bộ qua signaling thủ công (copy/paste SDP) để nhận video và gửi sự kiện.
4. Benchmark scripts/bench_webrtc.py: CPU%, FPS, bitrate, độ trễ với H.264 (PyAV/libx264, thử h264_nvenc/qsv/amf nếu có) và VP8 ở 1080p/720p; ghi vào docs/BENCHMARK.md. Đánh giá: nếu CPU > mục tiêu, đề xuất phương án tách tiến trình mã hóa (ffmpeg subprocess đẩy RTP) và ghi quyết định vào docs/ADR-0001-video-pipeline.md.
5. Tests: giao diện Transport với bản FakeTransport; regression các luồng LAN/relay cũ.

KHÔNG LÀM: chưa signaling qua relay, chưa TURN.

DoD: video từ desktop hiển thị trên web qua WebRTC; có số đo; ADR chốt hướng encode; luồng cũ vẫn chạy y như trước.
```

### Sprint 3.2 — Signaling + ICE/TURN

**Mục tiêu:** Kết nối P2P qua internet, có TURN dự phòng.
**Phụ thuộc:** 3.1.

```text
NHIỆM VỤ: Sprint 3.2 — Signaling qua relay và hạ tầng STUN/TURN.

VIỆC CẦN LÀM:
1. Signaling: tái dùng WS relay chỉ để trao offer/answer/ICE candidate. Thông điệp: rtc_offer, rtc_answer, rtc_ice, rtc_bye (có version, kích thước giới hạn). Đoạn signaling phải được XÁC THỰC bằng kênh đã thiết lập ở Giai đoạn 2 (ký SDP bằng khóa định danh, kiểm tra fingerprint DTLS trong SDP khớp khóa đã ghép/đã xác minh) để chống MITM tráo SDP.
2. Hạ tầng: deploy/coturn/ (docker-compose + turnserver.conf mẫu) với use-auth-secret, thông tin đăng nhập TURN tạm thời (TURN REST API: username=timestamp:id, credential=HMAC) do relay cấp qua signaling có TTL ngắn; bật TLS (turns:443) để vượt tường lửa; giới hạn băng thông/phiên và chặn dải IP nội bộ (denied-peer-ip).
3. Cấu hình ICE: STUN công cộng + TURN riêng; ưu tiên host/srflx trước relay; trickle ICE; thời gian chờ kết nối 15s rồi báo trạng thái và tự thử lại/ fallback.
4. Cơ chế chọn transport: thứ tự LAN-WS → WebRTC P2P → WebRTC qua TURN → Relay-WS E2E. Hiển thị trên HUD đang dùng đường nào (P2P/TURN/Relay).
5. ICE restart khi đổi mạng (Wi-Fi ↔ 4G) không cần nhập lại MK.
6. Tests: unit signaling (ký/kiểm SDP, từ chối SDP bị sửa), TURN credential hết hạn, mô phỏng NAT đối xứng (dùng coturn local + chặn UDP) → vẫn kết nối qua TURN TCP/TLS.
7. docs/DEPLOY_RELAY.md thêm phần TURN + mở cổng (3478/udp+tcp, 5349, 443, dải relay UDP).

DoD: điện thoại 4G ↔ máy tính sau NAT kết nối được (P2P hoặc TURN); SDP bị sửa giữa đường bị từ chối; đổi mạng không rớt phiên quá 5s.
```

### Sprint 3.3 — Video H.264, DataChannel input, hợp nhất tính năng

**Mục tiêu:** Chất lượng video tốt, toàn bộ tính năng chạy qua WebRTC.
**Phụ thuộc:** 3.2.

```text
NHIỆM VỤ: Sprint 3.3 — Hoàn thiện đường WebRTC cho video và điều khiển.

VIỆC CẦN LÀM:
1. Video: thực hiện quyết định trong ADR-0001. Ưu tiên H.264 (hw nếu có: NVENC/QSV/AMF; sw x264 preset ultrafast + zerolatency), fallback VP8. Thiết lập: keyframe interval ngắn + PLI/FIR để phục hồi, bitrate thích ứng (REMB/TWCC) trong khoảng 300 kbps–8 Mbps, giới hạn fps theo hoạt động màn hình (tĩnh → 2–5 fps), chế độ "ưu tiên chữ nét" (tune stillimage cho nội dung văn bản).
2. Chuyển toàn bộ tính năng sang DataChannel: input, settings, clipboard 2 chiều, chat, ping, danh sách viewer, chọn màn hình, đổi độ phân giải/chất lượng. Giữ schema JSON hiện tại để tái dùng handler trong core.py.
3. Quyền và chính sách (view-only, consent, audit) áp dụng NHƯ NHAU cho mọi transport — kiểm tra ở lớp core, không ở lớp transport.
4. PWA: web/transport/ với WebRtcTransport và WsTransport cùng giao diện; app.js không phụ thuộc loại transport; video dùng <video> (autoplay, playsinline, muted) với cờ độ trễ thấp (requestVideoFrameCallback để đo độ trễ); tọa độ chạm ánh xạ đúng theo kích thước video thực + zoom.
5. Tự chuyển đường: nếu WebRTC thất bại/kém → tự lùi sang JPEG-WS có thông báo; người dùng có thể ép chế độ trong Cài đặt.
6. Benchmark lại, cập nhật docs/BENCHMARK.md với mục tiêu A3 (độ trễ ≤ 200ms P2P; CPU ≤ 15%).
7. Tests: mô phỏng mất gói/độ trễ (netem) → bitrate thích ứng; chuyển đường fallback; view-only vẫn chặn input qua DataChannel.

DoD: toàn bộ tính năng hiện có dùng được qua WebRTC; fallback hoạt động; số đo đạt hoặc có ghi chú vì sao chưa đạt.
```

### Sprint 3.4 — Ổn định, tương thích trình duyệt, tối ưu pin

**Mục tiêu:** Chạy tốt trên Android Chrome, iOS Safari; tiết kiệm pin điện thoại.
**Phụ thuộc:** 3.3.

```text
NHIỆM VỤ: Sprint 3.4 — Ổn định và tương thích.

VIỆC CẦN LÀM:
1. Ma trận tương thích: Android Chrome/Firefox/Samsung Internet, iOS Safari 16+ (PWA). Ghi vào docs/COMPAT.md các khác biệt (H.264 profile, autoplay, WebCrypto X25519, Wake Lock, fullscreen).
2. iOS: bắt buộc playsinline, xử lý bàn phím ảo làm đổi viewport (visualViewport), ẩn thanh địa chỉ; gõ qua input ẩn + composition events cho IME tiếng Việt.
3. Pin/nhiệt: giảm tốc render khi tab ẩn, tắt HUD khi không dùng, dùng requestVideoFrameCallback thay vì vẽ canvas khi có thể.
4. Soak test: scripts/soak.py chạy phiên 2 giờ, theo dõi rò rỉ bộ nhớ agent (tracemalloc/psutil), số handle, số thread; sửa rò rỉ.
5. Chaos test: tắt/mở relay, ngắt TURN, đổi mạng, rút Wi-Fi desktop → phiên khôi phục hoặc dọn sạch, không treo GUI, không kẹt phím.
6. Sửa lỗi phát hiện, cập nhật Release Notes nháp (CHANGELOG.md).

DoD: phiên 2 giờ không tăng bộ nhớ bất thường; khôi phục sau mất mạng < 10s; PWA dùng tốt trên Android Chrome và iOS Safari (ghi các giới hạn còn lại).
```

---

## GIAI ĐOẠN 4 — TÍNH NĂNG (4 tuần)

### Sprint 4.1 — Âm thanh từ máy tính

**Phụ thuộc:** Gate 3.

```text
NHIỆM VỤ: Sprint 4.1 — Truyền âm thanh máy tính → điện thoại.

VIỆC CẦN LÀM:
1. Capture WASAPI loopback (thư viện pyaudiowpatch hoặc soundcard; ghim phiên bản), xử lý đổi thiết bị phát mặc định, mẫu 48 kHz stereo.
2. Mã hóa Opus (qua PyAV/ffmpeg hoặc aiortc AudioStreamTrack) 32–96 kbps; đẩy làm audio track WebRTC, chỉ khi caps "audio" được hai bên khai báo. Với đường Relay-WS: gói Opus nhỏ qua kênh E2E.
3. PWA: nút bật/tắt loa, thanh âm lượng; đồng bộ A/V gần đúng (không cần chính xác tuyệt đối); xử lý chính sách autoplay (bật khi có thao tác người dùng).
4. Quyền: mặc định TẮT, cần bật ở agent hoặc được người ngồi máy cho phép; view-only vẫn có thể nghe nếu được cấp. Ghi audit khi bật.
5. Tests: encoder nhận PCM giả ra Opus hợp lệ; đổi thiết bị không crash.

DoD: nghe được âm thanh với độ trễ < 300ms trên LAN; không làm tăng CPU > 3%; tắt là dừng capture hoàn toàn.
```

### Sprint 4.2 — Truyền file hai chiều

**Phụ thuộc:** Gate 3.

```text
NHIỆM VỤ: Sprint 4.2 — Truyền file qua DataChannel/kênh E2E.

VIỆC CẦN LÀM:
1. Giao thức file (docs/PROTOCOL.md): file_offer{id,name,size,sha256}, file_accept/reject, file_chunk{id,seq,data} (16–64 KB), file_ack, file_done, file_cancel. Có kiểm soát luồng (cửa sổ trượt) và tiếp tục khi rớt (resume theo seq).
2. Điện thoại → máy tính: lưu vào thư mục riêng (mặc định %USERPROFILE%/Downloads/TouchLink), KHÔNG tự mở/chạy file; làm sạch tên file (chống path traversal, tên thiết bị Windows như CON/NUL, ký tự cấm), chống ghi đè (thêm hậu tố), giới hạn dung lượng (mặc định 500 MB) và tổng dung lượng/ngày, chặn đuôi thực thi nguy hiểm (.exe .bat .cmd .ps1 .vbs .js .msi .scr .lnk…) trừ khi người ngồi máy xác nhận thủ công.
3. Máy tính → điện thoại: người ngồi máy chọn file từ GUI hoặc điện thoại yêu cầu duyệt thư mục được chia sẻ (allowlist thư mục do người dùng cấu hình; mặc định không chia sẻ gì). Không cho duyệt toàn ổ đĩa.
4. Mọi chuyển file cần xác nhận trên desktop trừ khi thiết bị đã ghép cặp và bật "tự động nhận"; view-only không được gửi/nhận.
5. Kiểm tra toàn vẹn SHA-256; hiển thị tiến độ, tốc độ, hủy; ghi audit (tên file, kích thước, hướng — không ghi nội dung).
6. Tests: làm sạch tên file, giới hạn dung lượng, resume, hash sai bị hủy, thư mục ngoài allowlist bị từ chối.

DoD: gửi file 200 MB qua P2P và qua TURN thành công, resume được; không thể ghi ra ngoài thư mục đích; chặn đuôi nguy hiểm có hiệu lực.
```

### Sprint 4.3 — Nhiều viewer, macro, phím tắt tùy biến

**Phụ thuộc:** Gate 3.

```text
NHIỆM VỤ: Sprint 4.3 — Đa viewer và tiện ích thao tác.

VIỆC CẦN LÀM:
1. Đa viewer qua relay/WebRTC: agent giữ nhiều peer; mô hình "một người điều khiển (controller) + nhiều người xem (viewer)"; cơ chế chuyển quyền điều khiển cần người ngồi máy hoặc controller hiện tại cho phép; chat chung; giới hạn số viewer (mặc định 4). Tái mã hóa một lần cho nhiều peer khi cùng profile để tiết kiệm CPU (simulcast đơn giản hoặc chia sẻ track).
2. Macro/phím tắt tùy biến trong PWA: người dùng tạo nút (tên, biểu tượng, chuỗi hành động: phím tổ hợp, gõ văn bản, chờ N ms, mở ứng dụng từ DANH SÁCH CHO PHÉP phía agent). Lưu trên điện thoại (IndexedDB) và đồng bộ qua agent cho thiết bị đã ghép (mã hóa).
3. Chặn macro nguy hiểm: macro chạy ở phía điện thoại → chỉ phát chuỗi input thường; "mở ứng dụng" chỉ chạy các mục trong allowlist cấu hình ở agent (không cho chạy lệnh tùy ý); giới hạn tốc độ và độ dài macro.
4. Cử chỉ 3 ngón (Alt+Tab, Win+Tab), chế độ ngang/dọc, tự phóng to vùng gõ khi bật bàn phím ảo.
5. Tests: chuyển quyền điều khiển, viewer không thể gửi input, macro vượt giới hạn bị từ chối, allowlist ứng dụng.

DoD: 3 viewer xem cùng lúc ổn định; chuyển quyền hoạt động; macro chạy đúng, không thể thực thi lệnh ngoài allowlist.
```

### Sprint 4.4 — Wake-on-LAN, đánh thức rồi kết nối, hoàn thiện iOS

**Phụ thuộc:** 2.1, 3.4.

```text
NHIỆM VỤ: Sprint 4.4 — WoL và trải nghiệm iOS/PWA.

VIỆC CẦN LÀM:
1. Wake-on-LAN: PWA lưu MAC + broadcast cho từng máy; vì trình duyệt không gửi UDP broadcast, dùng một "WoL helper" là agent khác cùng LAN (máy đang bật) hoặc relay-side helper chạy trong LAN (tùy chọn). Thiết kế: máy A (đang bật, agent TouchLink) nhận lệnh wake đã xác thực từ thiết bị đã ghép và gửi magic packet cho máy B. Giao thức: wake_request{target_mac} chỉ cho thiết bị tin cậy có quyền "wake"; giới hạn tần suất; audit.
2. Luồng "Đánh thức rồi kết nối": gửi wake → PWA hiển thị đếm tiến trình, thăm dò máy online (agent register lại trên relay) → tự kết nối khi sẵn sàng; timeout rõ ràng.
3. docs/WOL.md: bật WoL trong BIOS/NIC/Windows (Fast Startup, "Allow this device to wake the computer").
4. iOS PWA: manifest đầy đủ (icon, display standalone), meta apple-touch, splash; xử lý giới hạn nền của iOS (mất kết nối khi chuyển app → resume nhanh bằng resume_token).
5. Tests: dựng magic packet đúng định dạng, chống lặp/tần suất, quyền wake.

DoD: đánh thức một máy trong LAN từ điện thoại ngoài mạng thông qua máy trung gian; iOS cài PWA và kết nối lại nhanh sau khi quay lại app.
```

---

## GIAI ĐOẠN 5 — PHÁT HÀNH (2 tuần)

### Sprint 5.1 — CI/CD + build + giảm báo nhầm AV

**Phụ thuộc:** Gate 4 (hoặc bất kỳ mốc phát hành).

```text
NHIỆM VỤ: Sprint 5.1 — CI/CD và build đáng tin cậy.

VIỆC CẦN LÀM:
1. GitHub Actions:
   - test.yml: pytest + ruff + mypy (mức vừa) + bandit + pip-audit trên windows-latest, ma trận Python 3.10/3.11/3.12.
   - release.yml: khi tag vX.Y.Z → build, ký, tạo GitHub Release đính kèm zip portable + installer + SHA256SUMS + SBOM (CycloneDX).
2. Build: thử Nuitka (--onefile hoặc standalone) so với PyInstaller; chọn bản ít bị AV gắn cờ (kiểm tra VirusTotal, ghi kết quả vào docs/RELEASE.md). Ghim phiên bản công cụ; build có thể tái lập (reproducible) ở mức tốt nhất có thể.
3. Ký số: tích hợp signtool (chứng chỉ OV/EV qua secrets) hoặc SignPath Foundation cho dự án mã nguồn mở; timestamp. Viết hướng dẫn quản lý khóa (không để khóa trong repo).
4. Metadata exe: version info, tên công ty/sản phẩm, icon; manifest ghi rõ asInvoker (không đòi admin trừ khi cài service).
5. Quy trình nộp mẫu báo nhầm cho Microsoft Defender và các AV chính; công khai hash SHA-256 trong Release notes.
6. Dependabot/Renovate cho phụ thuộc; chính sách ghim phiên bản và kiểm tra sau 14 ngày với bản mới.

DoD: push tag tạo Release hoàn chỉnh tự động; exe có chữ ký; VirusTotal ghi nhận kết quả; SBOM đính kèm.
```

### Sprint 5.2 — Installer + tự cập nhật

**Phụ thuộc:** 5.1.

```text
NHIỆM VỤ: Sprint 5.2 — Installer và auto-update an toàn.

VIỆC CẦN LÀM:
1. Installer Inno Setup (hoặc WiX/MSI): cài per-user mặc định (không cần admin); tùy chọn thành phần "Cài TouchLinkSvc (cần quyền Admin, mở khóa từ xa)" mặc định KHÔNG chọn; rule Firewall chỉ cho mạng Private; shortcut; gỡ cài đặt sạch (kể cả service, pipe, rule).
2. Không có tùy chọn tự khởi động ngầm bắt buộc. Nếu cung cấp "Chạy khi đăng nhập Windows" thì phải là lựa chọn rõ ràng của người dùng, vẫn hiện icon khay và overlay khi có kết nối.
3. Tự cập nhật: kiểm tra manifest phiên bản (JSON ký Ed25519 do dự án giữ khóa; khóa công khai nhúng trong app) từ GitHub Releases; tải về, kiểm SHA-256 + chữ ký, hỏi người dùng trước khi cài; không bao giờ cập nhật im lặng; chống hạ cấp (downgrade) và kiểm tra HTTPS.
4. Xuất log chẩn đoán: nút "Xuất log" gom log (đã loại bỏ thông tin nhạy cảm: MK, khóa, nội dung) + phiên bản + cấu hình tóm tắt vào zip.
5. Tests: kiểm chữ ký manifest (hợp lệ/sai/hết hạn), chống downgrade, xử lý tải hỏng giữa chừng.

DoD: cài sạch và gỡ sạch trên Windows 10/11 VM; cập nhật từ v(n) lên v(n+1) có xác minh chữ ký; manifest bị sửa bị từ chối.
```

### Sprint 5.3 — Tài liệu, kiểm thử chấp nhận, phát hành v3.0

**Phụ thuộc:** 5.2.

```text
NHIỆM VỤ: Sprint 5.3 — Hoàn thiện và phát hành v3.0.

VIỆC CẦN LÀM:
1. Tài liệu: viết lại README.md (tiếng Việt + bản tiếng Anh README.en.md): giới thiệu, ảnh/gif demo, cài đặt, ghép cặp, mô hình bảo mật (nói rõ điều gì relay thấy/không thấy), tự host relay + TURN, giới hạn đã biết, câu hỏi thường gặp, khắc phục sự cố. Thêm docs/ARCHITECTURE.md, docs/SECURITY.md, docs/PROTOCOL.md (v2), docs/TESTING.md, docs/DEPLOY_RELAY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md.
2. Kiểm thử chấp nhận (docs/ACCEPTANCE.md) theo kịch bản: cài sạch → ghép cặp → điều khiển LAN → điều khiển 4G P2P → TURN → relay E2E → mất mạng/khôi phục → mở khóa từ xa có service → thu hồi thiết bị → gỡ cài đặt. Ghi kết quả, ảnh chụp.
3. Rà soát lần cuối: chạy lại SECURITY_CHECKLIST, benchmark so với mục tiêu A3, kiểm tra không còn TODO/FIXME nghiêm trọng, cập nhật CHANGELOG.md, bump version 3.0.0.
4. Tạo Release v3.0.0 qua CI; kiểm tra tải về và cài thử từ Release thật.
5. Kế hoạch sau phát hành: tạo ISSUE template, nhãn, roadmap v3.1 (ví dụ: chia sẻ nhiều màn hình, ghi hình phiên có xác nhận, plugin transport).

DoD: tài liệu đầy đủ và đúng với hành vi thật; acceptance đạt; Release v3.0.0 công khai kèm chữ ký + hash.
```

---

# Phụ lục

## Phụ lục A — Bản nháp giao thức v2 (tham chiếu cho AI IDE)

```text
Bắt tay:
  C→S: {"type":"hello","v":2,"caps":["tiles","pairing-v1","e2e-v1","webrtc","audio","files","multi-viewer"],"client":"pwa/3.0"}
  S→C: {"type":"hello","v":2,"caps":[...],"agent":"desktop/3.0","id_fp":"<sha256 pubkey agent>"}
Quy tắc: bên nhận bỏ qua trường lạ; thiếu "v" = v1; chọn tính năng = giao của hai tập caps.

Xác thực (một trong ba):
  1. key   : agent gửi {"type":"auth_challenge","nonce":b64}; viewer trả {"type":"auth_key","dev":id,"sig":b64}
  2. otp   : PAKE/HMAC với MK dùng một lần
  3. totp  : bổ sung cho truy cập không giám sát

Kết quả: {"type":"auth_ok","role":"control|view","resume":"<token 2 phút>"} | {"type":"auth_fail","reason":"unavailable"}  (reason chung)

Video JPEG: 0x01|w|h|JPEG (toàn khung) ; 0x02|w|h|tile|n|[x,y,len,JPEG]*n (tile)
WebRTC: rtc_offer / rtc_answer / rtc_ice / rtc_bye (ký bằng khóa định danh)
File: file_offer / file_accept / file_reject / file_chunk / file_ack / file_done / file_cancel
Khác: wake_request, input, settings, clipboard_*, chat, ping/pong, clients
Giới hạn: JSON ≤ 64 KB; chunk file ≤ 64 KB; frame ≤ 4 MB
```

## Phụ lục B — Checklist bảo mật (mục "Bắt buộc" = Gate 2)

| # | Mục | Mức |
|---|---|---|
| 1 | Relay không đọc được frame/phím/MK (test ciphertext) | Bắt buộc |
| 2 | Rate-limit relay theo ID/IP/toàn cục; lỗi chung chống dò ID | Bắt buộc |
| 3 | MK dùng một lần, ≥ 10 ký tự, có hạn; không đi kèm URL/QR | Bắt buộc |
| 4 | Pairing có SAS đối chiếu; secret hết hạn nhanh | Bắt buộc |
| 5 | Người lạ/relay luôn bị hỏi xác nhận trên desktop | Bắt buộc |
| 6 | View-only được thực thi ở agent | Bắt buộc |
| 7 | Overlay luôn nổi + nút/phím nóng ngắt khẩn cấp | Bắt buộc |
| 8 | Pipe service: ACL chặt, kiểm tra caller, whitelist lệnh, fuzz pass | Bắt buộc |
| 9 | Mở khóa từ xa mặc định TẮT, có audit | Bắt buộc |
| 10 | Không log MK/khóa/nội dung phím/clipboard | Bắt buộc |
| 11 | File: chống path traversal, chặn đuôi thực thi, giới hạn dung lượng | Bắt buộc (khi có 4.2) |
| 12 | SDP/signaling được xác thực, chống MITM | Bắt buộc (khi có GĐ3) |
| 13 | Cập nhật: chữ ký + chống downgrade, không cập nhật im lặng | Bắt buộc (khi có 5.2) |
| 14 | Phụ thuộc ghim phiên bản, pip-audit sạch lỗi cao | Nên |
| 15 | TOTP cho truy cập không giám sát | Nên |
| 16 | Khóa riêng điện thoại non-extractable (nếu trình duyệt hỗ trợ) | Nên |

## Phụ lục C — Bảng theo dõi Sprint (sao chép để dùng)

| Sprint | Nhánh | Trạng thái | Ngày bắt đầu | Ngày xong | Ghi chú/rủi ro |
|---|---|---|---|---|---|
| 0.1 | sprint/0.1-docs-protocol | ☐ | | | |
| 0.2 | sprint/0.2-relay-hardening | ☐ | | | |
| 0.3 | sprint/0.3-relay-overlay | ☐ | | | |
| 1.1 | sprint/1.1-dxgi-tiles | ☐ | | | |
| 1.2 | sprint/1.2-sendinput | ☐ | | | |
| 1.3 | sprint/1.3-adaptive | ☐ | | | |
| 2.1 | sprint/2.1-pairing | ☐ | | | |
| 2.2 | sprint/2.2-e2e-otp | ☐ | | | |
| 2.3 | sprint/2.3-consent-audit | ☐ | | | |
| 2.4 | sprint/2.4-service-hardening | ☐ | | | |
| 3.1 | sprint/3.1-transport-spike | ☐ | | | |
| 3.2 | sprint/3.2-signaling-turn | ☐ | | | |
| 3.3 | sprint/3.3-webrtc-features | ☐ | | | |
| 3.4 | sprint/3.4-stability | ☐ | | | |
| 4.1 | sprint/4.1-audio | ☐ | | | |
| 4.2 | sprint/4.2-files | ☐ | | | |
| 4.3 | sprint/4.3-multiviewer-macro | ☐ | | | |
| 4.4 | sprint/4.4-wol-ios | ☐ | | | |
| 5.1 | sprint/5.1-cicd | ☐ | | | |
| 5.2 | sprint/5.2-installer-update | ☐ | | | |
| 5.3 | sprint/5.3-release | ☐ | | | |

## Phụ lục D — Mẫu prompt kiểm tra cuối mỗi Sprint (dán sau khi AI báo xong)

```text
Hãy tự review Sprint vừa làm như một người kiểm tra độc lập:
1. Đối chiếu từng mục trong "VIỆC CẦN LÀM" và "DoD": mục nào đã xong, mục nào chưa, bằng chứng (file/test/lệnh).
2. Chạy toàn bộ test và dán kết quả. Liệt kê test mới thêm.
3. Tìm lỗi bảo mật tiềm ẩn trong diff (đầu vào chưa kiểm tra, log lộ bí mật, race condition, tài nguyên không giải phóng, phím/chuột bị kẹt).
4. Kiểm tra tương thích ngược: agent cũ + PWA mới, PWA cũ + agent mới.
5. Liệt kê giả định đã dùng, việc còn tồn đọng, và đề xuất bước tiếp theo.
Không sửa thêm tính năng ngoài phạm vi; chỉ sửa lỗi tìm thấy.
```

---

*Hết tài liệu. Khuyến nghị: bắt đầu từ Sprint 0.1, hoàn thành Gate 0 rồi mới mở rộng.*
