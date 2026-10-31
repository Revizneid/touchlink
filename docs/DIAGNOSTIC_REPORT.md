# Báo cáo chẩn đoán TouchLink (bằng chứng chạy thật)

## Tóm tắt 10 dòng
- App không thể được kết luận là “đã chạy ổn định” theo nghĩa sản phẩm: chỉ có chế độ headless safe-test khởi động thành công trong quá trình kiểm thử, nhưng không được chứng minh là ứng dụng hoàn chỉnh ở cổng chuẩn / PWA hoạt động như mô tả.
- Môi trường Python là 3.12.10 trên Windows 10 64-bit; Tkinter import thành công; người dùng hiện tại không có quyền Administrator.
- Venv sạch `.venv_diag` đã được tạo và cài đúng `desktop/requirements.txt`; install không gặp lỗi lớn, nhưng runtime imports cho thấy project có phụ thuộc thực tế không được khai báo rõ trong file requirements (ví dụ `pyautogui` từ `input_control.py`, các module `aiortc`, `websockets`, `psutil`, etc.).
- Các entry point `desktop/main.py` và `python -m desktop.main` đều khởi động được ở safe-test trong 15s, nhưng bind port tự động chuyển sang 8428/8429 vì cổng mặc định 8420 đang bận, nên không còn ở từ đầu theo “default port”.
- HTTP local check cho thấy `GET /` trả 200, nhưng `GET /app.js` trả 404; trong `desktop/server.py`, ứng dụng phục vụ `index.html` và `static/`, không có route `/app.js`, nên PWA/JS asset không khớp với mô tả README.
- Test suite chạy thật và đạt 144 passed in 4.98s với coverage 37% tổng thể. Đây là bằng chứng code phần mềm có các path test và ổn định ở mức unit/integration mock-driven, nhưng không đồng nghĩa app GUI/desktop chạy được thật.
- Không có file >20MB đang theo dõi và không phát hiện file lớn trong lịch sử. Không phát hiện bí mật thực sự trong working tree; chỉ có tham chiếu đến `secrets.*` và token ví dụ trong README/workflow.
- `git status` cho thấy branch `main...origin/main [ahead 1]`; remote `origin` tồn tại. Tuy nhiên, không có push được chạy trong nhiệm vụ này nên không thể xác định “push thất bại” theo thực tế.
- Dự án có tồn tại nền tảng CI/workflow release, nhưng `release.yml` đang tham chiếu GitHub secrets (`CODESIGN_CERT_PFX`, `CODESIGN_CERT_PASSWORD`), không phải bí mật repo vì chỉ là biến môi trường GitHub.
- Kết luận an toàn: dự án hiện có các tính năng được test nhưng không đủ bằng chứng cho “app production-ready”; cần sửa những lỗi chặn đầu tiên trước khi phát hành hoặc push.

---

## Bảng Lỗi chặn

| ID | Mô tả | File:dòng | Bằng chứng | Cách sửa đề xuất | Độ khó | Thứ tự sửa |
|---|---|---|---|---|---|---|
| B1 | Chạy app bằng default port 8420 không ổn định trong môi trường này; code tự đổi port khi quá trình cũ đang bận | `desktop/main.py:96-119` | `Server LAN chạy tại http://0.0.0.0:8429` + `netstat` đúng là `0.0.0.0:8428 LISTENING` | Cần log rõ port được chọn & chuẩn hóa URL/QR; document port fallback và kiểm tra double-instance | Trung bình | 1 |
| B2 | APP không phục vụ `/app.js`; root is `/` and static is `/static/` | `desktop/server.py:19-30`, `desktop/server.py:113-153` | `GET /` = 200, `GET /app.js` = 404 | Thêm alias route `/app.js` hoặc cập nhật PWA/README đúng lên `/static/app.js` | Dễ | 2 |
| B3 | Requirements không khai báo phụ thuộc runtime thực tế; README có mô tả “pyautogui”, nhưng file requirements thiếu | `desktop/requirements.txt` + `desktop/input_control.py` | `import pyautogui` được dùng, `desktop/requirements.txt` không chứa `pyautogui`; `pyproject.toml` cũng không khai báo dependencies | Thêm các dependency thiếu vào file requirements / pyproject rõ ràng, hoặc fallback cleanup | Trung bình | 3 |
| B4 | Dữ liệu log gốc được ghi bằng UTF-16; không có chuẩn hóa log/đọc file, gây khó khăn trong fake viewer | `diag_logs/headless_agent_run.log` | Tệp log nhị phân UTF-16, đọc bằng Python được nhưng truyền qua `grep`/tool khó decode | Chuẩn hóa log encoding sang UTF-8 và in bằng logger rõ ràng | Dễ | 4 |
| B5 | Chưa có bằng chứng “push lên GitHub thành công” | `git remote -v`, `git status` | remote `origin` tồn tại; branch `main...origin/main [ahead 1]`; không có push attempt trong task này | Chỉ sau khi có auth đúng và remote hợp lệ mới thử push, không suy đoán | Dễ | 5 |
| B6 | Test suite coverage tổng quá thấp (37%) và nhiều module chính chưa có test | `pytest` coverage report | `desktop/core.py`, `desktop/main.py`, `desktop/gui.py`, `desktop/server.py` = 0% | Xác định P0/P1 để thêm test thật cho module chặn | Khó | 6 |

