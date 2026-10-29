"""Mã hóa mật khẩu bằng DPAPI (Windows) để không lưu plaintext trong config.json.

DPAPI gắn với user + máy, chỉ tiến trình của chính user này giải mã được.
"""
import base64
import ctypes
import hashlib
import hmac
import os
import time
from threading import Lock

from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _free(blob: DATA_BLOB):
    ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(blob.pbData))


def protect(data: str) -> str:
    """Mã hóa chuỗi -> base64 (DPAPI). Fallback: tiền tố plain: nếu DPAPI lỗi."""
    try:
        out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(_blob(data.encode("utf-8"))), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            raise OSError("CryptProtectData failed")
        raw = ctypes.string_at(out.pbData, out.cbData)
        _free(out)
        return base64.b64encode(raw).decode("ascii")
    except Exception:
        return "plain:" + data


def unprotect(enc: str):
    """Giải mã chuỗi đã protect(). Trả về None nếu lỗi."""
    if not enc:
        return None
    if enc.startswith("plain:"):
        return enc[6:]
    try:
        raw = base64.b64decode(enc.encode("ascii"))
        out = DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(_blob(raw)), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        data = ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
        _free(out)
        return data
    except Exception:
        return None


def verify_password(pw: str, enc: str) -> bool:
    stored = unprotect(enc)
    if stored is None:
        return False
    import secrets as _s
    return _s.compare_digest(pw.encode("utf-8"), stored.encode("utf-8"))


class ResumeTokenStore:
    """Simple in-memory one-time session token store."""

    def __init__(self):
        self._tokens = {}
        self._lock = Lock()

    def issue(self, device_id: str, ttl_seconds: int = 120) -> str:
        token = hashlib.sha256(os.urandom(16)).hexdigest()
        expires = time.time() + max(1, int(ttl_seconds))
        with self._lock:
            self._tokens[token] = {"device_id": str(device_id), "expires": expires, "used": False}
        return token

    def consume(self, token: str, device_id: str) -> bool:
        if not token:
            return False
        with self._lock:
            entry = self._tokens.get(token)
            if entry is None:
                return False
            if entry["used"] or entry["device_id"] != str(device_id):
                self._tokens.pop(token, None)
                return False
            if time.time() > entry["expires"]:
                self._tokens.pop(token, None)
                return False
            entry["used"] = True
            self._tokens[token] = entry
            return True

    def invalidate(self, device_id: str):
        with self._lock:
            for token, entry in list(self._tokens.items()):
                if entry.get("device_id") == str(device_id):
                    self._tokens.pop(token, None)


resume_tokens = ResumeTokenStore()


def issue_resume_token(device_id: str, ttl_seconds: int = 120) -> str:
    return resume_tokens.issue(device_id, ttl_seconds)


def consume_resume_token(token: str, device_id: str) -> bool:
    return resume_tokens.consume(token, device_id)
