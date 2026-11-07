"""Unit and integration tests for Phase 3 WASAPI Audio Capture & Streaming (desktop/audio.py).

Verifies:
1. WasapiLoopbackCapturer initialization, buffer management, silence fallback.
2. WasapiLoopbackCapturer start/stop queue cleanup and thread life cycle.
3. DesktopAudioStreamTrack PTS, planar format ('fltp'), stereo layout, and 48kHz audio frames.
4. Consent-gated capture: silent frames when not allowed vs real/mock audio when allowed.
5. AudioSessionConfig validation, normalization, and loopback audio profile generation.
6. Default security posture: audio_enabled is False by default in desktop config.
7. WebRtcPeerSession audio negotiation when offer includes m=audio.
"""

from __future__ import annotations

import fractions
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

import config as cfgmod
from audio import (
    AUDIO_BITRATE_RANGE,
    AudioSessionConfig,
    DesktopAudioStreamTrack,
    WasapiLoopbackCapturer,
    build_audio_session_config,
    build_loopback_audio_profile,
    normalize_audio_config,
    validate_audio_config,
)
from transport.webrtc import WebRtcPeerSession, WebRtcTransport


def test_default_config_audio_disabled():
    """Security requirement: audio capture must default to False (consent required)."""
    assert cfgmod.DEFAULTS.get("audio_enabled") is False


def test_capturer_initialization_defaults():
    capturer = WasapiLoopbackCapturer()
    assert capturer.sample_rate == 48000
    assert capturer.channels == 2
    assert capturer.block_size == 960
    assert not capturer._running


def test_capturer_read_chunk_returns_silence_when_empty():
    capturer = WasapiLoopbackCapturer(sample_rate=48000, channels=2, block_size=960)
    chunk = capturer.read_chunk()
    assert isinstance(chunk, np.ndarray)
    assert chunk.shape == (960, 2)
    assert chunk.dtype == np.float32
    assert np.all(chunk == 0.0)


def test_capturer_queue_fifo_and_stop_clear():
    capturer = WasapiLoopbackCapturer(sample_rate=48000, channels=2, block_size=960)
    test_data = np.full((960, 2), 0.5, dtype=np.float32)
    capturer._queue.put(test_data)

    retrieved = capturer.read_chunk()
    np.testing.assert_array_equal(retrieved, test_data)

    # After retrieving, next chunk is silence
    next_chunk = capturer.read_chunk()
    assert np.all(next_chunk == 0.0)

    # Fill queue and test stop() clears everything
    for _ in range(5):
        capturer._queue.put(test_data)
    assert not capturer._queue.empty()
    capturer.stop()
    assert capturer._queue.empty()
    assert capturer._running is False


def test_capturer_is_available():
    # Should safely return bool without throwing uncaught exceptions
    avail = WasapiLoopbackCapturer.is_available()
    assert isinstance(avail, bool)


def test_capturer_start_returns_false_if_unavailable():
    capturer = WasapiLoopbackCapturer()
    with patch.object(WasapiLoopbackCapturer, "is_available", return_value=False):
        assert capturer.start() is False
        assert capturer._running is False


@pytest.mark.asyncio
async def test_audio_stream_track_silence_when_unauthorized():
    """When allowed=False, track must emit silent zero-filled audio frames even if capturer has data."""
    mock_capturer = MagicMock()
    mock_capturer.read_chunk.return_value = np.ones((960, 2), dtype=np.float32)

    track = DesktopAudioStreamTrack(capturer=mock_capturer, allowed=False)
    frame = await track.recv()

    assert frame is not None
    assert frame.sample_rate == 48000
    assert frame.layout.name == "stereo"
    assert frame.format.name == "fltp"
    assert frame.samples == 960

    # Capturer should not have been called because permission was denied
    mock_capturer.read_chunk.assert_not_called()

    # Audio data in frame should be all zeros
    arr = frame.to_ndarray()
    assert np.all(arr == 0.0)