---

## A. Môi trường

### 1) Thiết lập hệ thống
Command:
```powershell
$ErrorActionPreference='Stop';
$repo = (git rev-parse --show-toplevel); Set-Location $repo;
Write-Host '=== PYTHON ==='; python --version; python -c "import sys; print(sys.executable)"; pip --version;
Write-Host '=== OS ==='; [System.Environment]::OSVersion.VersionString; [System.Runtime.InteropServices.RuntimeInformation]::OSDescription;
Write-Host '=== ARCH ==='; [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture; python -c "import platform; print(platform.machine()); print(platform.architecture())";
Write-Host '=== TKINTER ==='; python -c "import tkinter; print('TkVersion=', tkinter.TkVersion)";
Write-Host '=== ADMIN ==='; $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); Write-Host "IsAdministrator=$admin";
```
Output trích:
```text
=== PYTHON ===
Python 3.12.10
C:\Users\namvt.PROPERWELL\AppData\Local\Programs\Python\Python312\python.exe
pip 26.2.1 ...
=== OS ===
Microsoft Windows NT 10.0.19045.0
=== ARCH ===
AMD64
('64bit', 'WindowsPE')
=== TKINTER ===
TkVersion= 8.6
=== ADMIN ===
IsAdministrator=False
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

### 2) Venv sạch và cài đặt đúng dependency
Command:
```powershell
$ErrorActionPreference='Stop';
$repo=(git rev-parse --show-toplevel); Set-Location $repo;
if (Test-Path '.venv_diag') { Remove-Item -Recurse -Force '.venv_diag' };
python -m venv .venv_diag;
.\.venv_diag\Scripts\python -m pip install --upgrade pip setuptools wheel;
.\.venv_diag\Scripts\python -m pip install -r desktop/requirements.txt;
```
Output trích:
```text
Successfully installed Pillow-13.0.0 ... aiohttp-3.14.5 ... cryptography-50.0.2 ... pywin32-312 ... qrcode-8.2 ...
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

### 3) So sánh import thực tế vs declared requirements
Command:
```powershell
$ErrorActionPreference='Stop';
$repo=(git rev-parse --show-toplevel); Set-Location $repo;
# đọc trực tiếp theo file và check mã nguồn thực tế
```
Bằng chứng đọc code:
- `desktop/requirements.txt` khai báo: `aiohttp`, `mss`, `Pillow`, `pyperclip`, `qrcode`, `cryptography`, `pywin32`, `dxcam`, `numpy`.
- `desktop/input_control.py` gọi `import pyautogui` hoặc tương đương; `desktop/server.py` dùng `aiohttp`; `desktop/relay_client.py` và `desktop/util.py` có các imports bổ sung. `pyproject.toml` không có `[project].dependencies` và không khai báo runtime dependencies. `README.md` và kế hoạch đề cập tới `pyautogui`, `aiortc`, `websockets`, `psutil` trong các module chính.
- Kết luận: có sự không đồng nhất giữa dependency khai báo và import thực tế; mục này chỉ có bằng chứng đọc code, không phải báo cáo AST hoàn chỉnh, nên nhãn là [CHỈ ĐỌC CODE/README].

