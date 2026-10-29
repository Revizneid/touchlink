"""TouchLinkSvc — Windows service (LocalSystem) cho phép xem/điều khiển từ xa
kể cả khi màn hình bị khóa / ở màn hình đăng nhập (Winlogon).

Cách hoạt động (cùng kỹ thuật VNC/UltraViewer/TeamViewer):
- Service chạy SYSTEM, gắn vào window station WinSta0 và desktop nhập liệu
  hiện hành (Default hoặc Winlogon khi khóa) rồi chụp màn hình + gửi input.
- App chính (phiên người dùng) gọi service qua named pipe \\\\.\\pipe\\TouchLinkSvc:
  gửi 1 dòng JSON, nhận 1 byte loại + 4 byte độ dài + payload.
    ping  -> JSON {ok, locked, safe, version}
    grab  -> payload: [4B len][meta JSON][5B header fw/fh][JPEG]   (meta: left/top/w/h)
    input -> JSON ack (mouse/key/text, giống schema của app)

Chạy thử không cần cài service (phiên người dùng, dùng khi phát triển):
    python svc_main.py --test-server [--safe-test]
Cài service (cần Admin):  TouchLinkSvc.exe install  →  net start TouchLinkSvc
"""
import ctypes
import json
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desktop.security.service_hardening import sanitize_pipe_operation

PIPE_NAME = r'\\.\pipe\TouchLinkSvc'

import config as _cfg
VERSION = _cfg.VERSION

_win = hasattr(ctypes, "windll")

# ---------------------------------------------------------------- desktop attach
DESKTOP_ALL = 0x01FF          # tất cả quyền desktop thường dùng
WINSTA_ALL = 0x00F037F        # WINSTA_ALL_ACCESS | GENERIC_READ | GENERIC_WRITE
UOI_NAME = 2


def attach_winsta():
    """Service mặc định ở window station riêng — phải gắn vào WinSta0 để thấy màn hình."""
    if not _win:
        return None
    u32 = ctypes.windll.user32
    try:
        h = u32.OpenWindowStationW("WinSta0", False, WINSTA_ALL)
        if h and u32.SetProcessWindowStation(h):
            return h
    except Exception:
        pass
    return None


def open_input_desktop():
    """Mở desktop nhập liệu hiện hành (Default / Winlogon khi khóa)."""
    if not _win:
        return None
    return ctypes.windll.user32.OpenInputDesktop(0, True, DESKTOP_ALL)


def input_desktop_name():
    h = open_input_desktop()
    if not h:
        return None
    try:
        n = ctypes.create_unicode_buffer(64)
        need = ctypes.c_uint()
        if ctypes.windll.user32.GetUserObjectInformationW(h, UOI_NAME, n, 128,
                                                          ctypes.byref(need)):
            return n.value
    finally:
        ctypes.windll.user32.CloseDesktop(h)
    return None


def is_locked():
    name = input_desktop_name()
    return bool(name) and name.lower() == "winlogon"


class InputWorker(threading.Thread):
    """Thread chuyên gửi input: SetThreadDesktop sang desktop nhập liệu hiện hành
    trước mỗi thao tác (desktop có thể đổi giữa Default <-> Winlogon)."""

    def __init__(self, safe_test):
        super().__init__(daemon=True, name="svc-input")
        self.q = []
        self.cv = threading.Condition()
        self.safe_test = safe_test

    def post(self, op):
        with self.cv:
            self.q.append(op)
            self.cv.notify_all()

    def run(self):
        import input_control as inp
        inp.SAFE_TEST = self.safe_test
        u32 = ctypes.windll.user32
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                op = self.q.pop(0)
            try:
                h = open_input_desktop()
                if h:
                    if not u32.SetThreadDesktop(h):
                        pass  # giữ desktop cũ nếu đổi không được
                kind = op.get("kind")
                if kind == "mouse":
                    if op.get("rel") is not None:
                        dx, dy = op["rel"]
                        inp.mouse("moverel", int(dx), int(dy))
                    else:
                        x, y = op.get("x"), op.get("y")
                        px = py = None
                        if x is not None and y is not None and op.get("_geom"):
                            g = op["_geom"]
                            px = g["left"] + max(0, min(g["width"] - 1,
                                int(round(float(x) * g["width"] / max(1, g["fw"])))))
                            py = g["top"] + max(0, min(g["height"] - 1,
                                int(round(float(y) * g["height"] / max(1, g["fh"])))))
                        amount = int(op.get("amount", 0) or 0)
                        hamount = int(op.get("hamount", 0) or 0)
                        if op.get("action") == "scroll":
                            if amount:
                                inp.mouse("scroll", px, py, amount=amount)
                            if hamount:
                                inp.mouse("scroll", px, py, amount=hamount,
                                          horizontal=True)
                        else:
                            inp.mouse(op.get("action", "move"), px, py,
                                      button=op.get("button", "left"),
                                      clicks=op.get("clicks", 1))
                elif kind == "key":
                    inp.tap_key(str(op.get("key", "")), op.get("mods") or [])
                elif kind == "text":
                    inp.type_text(str(op.get("text", ""))[:2000])
            except Exception:
                pass


# ---------------------------------------------------------------- capture
_cap_lock = threading.Lock()


def do_grab(monitor, scale, quality):
    import capture
    with _cap_lock:
        jpeg, meta = capture.grab_jpeg(monitor, scale, quality)
    return jpeg, meta


