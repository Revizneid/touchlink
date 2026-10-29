from desktop.transport.webrtc import (
    build_data_channels,
    build_webrtc_quality_profile,
    resolve_transport_order,
)


def test_webrtc_quality_profile_prefers_h264_for_text_content():
    profile = build_webrtc_quality_profile(
        width=1920,
        height=1080,
        content="text",
        is_idle=False,
        bandwidth_kbps=1800,
    )

    assert profile["codec"] == "h264"
    assert profile["tune"] == "stillimage"
    assert profile["fps"] >= 5
    assert profile["bitrate_kbps"] >= 300
    assert profile["keyframe_interval"] >= 2


def test_webrtc_uses_expected_data_channels_and_transport_order():
    channels = build_data_channels()
    assert "input" in channels
    assert "settings" in channels
    assert "clipboard" in channels

    assert resolve_transport_order(["lan_ws", "webrtc", "relay_ws"]) == [
        "lan_ws",
        "webrtc",
        "relay_ws",
    ]
    assert resolve_transport_order(["webrtc", "relay_ws"]) == ["webrtc", "relay_ws"]
