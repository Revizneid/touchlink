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

    def test_mouse_down_and_click_moves_before_button_action(self):
        import input_control
        mock_backend = MagicMock()
        with patch.object(input_control, "_get_backend", return_value=mock_backend):
            input_control.mouse("down", 500, 300, button="left")
            mock_backend.move_absolute.assert_called_with(500, 300)
            mock_backend.mouse_down.assert_called_with("left")

            mock_backend.reset_mock()
            input_control.mouse("click", 800, 600, button="left", clicks=1)
            mock_backend.move_absolute.assert_called_with(800, 600)
            mock_backend.click.assert_called_with("left", 1)

            mock_backend.reset_mock()
            input_control.mouse("up", 850, 650, button="left")
            mock_backend.move_absolute.assert_called_with(850, 650)
            mock_backend.mouse_up.assert_called_with("left")


if __name__ == "__main__":
    unittest.main()
