import time

from desktop import secure
from desktop.adaptive import AdaptiveController


def test_adaptive_controller_reduces_stream_under_lossy_link():
    controller = AdaptiveController(fps=12, quality=60, scale=100)

    out = controller.update(rtt_ms=240, dropped_ratio=0.35, queue_depth=20)

    assert out["fps"] <= 12
    assert out["quality"] <= 55
    assert out["scale"] <= 100

    recovered = controller.update(rtt_ms=35, dropped_ratio=0.01, queue_depth=1)
    assert recovered["quality"] >= out["quality"]
    assert recovered["fps"] >= out["fps"]


def test_resume_tokens_are_single_use_and_expire():
    token_store = secure.ResumeTokenStore()
    token = token_store.issue("device-42", ttl_seconds=60)

    assert token_store.consume(token, "device-42") is True
    assert token_store.consume(token, "device-42") is False

    expired_token = token_store.issue("device-43", ttl_seconds=60)
    token_store._tokens[expired_token]["expires"] = time.time() - 1
    assert token_store.consume(expired_token, "device-43") is False
