"""WebRTC transport with Sprint 3.3 runtime policy helpers.

This layer remains lightweight for non-RTC environments, but it now exposes the codec,
DataChannel, and transport-order decisions that the project plan expects before the real
aiortc integration lands.
"""

from __future__ import annotations

import asyncio
import fractions
import time
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

from .base import Transport

try:
    import av
    from aiortc import (
        RTCConfiguration,
        RTCIceCandidate,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
        VideoStreamTrack,
    )
    from aiortc.sdp import candidate_from_sdp
    _AIORTC_AVAILABLE = True
except ImportError:
    _AIORTC_AVAILABLE = False
    VideoStreamTrack = object  # type: ignore[misc, assignment]


class DesktopVideoStreamTrack(VideoStreamTrack):
    """VideoStreamTrack cho phép stream khung hình desktop trực tiếp từ capturer."""

    def __init__(self, get_frame_fn: Any = None, fps: int = 30) -> None:
        if _AIORTC_AVAILABLE:
            super().__init__()
        self.get_frame_fn = get_frame_fn
        self.fps = max(1, min(60, int(fps)))
        self._time_base = fractions.Fraction(1, 90000)
        self._pts = 0
        self._placeholder: Any = None

    async def recv(self) -> Any:
        pts, time_base = await self.next_timestamp()

        arr = None
        if callable(self.get_frame_fn):
            try:
                arr = self.get_frame_fn()
            except Exception:
                arr = None

        if arr is None:
            if self._placeholder is None:
                self._placeholder = np.zeros((720, 1280, 3), dtype=np.uint8)
            arr = self._placeholder
        else:
            self._placeholder = arr

        # Kiểm tra shape và kích thước
        if hasattr(arr, "shape") and len(arr.shape) == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]  # Bỏ kênh alpha nếu có

        frame = av.VideoFrame.from_ndarray(
            arr, format="bgr24" if getattr(arr, "is_bgr", False) else "rgb24"
        )
        frame.pts = pts
        frame.time_base = time_base
        return frame


class WebRtcPeerSession:
    """Quản lý một phiên kết nối WebRTC PeerConnection giữa Desktop Agent và Viewer."""

    def __init__(
        self,
        conn: Any,
        get_frame_fn: Any = None,
        on_message_fn: Any = None,
        ice_servers: list[Any] | None = None,
        audio_capturer: Any = None,
        audio_allowed: bool = False,
    ) -> None:
        self.conn = conn
        self.get_frame_fn = get_frame_fn
        self.on_message_fn = on_message_fn
        self.audio_capturer = audio_capturer
        self.audio_allowed = bool(audio_allowed)
        self.pc: Any = None
        self.track: Any = None
        self.audio_track: Any = None
        self.data_channels: dict[str, Any] = {}
        self.ice_servers = ice_servers or (
            [
                RTCIceServer(urls=["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]),
                RTCIceServer(
                    urls=[
                        "turn:openrelay.metered.ca:80",
                        "turn:openrelay.metered.ca:443",
                        "turn:openrelay.metered.ca:443?transport=tcp",
                    ],
                    username="openrelay",
                    credential="openrelay",
                ),
            ]
            if _AIORTC_AVAILABLE else []
        )
        self._closed = False

    async def handle_offer(self, offer_sdp: str) -> str:
        if not _AIORTC_AVAILABLE:
            raise RuntimeError("aiortc không có sẵn")

        config = RTCConfiguration(iceServers=self.ice_servers)
        self.pc = RTCPeerConnection(configuration=config)
        self.track = DesktopVideoStreamTrack(self.get_frame_fn, fps=30)
        self.pc.addTrack(self.track)

        # Thêm track âm thanh hệ thống qua WASAPI Loopback (Opus 48kHz Stereo)
        # Only add audio if the offer SDP contains an audio m-line; otherwise
        # setLocalDescription will fail with a direction negotiation error.
        if "m=audio" in offer_sdp:
            try:
                from audio import DesktopAudioStreamTrack
                self.audio_track = DesktopAudioStreamTrack(
                    capturer=self.audio_capturer, allowed=self.audio_allowed
                )
                self.pc.addTrack(self.audio_track)
            except Exception:
                self.audio_track = None

        @self.pc.on("datachannel")
        def on_datachannel(channel: Any) -> None:
            self.data_channels[channel.label] = channel

            @channel.on("message")
            def on_message(message: Any) -> None:
                if isinstance(message, str) and callable(self.on_message_fn):
                    try:
                        import json
                        msg = json.loads(message)
                        asyncio.create_task(self.on_message_fn(self.conn, msg))
                    except Exception:
                        pass

        @self.pc.on("icecandidate")
        async def on_icecandidate(candidate: Any) -> None:
            if candidate and self.conn:
                cand_payload = {
                    "candidate": candidate.candidate,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }
                await self.conn.send_json({"type": "rtc_ice", "candidate": cand_payload})

        @self.pc.on("connectionstatechange")
        def on_connectionstatechange() -> None:
            if self.pc and self.pc.connectionState in ("failed", "closed"):
                asyncio.create_task(self.close())

        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return str(self.pc.localDescription.sdp)

    async def add_ice_candidate(self, candidate_info: dict[str, Any] | str) -> None:
        if not self.pc or self._closed:
            return
        try:
            if isinstance(candidate_info, str):
                import json
                cand_dict = json.loads(candidate_info)
            else:
                cand_dict = candidate_info

            raw_cand = str(cand_dict.get("candidate", ""))
            sdp_mid = cand_dict.get("sdpMid")
            sdp_mline_index = cand_dict.get("sdpMLineIndex")
            if raw_cand:
                cand_line = raw_cand.strip()
                if cand_line.startswith("candidate:"):
                    cand_line = cand_line[len("candidate:"):]
                parsed_cand = candidate_from_sdp(cand_line)
                parsed_cand.sdpMid = sdp_mid
                parsed_cand.sdpMLineIndex = sdp_mline_index
                await self.pc.addIceCandidate(parsed_cand)
        except Exception:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.audio_capturer and hasattr(self.audio_capturer, "stop"):
            try:
                self.audio_capturer.stop()
            except Exception:
                pass
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None



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
    "DesktopVideoStreamTrack",
    "WebRtcPeerSession",
    "WebRtcTransport",
    "build_data_channels",
    "build_webrtc_quality_profile",
    "resolve_transport_order",
]
