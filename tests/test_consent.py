"""tests/test_consent.py — Kiểm thử logic xác nhận kết nối (mock UI).

Monkey-patch consent._show_dialog để không cần GUI thật:
- Kiểm tra is_consent_required()
- Kiểm tra ask_async() trả đúng kết quả
- Kiểm tra headless → tự động từ chối
- Kiểm tra timeout → từ chối
- Kiểm tra view_only flow
"""
from __future__ import annotations

import asyncio
import sys
import os

import pytest

# Thêm desktop/ vào path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

# Mock core.log và core.broadcast_event trước khi import consent
import types

_core_mock = types.ModuleType("core")
_core_mock.log = lambda msg: None
_core_mock.broadcast_event = lambda *a: None
sys.modules.setdefault("core", _core_mock)

# Mock aiohttp và các dep desktop khác không cần trong test
# Quan trọng: KHÔNG mock 'protocol' — test_protocol.py cần module thật
# Chỉ mock nếu chưa tồn tại; sau khi import consent, xóa stub để không làm ô nhiễm
# collection của test khác.
for _mod in ("aiohttp", "capture", "secure", "input_control",
             "config", "util", "auth", "keepawake", "svcpipe"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

import consent as consent_mod

for _mod in ("aiohttp", "capture", "secure", "input_control",
             "config", "util", "auth", "keepawake", "svcpipe"):
    if _mod in sys.modules and getattr(sys.modules[_mod], "__file__", None) is None:
        sys.modules.pop(_mod, None)


# ---------------------------------------------------------------------------
# Helper: mock _show_dialog
# ---------------------------------------------------------------------------

class _MockDialog:
    """Thay thế consent._show_dialog trong tests."""

    def __init__(self, result: str = "allow") -> None:
        self.result = result
        self.called = False
        self.last_args: tuple = ()

    def __call__(self, viewer_name: str, is_relay: bool, timeout_s: int) -> str:
        self.called = True
        self.last_args = (viewer_name, is_relay, timeout_s)
        return self.result

    def patch(self):
        consent_mod._show_dialog = self
        return self


class _RestoreDialog:
    def __init__(self):
        self._orig = consent_mod._show_dialog

    def __enter__(self):
        return self

    def __exit__(self, *_):
        consent_mod._show_dialog = self._orig


# ---------------------------------------------------------------------------
# 1. is_consent_required
# ---------------------------------------------------------------------------

class TestIsConsentRequired:
    def test_default_relay_true(self):
        """Mặc định: relay bật xác nhận."""
        assert consent_mod.is_consent_required({}, is_relay=True) is True

    def test_default_lan_false(self):
        """Mặc định: LAN tắt xác nhận."""
        assert consent_mod.is_consent_required({}, is_relay=False) is False

    def test_cfg_override_relay_false(self):
        """Config tắt xác nhận relay."""
        assert consent_mod.is_consent_required(
            {"consent_relay": False}, is_relay=True) is False

    def test_cfg_override_lan_true(self):
        """Config bật xác nhận LAN."""
        assert consent_mod.is_consent_required(
            {"consent_lan": True}, is_relay=False) is True

    def test_cfg_relay_true_explicit(self):
        """Config rõ ràng bật relay."""
        assert consent_mod.is_consent_required(
            {"consent_relay": True}, is_relay=True) is True


# ---------------------------------------------------------------------------
# 2. ask_async — mock dialog
# ---------------------------------------------------------------------------

class TestAskAsync:
    @pytest.fixture(autouse=True)
    def restore(self):
        orig = consent_mod._show_dialog
        yield
        consent_mod._show_dialog = orig

    async def test_allow_result(self):
        """Dialog trả allow → ask_async trả allow."""
        mock = _MockDialog("allow").patch()
        result = await consent_mod.ask_async(
            "TestViewer", is_relay=True, cfg={}, headless=False)
        assert result == consent_mod.ALLOW
        assert mock.called

    async def test_deny_result(self):
        """Dialog trả deny → ask_async trả deny."""
        _MockDialog("deny").patch()
        result = await consent_mod.ask_async(
            "TestViewer", is_relay=True, cfg={}, headless=False)
        assert result == consent_mod.DENY

    async def test_view_only_result(self):
        """Dialog trả view_only → ask_async trả view_only."""
        _MockDialog("view_only").patch()
        result = await consent_mod.ask_async(
            "TestViewer", is_relay=True, cfg={}, headless=False)
        assert result == consent_mod.VIEW_ONLY

    async def test_viewer_name_passed(self):
        """viewer_name được truyền vào dialog."""
        mock = _MockDialog("allow").patch()
        await consent_mod.ask_async(
            "Relay viewer (1.2.3.x)", is_relay=True, cfg={}, headless=False)
        assert mock.last_args[0] == "Relay viewer (1.2.3.x)"

    async def test_is_relay_flag_passed(self):
        """is_relay flag được truyền vào dialog."""
        mock = _MockDialog("allow").patch()
        # Phải bật consent_lan=True thì dialog mới được gọi với is_relay=False
        await consent_mod.ask_async("v", is_relay=False,
                                    cfg={"consent_lan": True}, headless=False)
        assert mock.called, "Dialog phải được gọi khi consent_lan=True"
        assert mock.last_args[1] is False


    async def test_timeout_passed(self):
        """Timeout CONSENT_TIMEOUT_S được truyền vào dialog."""
        mock = _MockDialog("allow").patch()
        await consent_mod.ask_async("v", is_relay=True, cfg={}, headless=False)
        assert mock.last_args[2] == consent_mod.CONSENT_TIMEOUT_S

    async def test_consent_not_required_lan(self):
        """LAN không yêu cầu consent → không gọi dialog → trả allow."""
        mock = _MockDialog("deny").patch()  # sẽ trả deny nếu được gọi
        result = await consent_mod.ask_async(
            "LAN viewer", is_relay=False,
            cfg={"consent_lan": False}, headless=False)
        assert result == consent_mod.ALLOW
        assert not mock.called, "Dialog không nên được gọi khi consent_required=False"

    async def test_consent_required_lan_when_enabled(self):
        """Khi consent_lan=True: dialog được gọi."""
        mock = _MockDialog("allow").patch()
        result = await consent_mod.ask_async(
            "LAN viewer", is_relay=False,
            cfg={"consent_lan": True}, headless=False)
        assert mock.called
        assert result == consent_mod.ALLOW


# ---------------------------------------------------------------------------
# 3. Headless mode → tự động từ chối
# ---------------------------------------------------------------------------

class TestHeadlessMode:
    @pytest.fixture(autouse=True)
    def restore(self):
        orig = consent_mod._show_dialog
        yield
        consent_mod._show_dialog = orig

    async def test_headless_always_deny(self):
        """Headless: bất kể config → từ chối, không hiện dialog."""
        mock = _MockDialog("allow").patch()
        result = await consent_mod.ask_async(
            "TestViewer", is_relay=True, cfg={"consent_relay": True}, headless=True)
        assert result == consent_mod.DENY
        assert not mock.called, "Dialog không được gọi trong headless"

    async def test_headless_deny_regardless_cfg(self):
        """Headless với mọi config đều từ chối."""
        mock = _MockDialog("allow").patch()
        for cfg in [
            {"consent_relay": False},
            {"consent_relay": True},
            {},
        ]:
            result = await consent_mod.ask_async(
                "v", is_relay=True, cfg=cfg, headless=True)
            assert result == consent_mod.DENY
        assert not mock.called


# ---------------------------------------------------------------------------
# 4. Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_constants_defined(self):
        assert consent_mod.ALLOW == "allow"
        assert consent_mod.VIEW_ONLY == "view_only"
        assert consent_mod.DENY == "deny"

    def test_timeout_is_30s(self):
        assert consent_mod.CONSENT_TIMEOUT_S == 30