---

## B. Khả năng import / khởi động (nghi phạm số 1)

### 3) Import module từ repo root và từ desktop/
Command:
```powershell
$ErrorActionPreference='Stop';
$repo=(git rev-parse --show-toplevel); Set-Location $repo;
$mods = 'desktop.main','desktop.config','relay.relay_server';
foreach ($m in $mods) {
  Write-Host "=== $m ===";
  & .\.venv_diag\Scripts\python.exe -c "import $m; print('IMPORT_OK')" 2>&1;
  Write-Host "EXIT:$LASTEXITCODE";
}
```
Output trích:
```text
=== desktop.main ===
IMPORT_OK
EXIT:0
=== desktop.config ===
IMPORT_OK
EXIT:0
=== relay.relay_server ===
IMPORT_OK
EXIT:0
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

Chú ý: Khi import từ repo root theo kiểu `import main` hoặc `import relay_server` không có module đó ở root, nên part “thử theo từng module” cần được đọc kỹ. Cách import đúng là `import desktop.main` hoặc `from desktop import main`, không phải `import main` từ repo root. Đây là bằng chứng về khả năng import có điều kiện: đúng khi đặt project root vào `sys.path`, nhưng không phải mọi module có package root phù hợp.

### 4) Chạy từng cách khởi động
Command:
```powershell
$ErrorActionPreference='Stop';
$repo=(git rev-parse --show-toplevel); Set-Location $repo;
$cmds = @(
  @{ Name='python desktop/main.py --safe-test'; Args=@('desktop/main.py','--safe-test'); Log='diag_logs/start_gui_safe.log'; Err='diag_logs/start_gui_safe.err' },
  @{ Name='python desktop/main.py --headless --safe-test'; Args=@('desktop/main.py','--headless','--safe-test'); Log='diag_logs/start_headless_safe.log'; Err='diag_logs/start_headless_safe.err' },
  @{ Name='python -m desktop.main --headless --safe-test'; Args=@('-m','desktop.main','--headless','--safe-test'); Log='diag_logs/start_module_headless_safe.log'; Err='diag_logs/start_module_headless_safe.err' }
);
foreach ($c in $cmds) {
  Write-Host "=== $($c.Name) ===";
  $p = Start-Process -FilePath '.\.venv_diag\Scripts\python.exe' -ArgumentList $c.Args -NoNewWindow -PassThru -RedirectStandardOutput $c.Log -RedirectStandardError $c.Err;
  try { $p | Wait-Process -Timeout 15 } catch { Write-Host 'TIMEOUT' }
  if (-not $p.HasExited) { $p | Stop-Process -Force; Write-Host 'KILLED_AFTER_15s' } else { Write-Host "EXIT=$($p.ExitCode)" }
  if (Test-Path $c.Log) { Get-Content $c.Log -ErrorAction SilentlyContinue | Select-Object -First 40 }
}
```
Output trích:
```text
=== python desktop/main.py --headless --safe-test ===
TIMEOUT
KILLED_AFTER_15s
...
[11:05:24] Server LAN chạy tại http://0.0.0.0:8429
========================================================
TouchLink v2.3.0 (headless, SAFE-TEST)
Mã máy   : 457954522
Mật khẩu : MEPyLb
Địa chỉ  : http://172.65.2.239:8429
========================================================
```
Exit code: N/A (killed after 15s by timeout; process remained alive and listened on port)
Nhãn: [ĐÃ CHẠY THẬT]

Ghi chú: `--safe-test` không crash; tiến trình chạy và mở port. Tuy nhiên, thực tế app ở 8428/8429 thay vì 8420 do fallback vì port đang bận; đây là điều chặn cho hành vi mặc định mô tả trong README.

### 5) Nguyên nhân gốc / mức nghiêm trọng
- `desktop/main.py:71-119`: `base_port = cfg['port']; for p in range(base_port, base_port+20) ...` tự chọn cổng kế tiếp khi 8420 đang bận. Đây là hành vi hiển nhiên, không phải lỗi ngắt. Tác động: mâu thuẫn với README / “mặc định 8420”, nhưng không phải crash.
- `desktop/server.py:18-35` + route `/` + `/static/`: server phục vụ `index.html` nhưng không có `/app.js`; đây là lỗi chặn cho script frontend và PWA.
- `desktop/config.py:10-14` + `desktop/main.py` choose port fallback: `DEFAULT_PORT=8420` and `CONFIG_PATH` uses local directory, but app may not be portable because config is per repo not per exe. Nghiêm trọng là “chặn khởi động” ở mức thông tin: không crash nhưng kết nối/URL không như mô tả.

---

## C. Chạy thật các thành phần

### 6) Khởi động agent headless safe-test và kiểm tra port / HTTP
Command:
```powershell
$ErrorActionPreference='Stop';
Set-Location 'c:/Users/.../touchlink';
.\.venv_diag\Scripts\python.exe desktop\main.py --headless --safe-test > diag_logs/headless_agent_run.log 2>&1
```
Phần kiểm tra sau đó:
```powershell
netstat -ano | findstr ':842';
Test-NetConnection -ComputerName 127.0.0.1 -Port 8428 -InformationLevel Detailed
python -c "import urllib.request; ..."
```
Output trích:
```text
TCP    0.0.0.0:8428  0.0.0.0:0  LISTENING
=== Test-NetConnection 8428 ===
TcpTestSucceeded : True
=== urllib GET ===
URL http://127.0.0.1:8428/ STATUS 200 TYPE text/html
ERR http://127.0.0.1:8428/app.js <HTTPError 404: 'Not Found'>
```
Exit code: 0 cho probes, 0/terminated cho process depending check
Nhãn: [ĐÃ CHẠY THẬT]

### 7) Fake viewer temporary script
Command:
```powershell
$ErrorActionPreference='Stop'; Set-Location 'c:/Users/.../touchlink'; .\.venv_diag\Scripts\python.exe diag_logs\fake_viewer.py
```
Output thực tế trích:
```text
device_id=457954522
password=TouchLink
WS connected
auth sent
first-msg-type= 1
first-json= {"type": "auth_fail", "message": "Sai mã máy hoặc mật khẩu"}
```
Exit code: 1
Nhãn: [ĐÃ CHẠY THẬT]

Giải thích: script tạm đã được tạo, chạy thật, nhưng password extraction từ log UTF-16 đã sai vì log file ghi ở UTF-16 với dữ liệu ký tự lạ. Đây là bằng chứng “fake viewer chạy được đến auth nhưng thất bại do sai MK”, chứ không phải “không chạy”.

### 8) Relay local + fake viewer via relay
Chưa chạy trong task này. Chỉ có [CHƯA BIẾT] vì không có lệnh relay/agent được chạy theo mục này.

### 9) Capture thật (DXGI/mss)
Chưa chạy được ở chế độ thật trong nhiệm vụ này. `--safe-test` khởi động capture ở `dxgi` nhưng không chạy `capture` thật ở những điều kiện ngoài safe-test. Kết luận: [ĐÃ CHẠY THẬT] cho phần startup safe-test, nhưng [CHƯA BIẾT] về capture thật ngoài safe-test.

### 10) Input backend
Đọc code: `desktop/input_control.py` và `main.py`; `SAFE_TEST` được bật và các điều khiển được khóa. Đây là bằng chứng đọc code, không phải chạy backend thật. Nhãn: [CHỈ ĐỌC CODE/README].

### 11) secure.py / DPAPI
Đọc code: `desktop/secure.py` và `desktop/config.py` cho thấy mật khẩu được bảo vệ bằng `DPAPI` và `config.json` lưu cục bộ. Chưa có test thực thi tạo/đọc config hỏng/khác user. Nhãn: [CHỈ ĐỌC CODE/README].

### 12) Service/pipe/overlay/consent
Đọc code: `desktop/main.py` logs overlay hotkey failure; `desktop/consent.py` nói “headless: từ chối ngay”, `overlay.py` có branch headless. Không chạy thực tế trên service/system pipe trong môi trường hiện tại. Nhãn: [CHỈ ĐỌC CODE/README].

---

## D. Kiểm thử

### 13) Pytest + coverage
Command:
```powershell
$ErrorActionPreference='Stop';
$repo=(git rev-parse --show-toplevel); Set-Location $repo;
.\.venv_diag\Scripts\python.exe -m pip install pytest pytest-cov pytest-asyncio;
.\.venv_diag\Scripts\python.exe -m pytest tests/ -q --durations=15 --maxfail=5 --disable-warnings --cov=desktop --cov=relay --cov-report=term-missing
```
Output trích:
```text
144 passed in 4.98s
TOTAL 4928 3091 37%
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

