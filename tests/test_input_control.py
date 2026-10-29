"""Unit tests cho input backend SendInput.

Nhắm vào mapping phím, tọa độ đa màn hình, ký tự Unicode ngoài BMP và
release khi ngắt kết nối.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

from input import sendinput


class TestSendInputBackend(unittest.TestCase):
    def setUp(self):
        self.user32 = MagicMock()
        self.windll = types.SimpleNamespace(user32=self.user32)

    def test_key_map_and_media_keys(self):
        ctrl = sendinput.resolve_key("ctrl")
        enter = sendinput.resolve_key("enter")
        up = sendinput.resolve_key("arrowup")
        f12 = sendinput.resolve_key("f12")
        win = sendinput.resolve_key("win")
        self.assertEqual(ctrl["vk"], 0x11)
        self.assertEqual(ctrl["scan"], 0x1D)
        self.assertEqual(enter["scan"], 0x1C)
        self.assertTrue(up["extended"])
        self.assertEqual(f12["vk"], 0x7B)
        self.assertEqual(win["vk"], 0x5B)

    def test_normalize_absolute_position_for_virtual_desktop(self):
        with patch.object(sendinput.ctypes, "windll", self.windll, create=True):
            with patch.object(sendinput, "get_system_metrics", side_effect=[-1920, 0, 3840, 1080, 0, 0, 0, 0]):
                normalized = sendinput.normalize_absolute_xy(1920, 540, -1920, 0, 3840, 1080)
                self.assertEqual(normalized, (65535, 32767))

                normalized2 = sendinput.normalize_absolute_xy(100, 50, 0, 0, 3840, 1080)
                self.assertEqual(normalized2, (1706, 3034))

    def test_release_all_clears_held_inputs(self):
        backend = sendinput.WindowsSendInputBackend(user32=self.user32)
        backend.key_down("ctrl")
        backend.mouse_down("left")
        backend.release_all()
        self.assertEqual(backend._held_modifiers, set())
        self.assertEqual(backend._held_buttons, set())
        self.assertGreaterEqual(self.user32.SendInput.call_count, 3)

    def test_surrogate_pair_unicode_is_split_correctly(self):
        backend = sendinput.WindowsSendInputBackend(user32=self.user32)
        with patch.object(sendinput.ctypes, "windll", self.windll, create=True):
            backend.type_text("𐍈")
        self.assertGreaterEqual(self.user32.SendInput.call_count, 4)


if __name__ == "__main__":
    unittest.main()
