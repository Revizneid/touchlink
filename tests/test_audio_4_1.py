from desktop.audio import (
    AudioSessionConfig,
    build_loopback_audio_profile,
    validate_audio_config,
)


def test_loopback_audio_profile_uses_opus_and_loopback_defaults():
    cfg = build_loopback_audio_profile(sample_rate_hz=48000, channels=2, bitrate_kbps=48)
    assert cfg["codec"] == "opus"
    assert cfg["capture_source"] == "loopback"
    assert cfg["sample_rate_hz"] == 48000
    assert cfg["channels"] == 2
    assert 32 <= cfg["bitrate_kbps"] <= 96
    assert validate_audio_config(cfg) is True


def test_audio_session_config_rejects_invalid_values():
    session = AudioSessionConfig(enabled=True, codec="opus", sample_rate_hz=44100, channels=2, bitrate_kbps=96)
    assert session.enabled is True
    assert session.codec == "opus"
    assert validate_audio_config(session.to_dict()) is True
    assert validate_audio_config({"codec": "pcm", "sample_rate_hz": 0, "channels": 0}) is False