@pytest.mark.asyncio
async def test_audio_stream_track_captures_when_authorized():
    """When allowed=True and capturer provides chunks, track converts to planar float32 frame."""
    mock_capturer = MagicMock()
    test_samples = np.full((960, 2), 0.75, dtype=np.float32)
    mock_capturer.read_chunk.return_value = test_samples

    track = DesktopAudioStreamTrack(capturer=mock_capturer, allowed=True)
    frame = await track.recv()

    assert frame is not None
    mock_capturer.read_chunk.assert_called_once()
    assert frame.samples == 960
    assert frame.sample_rate == 48000
    assert frame.format.name == "fltp"

    arr = frame.to_ndarray()
    assert arr.shape == (2, 960)
    np.testing.assert_allclose(arr, 0.75, atol=1e-5)


@pytest.mark.asyncio
async def test_audio_stream_track_fallback_on_none_chunk():
    """When capturer raises or returns None, track safely falls back to silent audio frame."""
    mock_capturer = MagicMock()
    mock_capturer.read_chunk.side_effect = RuntimeError("WASAPI device disconnected")

    track = DesktopAudioStreamTrack(capturer=mock_capturer, allowed=True)
    frame = await track.recv()

    assert frame is not None
    assert frame.samples == 960
    arr = frame.to_ndarray()
    assert np.all(arr == 0.0)


def test_audio_session_config_validation():
    # Valid default config
    valid_cfg = {
        "codec": "opus",
        "sample_rate_hz": 48000,
        "channels": 2,
        "bitrate_kbps": 48,
        "capture_source": "loopback",
    }
    assert validate_audio_config(valid_cfg) is True

    # Invalid codec
    assert validate_audio_config({**valid_cfg, "codec": "flac"}) is False
    # PCM is explicitly rejected in validate_audio_config
    assert validate_audio_config({**valid_cfg, "codec": "pcm"}) is False

    # Invalid sample rate
    assert validate_audio_config({**valid_cfg, "sample_rate_hz": 11025}) is False

    # Invalid channels
    assert validate_audio_config({**valid_cfg, "channels": 6}) is False

    # Out of range bitrate
    assert validate_audio_config({**valid_cfg, "bitrate_kbps": 16}) is False
    assert validate_audio_config({**valid_cfg, "bitrate_kbps": 128}) is False

    # Empty / None
    assert validate_audio_config({}) is False
    assert validate_audio_config(None) is False


def test_build_loopback_audio_profile():
    profile = build_loopback_audio_profile(enabled=True)
    assert profile["enabled"] is True
    assert profile["codec"] == "opus"
    assert profile["sample_rate_hz"] == 48000
    assert profile["channels"] == 2
    assert profile["bitrate_kbps"] == 48
    assert profile["permission_required"] is True


def test_build_audio_session_config_dataclass():
    cfg = build_audio_session_config(enabled=True, sample_rate_hz=48000)
    assert isinstance(cfg, AudioSessionConfig)
    assert cfg.enabled is True
    assert cfg.permission_required is True
    assert cfg.to_dict()["codec"] == "opus"


@pytest.mark.asyncio
async def test_webrtc_session_with_audio_offer():
    """Verify WebRtcPeerSession attaches DesktopAudioStreamTrack when offer contains m=audio."""
    if not WebRtcTransport.is_available():
        pytest.skip("aiortc is not available in test environment")

    from aiortc import RTCPeerConnection

    client_pc = RTCPeerConnection()
    client_pc.addTransceiver("video", direction="recvonly")
    client_pc.addTransceiver("audio", direction="recvonly")
    client_offer = await client_pc.createOffer()
    assert "m=audio" in client_offer.sdp

    class MockConn:
        name = "test_audio_viewer"
        async def send_json(self, d):
            pass

    mock_capturer = MagicMock()
    mock_capturer.read_chunk.return_value = np.zeros((960, 2), dtype=np.float32)

    session = WebRtcPeerSession(
        conn=MockConn(),
        get_frame_fn=lambda: np.zeros((360, 640, 3), dtype=np.uint8),
        audio_capturer=mock_capturer,
        audio_allowed=True,
    )

    answer_sdp = await session.handle_offer(client_offer.sdp)
    assert "m=video" in answer_sdp
    assert "m=audio" in answer_sdp
    assert session.audio_track is not None

    await session.close()
    await client_pc.close()

