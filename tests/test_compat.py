from desktop.compat import build_mobile_viewport_policy, detect_browser_family


def test_ios_profile_requires_playsinline_and_visual_viewport():
    profile = build_mobile_viewport_policy("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
    assert profile["family"] == "ios"
    assert profile["playsinline"] is True
    assert profile["uses_visual_viewport"] is True
    assert profile["hide_address_bar"] is True
    assert profile["keyboard_adjustment"] == "visualViewport"


def test_android_profile_handles_chrome_and_wake_lock():
    profile = build_mobile_viewport_policy("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36")
    assert profile["family"] == "android"
    assert profile["playsinline"] is True
    assert profile["supports_wake_lock"] is True
    assert profile["keyboard_adjustment"] in {"viewport", "visualViewport"}


def test_detect_browser_family_is_stable_for_unknown_agents():
    assert detect_browser_family("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "desktop"