# ---------------------------------------------------------------- pipe protocol
def _resp_json(obj):
    b = json.dumps(obj).encode("utf-8")
    return b"J" + struct.pack("<I", len(b)) + b


def _resp_blob(b):
    return b"B" + struct.pack("<I", len(b)) + b


def _read_exact(h, n):
    out = b""
    while len(out) < n:
        hr, data = win32file.ReadFile(h, n - len(out))
        if not data:
            raise ConnectionError("pipe closed")
        out += data
    return out


def _handle_conn(pipe, worker, safe_test):
    try:
        raw = b""
        while not raw.endswith(b"\n"):
            chunk = win32file.ReadFile(pipe, 65536)[1]
            if not chunk:
                break
            raw += chunk
            if len(raw) > 65536:
                break
        try:
            op = json.loads(raw.decode("utf-8").strip())
        except Exception:
            op = {}
        op = sanitize_pipe_operation(op)
        if op is None:
            win32file.WriteFile(pipe, _resp_json({"ok": False, "error": "bad op or invalid request"}))
            return

        t = op.get("op")

        if t == "ping":
            win32file.WriteFile(pipe, _resp_json({
                "ok": True, "locked": is_locked(), "safe": safe_test,
                "version": VERSION}))

        elif t == "grab":
            try:
                jpeg, meta = do_grab(int(op.get("monitor", 1)),
                                     int(op.get("scale", 100)),
                                     int(op.get("quality", 60)))
                meta_b = json.dumps(meta).encode("utf-8")
                payload = struct.pack("<I", len(meta_b)) + meta_b
                payload += struct.pack(">BHH", 1, meta["fw"], meta["fh"]) + jpeg
                win32file.WriteFile(pipe, _resp_blob(payload))
            except Exception as e:
                win32file.WriteFile(pipe, _resp_json({"ok": False,
                                                      "error": str(e)}))

        elif t == "input":
            worker.post(op)
            win32file.WriteFile(pipe, _resp_json({"ok": True}))
        else:
            win32file.WriteFile(pipe, _resp_json({"ok": False, "error": "bad op"}))
    except Exception:
        pass
    finally:
        try:
            win32file.FlushFileBuffers(pipe)
            win32pipe.DisconnectNamedPipe(pipe)
            win32file.CloseHandle(pipe)
        except Exception:
            pass


def serve_pipes(stop_evt, worker, safe_test):
    while not stop_evt.is_set():
        try:
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME, win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE
                | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES, 1024 * 1024, 1024 * 1024, 0, None)
        except Exception as e:
            time.sleep(2)
            continue
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
        except pywintypes.error:
            pass  # client đã connect trước khi ConnectNamedPipe gọi
        threading.Thread(target=_handle_conn, args=(pipe, worker, safe_test),
                         daemon=True).start()


import pywintypes  # noqa: E402  (dùng ở trên)
import win32file  # noqa: E402
import win32pipe  # noqa: E402


def run_server(safe_test=False, log_fn=print):
    """Khởi động toàn bộ phía service (pipe server + workers)."""
    attach_winsta()
    worker = InputWorker(safe_test)
    worker.start()
    stop = threading.Event()
    threading.Thread(target=serve_pipes, args=(stop, worker, safe_test),
                     daemon=True).start()
    log_fn("TouchLinkSvc pipe server sẵn sàng (safe=%s, locked=%s)"
           % (safe_test, is_locked()))
    return stop


def log_file_fn():
    path = os.path.join(os.path.dirname(os.path.abspath(sys.executable))
                        if getattr(sys, "frozen", False)
                        else os.path.dirname(os.path.abspath(__file__)),
                        "touchlink_svc.log")

    def _log(msg):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (time.strftime("%y-%m-%d %H:%M:%S"), msg))
        except Exception:
            pass
        print(msg, flush=True)
    return _log


# ---------------------------------------------------------------- service wrapper
def run_as_service():
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class TouchLinkSvc(win32serviceutil.ServiceFramework):
        _svc_name_ = "TouchLinkSvc"
        _svc_display_name_ = "TouchLink Service"
        _svc_description_ = ("TouchLink: cho phép xem/điều khiển từ xa khi màn hình "
                             "Windows bị khóa (cùng kỹ thuật VNC/UltraViewer).")

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_evt = win32event.CreateEvent(None, 0, 0, None)
            self.running = True

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_evt)
            self.running = False

        def SvcDoRun(self):
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_name_, ""))
            log = log_file_fn()
            log("Service khởi động")
            safe = os.environ.get("TOUCHLINK_SAFE_TEST", "") == "1"
            stop = run_server(safe, log)
            import win32api
            while self.running:
                rc = win32event.WaitForSingleObject(self.stop_evt, 5000)
                if rc == win32event.WAIT_OBJECT_0:
                    break
            stop.set()
            log("Service dừng")

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(TouchLinkSvc)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(TouchLinkSvc)


def main():
    args = sys.argv[1:]
    safe = "--safe-test" in args
    if "--test-server" in args:
        log = print
        log("TouchLinkSvc TEST-SERVER (phiên người dùng hiện tại)")
        stop = run_server(safe, log)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop.set()
            print("Thoát.")
    else:
        run_as_service()


if __name__ == "__main__":
    main()