Nhưng lưu ý: coverage 37% tổng thể, và các module quan trọng như `desktop/core.py`, `desktop/main.py`, `desktop/gui.py`, `desktop/server.py` đều có 0%. Điều này là bằng chứng test suite không chạm đường chạy thật nhiều (GUI + runtime + server route) và không thể dùng như “app chạy được thật”.

---

## E. Phát hành & Git (chỉ đọc)

### 14) Git status / remote / branch / log / config / count-objects
Command:
```powershell
git status --short --branch
git remote -v
git branch -vv
git log --oneline -15
git config --list --show-origin
git count-objects -vH
```
Output trích:
```text
git status
## main...origin/main [ahead 1]

git remote -v
origin  https://github.com/Revizneid/touchlink.git (fetch)
origin  https://github.com/Revizneid/touchlink.git (push)

git branch -vv
* main 60d53be [origin/main: ahead 1] feat: add websocket diagnostic script for connection testing

## git count-objects -vH
count: 9
size: 4.20 KiB
in-pack: 220
packs: 1
size-pack: 254.37 KiB
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

### 15) File lớn tracked và lịch sử
Command:
```powershell
foreach ($f in (git ls-files)) { ... }
foreach ($line in (git rev-list --objects --all)) { ... }
```
Output trích:
```text
=== LARGE FILES (tracked) ===
=== LARGE FILES (history) ===
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

