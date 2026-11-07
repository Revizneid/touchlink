"""Audio pipeline helpers for Sprint 4.1.

This module models the desktop-side loopback capture and Opus configuration needed for
future WebRTC audio tracks. The implementation remains dependency-light and testable so it
works even when real audio libraries are absent in CI or local developer shells.
"""

from __future__ import annotations

import asyncio
import fractions
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:
    import soundcard as sc
    _SOUNDCARD_AVAILABLE = True
except Exception:
    _SOUNDCARD_AVAILABLE = False

try:
    import av
    from aiortc import AudioStreamTrack
    _AIORTC_AUDIO_AVAILABLE = True
except Exception:
    _AIORTC_AUDIO_AVAILABLE = False
    AudioStreamTrack = object  # type: ignore[misc, assignment]

SUPPORTED_AUDIO_CODECS = {"opus", "aac", "pcm"}
VALID_SAMPLE_RATES = {32000, 44100, 48000}
VALID_CHANNELS = {1, 2}
AUDIO_BITRATE_RANGE = (32, 96)


class WasapiLoopbackCapturer:
    """Thu âm thanh hệ thống Windows qua WASAPI Loopback (48kHz, stereo, 20ms block = 960 samples)."""

    def __init__(self, sample_rate: int = 48000, channels: int = 2, block_size: int = 960) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.block_size = int(block_size)
        self._running = False
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=10)
        self._lock = threading.Lock()

    @staticmethod
    def is_available() -> bool:
        if not _SOUNDCARD_AVAILABLE:
            return False
        try:
            spk = sc.default_speaker()
            return spk is not None
        except Exception:
            return False

    def start(self) -> bool:
        if not self.is_available():
            return False
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._thread = threading.Thread(
                target=self._record_loop, daemon=True, name="wasapi_loopback"
            )
            self._thread.start()
            return True

    def _record_loop(self) -> None:
        try:
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            with mic.recorder(
                samplerate=self.sample_rate, channels=self.channels, blocksize=self.block_size
            ) as rec:
                while self._running:
                    data = rec.record(numframes=self.block_size)
                    chunk = data.astype(np.float32)
                    if not self._queue.full():
                        self._queue.put_nowait(chunk)
                    else:
                        try:
                            self._queue.get_nowait()
                            self._queue.put_nowait(chunk)
                        except Exception:
                            pass
        except Exception:
            self._running = False

    def read_chunk(self) -> np.ndarray:
        """Đọc 1 chunk float32 (block_size, channels). Nếu không có hoặc im lặng thì trả về zeros."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return np.zeros((self.block_size, self.channels), dtype=np.float32)

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break


class DesktopAudioStreamTrack(AudioStreamTrack):
    """AudioStreamTrack cho WebRTC, truyền âm thanh Opus 48kHz Stereo qua RTC MediaStream."""

    def __init__(
        self, capturer: WasapiLoopbackCapturer | None = None, allowed: bool = False
    ) -> None:
        if _AIORTC_AUDIO_AVAILABLE:
            super().__init__()
        self.capturer = capturer
        self.allowed = bool(allowed)
        self.sample_rate = 48000
        self.channels = 2
        self.block_size = 960  # 20ms tương ứng với 48kHz
        self._time_base = fractions.Fraction(1, 48000)
        self._pts = 0
        self._start: float | None = None

    async def recv(self) -> Any:
        if self._start is None:
            self._start = time.time()
            self._pts = 0
        else:
            self._pts += self.block_size
            wait = self._start + (self._pts / self.sample_rate) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        pts = self._pts
        time_base = self._time_base

        chunk: np.ndarray | None = None
        if self.allowed and self.capturer is not None:
            try:
                chunk = self.capturer.read_chunk()
            except Exception:
                chunk = None

        if chunk is None or not hasattr(chunk, "shape"):
            chunk = np.zeros((self.block_size, self.channels), dtype=np.float32)

        # Chuyển (block_size, channels) sang planar (channels, block_size) cho format 'fltp'
        planar_data = np.ascontiguousarray(chunk.T, dtype=np.float32)
        frame = av.AudioFrame.from_ndarray(planar_data, format="fltp", layout="stereo")
        frame.sample_rate = self.sample_rate
        frame.pts = pts
        frame.time_base = self._time_base
        return frame


@dataclass
class AudioSessionConfig:
    enabled: bool = False
    codec: str = "opus"
    capture_source: str = "loopback"
    sample_rate_hz: int = 48000
    channels: int = 2
    bitrate_kbps: int = 48
    frame_size: int = 960
    audio_device: str | None = None
    permission_required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
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


def normalize_audio_config(raw: dict[str, Any] | AudioSessionConfig | None) -> dict[str, Any]:
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


def validate_audio_config(config: dict[str, Any] | AudioSessionConfig | None) -> bool:
    if not config:
        return False
    cfg = normalize_audio_config(config)
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
    return capture_source in {"loopback", "system", "default"}


def build_loopback_audio_profile(
    *,
    sample_rate_hz: int = 48000,
    channels: int = 2,
    bitrate_kbps: int = 48,
    enabled: bool = True,
    device: str | None = None,
) -> dict[str, Any]:
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
    "AUDIO_BITRATE_RANGE",
    "DesktopAudioStreamTrack",
    "SUPPORTED_AUDIO_CODECS",
    "AudioSessionConfig",
    "WasapiLoopbackCapturer",
    "build_audio_session_config",
    "build_loopback_audio_profile",
    "validate_audio_config",
]
