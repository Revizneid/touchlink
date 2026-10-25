"""Cấu hình TouchLink — lưu/đọc config.json, sinh ID và mật khẩu."""
import json
import os
import secrets
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
VERSION = "2.1.0"
DEFAULT_PORT = 8420

# Khi chạy dạng exe đóng gói (PyInstaller): config.json nằm CẠNH file exe (portable)
FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else APP_DIR
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "device_id": None,
    "password_enc": None,
    "port": DEFAULT_PORT,
    # Mặc định bật relay công cộng để mobile kết nối qua internet ngay lần chạy đầu
    "relay_url": "wss://touchlink-relay.onrender.com/ws",
    "relay_enabled": True,
}


def load():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def save(cfg):
    tmp = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(tmp, f, indent=2, ensure_ascii=False)


def gen_device_id():
    # 9 chữ số, tránh 0/1 dễ gây nhầm
    return "".join(secrets.choice("23456789") for _ in range(9))


def gen_password():
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))
