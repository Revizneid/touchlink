import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.transport import (
    RTCSignalMessage,
    create_turn_credential,
    sign_sdp,
    validate_webrtc_signal,
    verify_signed_sdp,
    verify_turn_credential,
)


def test_webrtc_signaling_message_and_sdp_verification():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    sdp = "v=0\r\n" \
          "o=- 0 0 IN IP4 127.0.0.1\r\n" \
          "s=-\r\n" \
          "t=0 0\r\n" \
          "a=group:BUNDLE 0\r\n" \
          "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n" \
          "c=IN IP4 0.0.0.0\r\n" \
          "a=mid:0\r\n"

    signed = sign_sdp(sdp, private_key)
    assert verify_signed_sdp(sdp, signed, public_key) is True
    assert verify_signed_sdp(sdp, b"tampered", public_key) is False

    msg = RTCSignalMessage(
        type="rtc_offer",
        device_id="234567892",
        sdp=sdp,
        signature=signed.hex(),
        signer="234567892",
    )
    assert validate_webrtc_signal(msg) is True

    tampered = RTCSignalMessage(
        type="rtc_offer",
        device_id="234567892",
        sdp="v=0\r\ninvalid\r\n",
        signature="00",
        signer="234567892",
    )
    assert validate_webrtc_signal(tampered) is False


def test_turn_credential_generation_and_expiry():
    issued = create_turn_credential("shared-turn-secret", device_id="234567892", ttl_s=300)
    assert issued["ttl_s"] == 300
    assert issued["expires_at"] > time.time()
    assert verify_turn_credential(
        "shared-turn-secret",
        issued["username"],
        issued["credential"],
        device_id="234567892",
        now=time.time(),
    ) is True
    assert verify_turn_credential(
        "shared-turn-secret",
        issued["username"],
        issued["credential"],
        device_id="wrong",
        now=time.time(),
    ) is False

    expired = create_turn_credential("shared-turn-secret", device_id="234567892", ttl_s=1, now=time.time() - 2)
    assert verify_turn_credential(
        "shared-turn-secret",
        expired["username"],
        expired["credential"],
        device_id="234567892",
        now=time.time(),
    ) is False