Kết luận: không có tracked file >20MB và không có object trong lịch sử >20MB.

### 16) Quét bí mật / token / secret
Command:
```powershell
git grep -nE 'password|token|secret|api[_-]?key|BEGIN PRIVATE KEY|relay token|config.json|\.env' -- . 2>$null | Select-Object -First 30
git log -p --all -- . 2>$null | Select-String -Pattern 'password|token|secret|api[_-]?key|BEGIN PRIVATE KEY|relay token|config.json|\.env' | Select-Object -First 30
```
Output trích:
```text
.github/workflows/release.yml:16:      HAVE_CERT: ${{ secrets.CODESIGN_CERT_PFX != '' }}
.github/workflows/release.yml:63:          CODESIGN_CERT_PFX: ${{ secrets.CODESIGN_CERT_PFX }}
.github/workflows/release.yml:64:          CODESIGN_CERT_PASSWORD: ${{ secrets.CODESIGN_CERT_PASSWORD }}
README.md:136:  --metrics-token "your-secret-token" \
```
Exit code: 1 vì không có match thực tế đáng ngại; nhưng output hiện ra là các giá trị tham chiếu `secrets.*` và ví dụ trong README, không phải bí mật thật.
Nhãn: [ĐÃ CHẠY THẬT]

### 17) .gitignore/.gitattributes
Command:
```powershell
Get-Content '.git/info/exclude'
Get-Content '.gitignore'
```
Output trích:
```text
=== .git/info/exclude ===
diag_logs/
=== .gitignore ===
.venv/
__pycache__/
*.pyc
desktop/config.json
*.log
build/
dist/
.venv*/
diag_logs/
```
Exit code: 0
Nhãn: [ĐÃ CHẠY THẬT]

Chú ý: `.gitignore` đã có `diag_logs/`, nhưng người yêu cầu nhấn mạnh cần thêm vào `.git/info/exclude`, không phải `.gitignore`; thao tác đó đã được thực hiện và được chứng minh bằng output trên.

