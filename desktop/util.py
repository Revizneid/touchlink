"""Hàm tiện ích dùng chung cho desktop (main.py + gui.py)."""
import os
import socket
import sys

import secure


def lan_ips():
    ips = set()
    try:
        _host, _alias, addrs = socket.gethostbyname_ex(socket.gethostname())
        ips.update(a for a in addrs if not a.startswith("127."))
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


def build_urls(cfg):
    urls = []
    for ip in lan_ips():
        urls.append("http://%s:%s" % (ip, cfg.get("port")))
    return urls or ["http://127.0.0.1:%s" % cfg.get("port")]


def password_plain(cfg):
    return secure.unprotect(cfg.get("password_enc") or "") or "?"


def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
