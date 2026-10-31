"""WebRTC transport with Sprint 3.3 runtime policy helpers.

This layer remains lightweight for non-RTC environments, but it now exposes the codec,
DataChannel, and transport-order decisions that the project plan expects before the real
aiortc integration lands.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .base import Transport


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _normalize_transport_name(name: str) -> str:
    return str(name).strip().lower().replace("-", "_")


def resolve_transport_order(transports: Iterable[str] | None) -> list[str]:
    """Return the supported transport order with duplicates removed."""
    seen = set()
    ordered: list[str] = []
    for raw in transports or []:
        name = _normalize_transport_name(raw)
        if name in {"lan_ws", "webrtc", "relay_ws"} and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def build_data_channels() -> dict[str, dict[str, Any]]:
    """Return the channel layout used for control, input, settings, and clipboard."""
    return {
        "input": {"label": "input", "ordered": True, "reliable": True, "direction": "bidirectional"},
        "settings": {"label": "settings", "ordered": True, "reliable": True, "direction": "bidirectional"},
        "clipboard": {"label": "clipboard", "ordered": True, "reliable": True, "direction": "bidirectional"},
        "chat": {"label": "chat", "ordered": True, "reliable": True, "direction": "bidirectional"},
        "ping": {"label": "ping", "ordered": False, "reliable": False, "direction": "bidirectional"},
        "viewer": {"label": "viewer", "ordered": True, "reliable": True, "direction": "outbound"},
    }


def build_webrtc_quality_profile(
    *,
    width: int = 1920,
    height: int = 1080,
    content: str = "screen",
    is_idle: bool = False,
    bandwidth_kbps: int = 1500,
) -> dict[str, Any]:
    """Return a WebRTC quality profile aligned with the Sprint 3.3 plan."""
    content_name = (content or "screen").lower()
    area = max(1, int(width)) * max(1, int(height))
    codec = "h264"
    tune = "stillimage" if content_name == "text" else "zerolatency"
    fps = 2 if is_idle else (5 if content_name == "text" else 15)
    if area >= 1920 * 1080:
        base_bitrate = 2200 if content_name == "text" else 3200
    elif area >= 1280 * 720:
        base_bitrate = 1400 if content_name == "text" else 2200
    else:
        base_bitrate = 900 if content_name == "text" else 1400

    if bandwidth_kbps <= 600:
        base_bitrate = 300
    elif bandwidth_kbps <= 1200:
        base_bitrate = 700
    bitrate_kbps = _clamp(base_bitrate, 300, 8000)
    keyframe_interval = 2 if content_name == "text" else 5

    return {
        "codec": codec,
        "tune": tune,
        "fps": fps,
        "bitrate_kbps": bitrate_kbps,
        "keyframe_interval": keyframe_interval,
        "content": content_name,
        "width": int(width),
        "height": int(height),
        "bandwidth_kbps": int(bandwidth_kbps),
    }


class WebRtcTransport(Transport):
    def __init__(self, *, signaling_url: str | None = None, preferred_codec: str = "h264") -> None:
        super().__init__()
        self.signaling_url = signaling_url
        self.preferred_codec = preferred_codec
        self.data_channels = build_data_channels()
        self.quality_profile = build_webrtc_quality_profile()
        self._pc = None

    @staticmethod
    def is_available() -> bool:
        try:
            import aiortc  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> bool:
        if not self.is_available():
            raise RuntimeError("WebRTC transport requires aiortc to be installed.")
        self._started = True
        return True

    def configure_quality(self, **kwargs: Any) -> dict[str, Any]:
        self.quality_profile = build_webrtc_quality_profile(**kwargs)
        self.preferred_codec = self.quality_profile["codec"]
        return self.quality_profile

    def send_video(self, frame: Any) -> Any:
        return {
            "transport": "webrtc",
            "video_frame": frame,
            "codec": self.preferred_codec,
            "quality": self.quality_profile,
        }

    def send_data(self, message: Any) -> Any:
        if isinstance(message, Mapping):
            channel_type = str(message.get("type") or "input")
            if self.data_channels.get(channel_type):
                if callable(self._data_callback):
                    self._data_callback(message)
                return {"transport": "webrtc", "channel": channel_type, "sent": message}
        if callable(self._data_callback):
            self._data_callback(message)
        return {"transport": "webrtc", "sent": message}

    def stats(self) -> dict[str, Any]:
        return {
            "transport": "webrtc",
            "started": self.started,
            "available": self.is_available(),
            "preferred_codec": self.preferred_codec,
            "data_channels": list(self.data_channels.keys()),
            "quality_profile": self.quality_profile,
        }

    def close(self) -> None:
        self._started = False
        self._pc = None


__all__ = [
    "WebRtcTransport",
    "build_data_channels",
    "build_webrtc_quality_profile",
    "resolve_transport_order",
]
