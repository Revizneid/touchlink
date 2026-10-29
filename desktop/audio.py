"""Audio pipeline helpers for Sprint 4.1.

This module models the desktop-side loopback capture and Opus configuration needed for
future WebRTC audio tracks. The implementation remains dependency-light and testable so it
works even when real audio libraries are absent in CI or local developer shells.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


SUPPORTED_AUDIO_CODECS = {"opus", "aac", "pcm"}
VALID_SAMPLE_RATES = {32000, 44100, 48000}
VALID_CHANNELS = {1, 2}
AUDIO_BITRATE_RANGE = (32, 96)


@dataclass
class AudioSessionConfig:
    enabled: bool = False
    codec: str = "opus"
    capture_source: str = "loopback"
    sample_rate_hz: int = 48000
    channels: int = 2
    bitrate_kbps: int = 48
    frame_size: int = 960
    audio_device: Optional[str] = None
    permission_required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "enabled": bool(self.enabled),
            "codec": str(self.codec).lower(),
            "capture_source": str(self.capture_source).lower(),
            "sample_rate_hz": int(self.sample_rate_hz),
            "channels": int(self.channels),
            "bitrate_kbps": int(self.bitrate_kbps),
            "frame_size": int(self.frame_size),
            "audio_device": self.audio_device,
            "permission_required": bool(self.permission_required),
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


def normalize_audio_config(raw: Dict[str, Any] | AudioSessionConfig | None) -> Dict[str, Any]:
    if isinstance(raw, AudioSessionConfig):
        return raw.to_dict()
    if not isinstance(raw, dict):
        return {}
    config = dict(raw)
    config["enabled"] = bool(config.get("enabled", False))
    config["codec"] = str(config.get("codec", "opus")).lower()
    config["capture_source"] = str(config.get("capture_source", "loopback")).lower()
    config["sample_rate_hz"] = int(config.get("sample_rate_hz", 48000))
    config["channels"] = int(config.get("channels", 2))
    config["bitrate_kbps"] = int(config.get("bitrate_kbps", 48))
    config["frame_size"] = int(config.get("frame_size", 960))
    if config.get("audio_device") is not None:
        config["audio_device"] = str(config["audio_device"])
    config["permission_required"] = bool(config.get("permission_required", True))
    return config


def validate_audio_config(config: Dict[str, Any] | AudioSessionConfig | None) -> bool:
    cfg = normalize_audio_config(config)
    if not cfg:
        return False
    codec = cfg.get("codec", "opus")
    if codec not in SUPPORTED_AUDIO_CODECS:
        return False
    if codec == "pcm":
        return False
    sample_rate = int(cfg.get("sample_rate_hz", 0))
    channels = int(cfg.get("channels", 0))
    bitrate = int(cfg.get("bitrate_kbps", 0))
    if sample_rate not in VALID_SAMPLE_RATES:
        return False
    if channels not in VALID_CHANNELS:
        return False
    low, high = AUDIO_BITRATE_RANGE
    if bitrate < low or bitrate > high:
        return False
    capture_source = str(cfg.get("capture_source", "loopback")).lower()
    if capture_source not in {"loopback", "system", "default"}:
        return False
    return True


def build_loopback_audio_profile(
    *,
    sample_rate_hz: int = 48000,
    channels: int = 2,
    bitrate_kbps: int = 48,
    enabled: bool = True,
    device: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the default loopback audio settings for the desktop agent."""
    profile = {
        "enabled": bool(enabled),
        "codec": "opus",
        "capture_source": "loopback",
        "sample_rate_hz": int(sample_rate_hz),
        "channels": int(channels),
        "bitrate_kbps": int(bitrate_kbps),
        "frame_size": 960,
        "audio_device": device,
        "permission_required": True,
    }
    if not validate_audio_config(profile):
        profile["sample_rate_hz"] = 48000
        profile["channels"] = 2
        profile["bitrate_kbps"] = 48
    return profile


def build_audio_session_config(**kwargs: Any) -> AudioSessionConfig:
    raw = build_loopback_audio_profile(**kwargs)
    return AudioSessionConfig(
        enabled=bool(raw.get("enabled", False)),
        codec=str(raw.get("codec", "opus")),
        capture_source=str(raw.get("capture_source", "loopback")),
        sample_rate_hz=int(raw.get("sample_rate_hz", 48000)),
        channels=int(raw.get("channels", 2)),
        bitrate_kbps=int(raw.get("bitrate_kbps", 48)),
        frame_size=int(raw.get("frame_size", 960)),
        audio_device=kwargs.get("device"),
        permission_required=True,
    )


__all__ = [
    "AudioSessionConfig",
    "AUDIO_BITRATE_RANGE",
    "SUPPORTED_AUDIO_CODECS",
    "build_audio_session_config",
    "build_loopback_audio_profile",
    "validate_audio_config",
]