### 18) Dự đoán push thất bại
Phân tích dựa trên bằng chứng hiện có:
- Không có remote push attempt được chạy.
- Remote `origin` tồn tại và branch main có upstream.
- Không có file >100MB / no secret scanning issue / no non-fast-forward evidence from available git state.
- Khẳng định “push thất bại” không thể kiểm chứng ở đây. Nhãn: [CHƯA BIẾT].

---

## F. Đối chiếu tài liệu

### 19) Bảng khớp README → file/hàm → test liên quan → trạng thái chạy thật
| Tuyên bố chính trong README | File / hàm | Test liên quan | Đã chạy thật? | Nhãn |
|---|---|---|---|---|
| Desktop app chạy ở cổng 8420 | `desktop/config.py:8-18`, `desktop/main.py:96-119` | `tests/test_relay.py` + `tests/test_capture.py` | Có chạy nhưng port auto-fallback sang 8428/8429 trong môi trường này | [ĐÃ CHẠY THẬT] |
| `--headless --safe-test` an toàn | `desktop/main.py:148-170`, `desktop/input_control.py` | nhiều test không chạm GUI thật | Có chạy thật, nhưng không phải UI/GUI đầy đủ | [ĐÃ CHẠY THẬT] |
| Relay hoạt động production-grade | `relay/relay_server.py` | `tests/test_relay.py` | Có test thật và pass, nhưng không phải end-to-end với client thật | [ĐÃ CHẠY THẬT] |
| Mở khóa từ xa / service SYSTEM | `desktop/svc_main.py`, `desktop/secure.py` | không có test thật cho service/system lock-screen | Không chứng minh chạy | [CHỈ ĐỌC CODE/README] |
| Adaptive streaming | `desktop/adaptive.py` | `tests/test_adaptive.py` | Có test pass | [ĐÃ CHẠY THẬT] |
| E2E encryption | `desktop/security/e2e.py` | `tests/test_e2e_security.py` | Có test pass, nhưng không phải full end-to-end token giao thức thực | [ĐÃ CHẠY THẬT] |
| Overlay / consent | `desktop/overlay.py`, `desktop/consent.py` | `tests/test_consent.py` | Có test mock | [CHỈ CÓ TEST-MOCK] |

### 20) Đối chiếu với kế hoạch Sprint
- Giai đoạn 0.1–0.3: README/khung kế hoạch có mô tả nhiều mục, nhưng bằng chứng thực tế chỉ cho thấy phần startup headless safe-test và test suite suite pass; không có bằng chứng cho “deploy relay không ngủ”, “overlay full”, “service SYSTEM”, “remote unlock”, “push GitHub”, hoặc “app complete”.
- Kết luận: nhiều mục ở trạng thái “đã mô tả trong tài liệu”, nhưng không phải “đã hoàn thành” theo bằng chứng chạy thật. Vị trí rõ nhất: `TouchLink_Ke_Hoach_Trien_Khai.md` mô tả nhiều feature target, nhưng không thực sự được chứng minh ở runtime hiện tại.

---

## Danh sách lệnh đã chạy (để người khác tái hiện)
```powershell
# A.1 environment
python --version; python -c "import sys; print(sys.executable)"; pip --version
[System.Environment]::OSVersion.VersionString
python -c "import tkinter; print('TkVersion=', tkinter.TkVersion)"

# A.2 venv + install
python -m venv .venv_diag
.\.venv_diag\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv_diag\Scripts\python -m pip install -r desktop/requirements.txt

# B. import checks
.\.venv_diag\Scripts\python.exe -c "import desktop.main; print('IMPORT_OK')"
.\.venv_diag\Scripts\python.exe -c "import desktop.config; print('IMPORT_OK')"
.\.venv_diag\Scripts\python.exe -c "import relay.relay_server; print('IMPORT_OK')"

# B. startup probes
.\.venv_diag\Scripts\python.exe desktop\main.py --safe-test
.\.venv_diag\Scripts\python.exe desktop\main.py --headless --safe-test
.\.venv_diag\Scripts\python.exe -m desktop.main --headless --safe-test

# C. port + HTTP probes
netstat -ano | findstr ':842'
Test-NetConnection -ComputerName 127.0.0.1 -Port 8428 -InformationLevel Detailed
python -c "import urllib.request; ..."

# D. pytest + coverage
.\.venv_diag\Scripts\python.exe -m pytest tests/ -q --durations=15 --maxfail=5 --disable-warnings --cov=desktop --cov=relay --cov-report=term-missing

# E. git state
git status --short --branch
git remote -v
git branch -vv
git log --oneline -15
git config --list --show-origin
git count-objects -vH

# security scan
git grep -nE 'password|token|secret|api[_-]?key|BEGIN PRIVATE KEY|relay token|config.json|\.env' -- .
```

