"""Integration tests for Phase 2 WebRTC Video Pipeline (Sprint 3.1 - 3.4).

Verifies:
1. DesktopVideoStreamTrack creates valid av.VideoFrames with correct PTS & dimensions.
2. DesktopVideoStreamTrack provides safe fallback frame when capturer has no new frame.
3. WebRtcPeerSession handles SDP offer and produces a valid SDP answer.
4. Core message dispatch correctly routes rtc_offer, rtc_ice, and rtc_bye messages.
5. Adaptive controller reacts to network latency / queue backlog by lowering bitrate & fps.
"""

import asyncio
import os
import sys
import numpy as np
import pytest

# Ensure desktop is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

from desktop.transport.webrtc import DesktopVideoStreamTrack, WebRtcPeerSession, WebRtcTransport
from desktop.adaptive import AdaptiveController
import desktop.core as core


@pytest.mark.asyncio
async def test_desktop_video_stream_track_frames():
    """Verify track generates valid av.VideoFrame from numpy array."""
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dummy_frame[:, :, 0] = 255  # Red tint

    track = DesktopVideoStreamTrack(get_frame_fn=lambda: dummy_frame, fps=30)
    video_frame = await track.recv()

    assert video_frame is not None
    assert video_frame.width == 640
    assert video_frame.height == 480
    assert video_frame.pts is not None
    assert video_frame.time_base is not None


@pytest.mark.asyncio
async def test_desktop_video_stream_track_placeholder():
    """Verify track does not crash when capturer returns None."""
    track = DesktopVideoStreamTrack(get_frame_fn=lambda: None, fps=30)
    video_frame = await track.recv()

    assert video_frame is not None
    assert video_frame.width == 1280
    assert video_frame.height == 720


@pytest.mark.asyncio
async def test_webrtc_peer_session_handshake():
    """Verify WebRtcPeerSession can take an offer SDP and return a valid answer SDP."""
    if not WebRtcTransport.is_available():
        pytest.skip("aiortc is not available in test environment")

    from aiortc import RTCPeerConnection

    # Simulate client peer connection
    client_pc = RTCPeerConnection()
    client_pc.addTransceiver("video", direction="recvonly")
    client_offer = await client_pc.createOffer()

    sent_messages = []

    class MockConn:
        name = "test_viewer"
        async def send_json(self, d):
            sent_messages.append(d)

    mock_conn = MockConn()
    session = WebRtcPeerSession(
        conn=mock_conn,
        get_frame_fn=lambda: np.zeros((360, 640, 3), dtype=np.uint8),
    )

    answer_sdp = await session.handle_offer(client_offer.sdp)
    assert "m=video" in answer_sdp
    assert "a=sendonly" in answer_sdp or "a=sendrecv" in answer_sdp

    # Add candidate test
    await session.add_ice_candidate({
        "candidate": "candidate:1 1 UDP 2130706431 127.0.0.1 50000 typ host",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
    })

    await session.close()
    await client_pc.close()


@pytest.mark.asyncio
async def test_core_rtc_message_dispatch():
    """Verify core.handle_client_message properly dispatches rtc_offer, rtc_ice, rtc_bye."""
    sent_jsons = []

    class DummyConn:
        name = "rtc_client"
        alive = True
        view_only = False
        caps = []
        rtc_session = None

        async def send_json(self, data):
            sent_jsons.append(data)

        def request_keyframe(self):
            pass

    conn = DummyConn()

    # If offer has invalid or dummy SDP, it should handle cleanly and reply with rtc_answer or rtc_error
    from aiortc import RTCPeerConnection
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    offer = await pc.createOffer()

    await core.handle_client_message(conn, {"type": "rtc_offer", "sdp": offer.sdp})
    assert len(sent_jsons) >= 1
    assert sent_jsons[0]["type"] in ("rtc_answer", "rtc_error")

    # Send ICE
    await core.handle_client_message(conn, {"type": "rtc_ice", "candidate": None})

    # Send Bye
    await core.handle_client_message(conn, {"type": "rtc_bye"})
    assert conn.rtc_session is None

    await pc.close()


def test_adaptive_controller_quality_scaling():
    """Verify AdaptiveController tunes fps/quality when link degrades."""
    controller = AdaptiveController(mode="auto", fps=24, quality=75, scale=100)

    # Simulating severe congestion: RTT > 220ms, drop > 30%
    target = controller.update(rtt_ms=250, dropped_ratio=0.35, queue_depth=20)
    assert target["fps"] < 24
    assert target["quality"] < 75
    assert target["scale"] < 100

    # Simulating excellent LAN condition: RTT 20ms, 0 drop
    ctrl_good = AdaptiveController(mode="auto", fps=10, quality=40, scale=60)
    target_good = ctrl_good.update(rtt_ms=20, dropped_ratio=0.01, queue_depth=1)
    assert target_good["fps"] > 10
    assert target_good["quality"] > 40
    assert target_good["scale"] > 60