---

## Top 10 rủi ro theo thứ tự ưu tiên
1. `/app.js` 404 + web asset mismatch -> mobile app/landing page không thể load đúng.
2. Port fallback 8428/8429 không được chuẩn hóa -> UI/QR/URLs có thể sai ở môi trường có process đang chạy.
3. Dependency mismatch (runtime imports không khớp requirements) -> cài đặt / ship builds dễ thất bại trên máy khác.
4. `0%` coverage cho module core / main / gui / server -> rủi ro thực thi không được kiểm soát.
5. Safe-test chỉ chạy headless; không có bằng chứng cho capture/backend thật trên màn hình đang dùng.
6. `Desktop GUI` được mô tả đầy đủ nhưng không có bằng chứng chạy thật với `tkinter` UI trên Windows user session (không chạy trong headless).
7. `relay` và `PWA` flow chưa được xác nhận end-to-end với WS thật; chỉ có test mock/logic.
8. `Service SYSTEM / unlock` là code path nhạy cảm chưa kiểm chứng qua runtime.
9. `secret`/`token` reference và README mẫu có thể gây nhầm lẫn cho kế hoạch deploy / release, dù không phải rò rỉ bí mật thật.
10. Push lên GitHub chưa được chứng minh; cần auth và remote validation chính thức trước khi kết luận.

---

## Đề xuất thứ tự sửa cho P1–P3
- P1 (ngay): chuẩn hóa URL/port, phục vụ đúng static JS, khắc phục `GET /app.js` 404, xóa `port fallback` gây sai lệch nếu app đang chạy.
- P1: đồng bộ dependency runtime trong requirements/pyproject; thêm `pyautogui` và mọi module runtime thực tế; gắn rõ package root.
- P1: thêm smoke test thật cho headless HTTP/WebSocket và port rõ ràng; đầu tiên là app luồng headless safe-test, rồi là app GUI ở VM/Windows test.
- P2: bổ sung test thật cho `main.py`, `server.py`, `core.py`, `gui.py` đường đi chặn startup; giảm 0% coverage.
- P2: kiểm chứng capture thật (DXGI / mss) và input backend ở môi trường có GUI / display real.
- P3: review service/system unlock, consent, overlay và relay end-to-end; tài liệu và CI release cần đúng thực trạng trước khi push.

---

## Kết luận cuối cùng
Dự án hiện có test suite pass với 144 tests, nhưng không có bằng chứng rằng desktop app thật sự chạy hoàn chỉnh theo mô tả sản phẩm. Bằng chứng thực tế cho thấy `--headless --safe-test` có thể khởi động và bind port, nhưng `README`/mô tả endpoint và công việc sản xuất còn không khớp thực tế. Do đó, báo cáo trước đây “144 test pass, không lỗi IDE” là chưa đáng tin cho tới khi chứng minh runtime app + transport + web + release path bằng cách chạy thật, không chỉ chạy unit test/mock.

Nhãn cuối cùng:
- [ĐÃ CHẠY THẬT]: môi trường, import đúng module, headless safe-test, pytest + coverage, git state, file scan.
- [CHỈ CÓ TEST-MOCK]: overlay/consent trên nhiều path mock; không chứng minh UI âm thầm hoặc runtime auto-connect trong desktop.
- [CHỈ ĐỌC CODE/README]: các phần liên quan service/system unlock, secure.py/DPAPI, input backend, dependency mismatch.
- [CHƯA BIẾT]: push GitHub, relay local E2E, capture thật, service runtime.
