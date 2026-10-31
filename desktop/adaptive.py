"""Adaptive stream controller for TouchLink.

This module chooses capture quality and frame rate from network health.
It is intentionally lightweight and deterministic so it can be tested without
real network or screen access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AdaptiveController:
    """A small hysteresis-based controller for screen stream quality.

    Inputs are health indicators from the network path:
    - rtt_ms: end-to-end latency in milliseconds.
    - dropped_ratio: fraction of frames skipped / lost in recent window.
    - queue_depth: pending outgoing frame count, approximated by sender backlog.
    """

    min_fps: int = 5
    max_fps: int = 30
    min_quality: int = 30
    max_quality: int = 85
    min_scale: int = 50
    max_scale: int = 100
    mode: str = "auto"
    fps: int = 12
    quality: int = 60
    scale: int = 100
    rtt_ms: float = 0.0
    dropped_ratio: float = 0.0
    queue_depth: int = 0
    _high_water_mark: int = 0
    _low_water_mark: int = 0

    def __post_init__(self):
        self.fps = max(self.min_fps, min(self.max_fps, int(self.fps)))
        self.quality = max(self.min_quality, min(self.max_quality, int(self.quality)))
        self.scale = max(self.min_scale, min(self.max_scale, int(self.scale)))
        self._high_water_mark = self.quality + 10
        self._low_water_mark = self.quality - 10

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(maximum, value))

    def _next_step(self, rtt_ms: float, dropped_ratio: float, queue_depth: int) -> dict[str, int]:
        """Return a target profile without mutating the controller state."""
        target_fps = self.fps
        target_quality = self.quality
        target_scale = self.scale

        bad_link = rtt_ms > 220 or dropped_ratio > 0.28 or queue_depth > 16
        weak_link = rtt_ms > 120 or dropped_ratio > 0.12 or queue_depth > 8
        good_link = rtt_ms < 80 and dropped_ratio < 0.08 and queue_depth < 4

        if bad_link:
            target_fps = max(self.min_fps, self.fps - 6)
            target_quality = max(self.min_quality, self.quality - 15)
            target_scale = max(self.min_scale, self.scale - 15)
        elif weak_link:
            target_fps = max(self.min_fps, self.fps - 3)
            target_quality = max(self.min_quality, self.quality - 8)
            target_scale = max(self.min_scale, self.scale - 8)
        elif good_link:
            target_fps = min(self.max_fps, self.fps + 3)
            target_quality = min(self.max_quality, self.quality + 8)
            target_scale = min(self.max_scale, self.scale + 8)

        return {
            "fps": self._clamp(target_fps, self.min_fps, self.max_fps),
            "quality": self._clamp(target_quality, self.min_quality, self.max_quality),
            "scale": self._clamp(target_scale, self.min_scale, self.max_scale),
        }

    def update(self, rtt_ms: float, dropped_ratio: float, queue_depth: int) -> dict[str, int]:
        """Compute the next auto tuning values and store the latest metrics."""
        self.rtt_ms = float(rtt_ms)
        self.dropped_ratio = float(dropped_ratio)
        self.queue_depth = int(queue_depth)

        if self.mode != "auto":
            return {"fps": self.fps, "quality": self.quality, "scale": self.scale}

        target = self._next_step(self.rtt_ms, self.dropped_ratio, self.queue_depth)
        # Hysteresis: avoid oscillating near the boundary.
        if target["quality"] > self.quality and self.rtt_ms < 70 and self.dropped_ratio < 0.05 or target["quality"] < self.quality and (self.rtt_ms > 90 or self.dropped_ratio > 0.1 or self.queue_depth > 5):
            self.quality = target["quality"]
        else:
            self.quality = max(self.min_quality, min(self.max_quality, self.quality))

        if target["fps"] > self.fps and self.rtt_ms < 60 and self.dropped_ratio < 0.04 and self.queue_depth < 3 or target["fps"] < self.fps and (self.rtt_ms > 100 or self.dropped_ratio > 0.08 or self.queue_depth > 6):
            self.fps = target["fps"]
        else:
            self.fps = max(self.min_fps, min(self.max_fps, self.fps))

        if target["scale"] > self.scale and self.rtt_ms < 70 and self.dropped_ratio < 0.06 or target["scale"] < self.scale and (self.rtt_ms > 120 or self.dropped_ratio > 0.12 or self.queue_depth > 8):
            self.scale = target["scale"]
        else:
            self.scale = max(self.min_scale, min(self.max_scale, self.scale))

        return {"fps": self.fps, "quality": self.quality, "scale": self.scale}

    def set_mode(self, mode: str):
        self.mode = "auto" if mode == "auto" else "fixed"

    def state(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "fps": self.fps,
            "quality": self.quality,
            "scale": self.scale,
            "rtt_ms": self.rtt_ms,
            "dropped_ratio": self.dropped_ratio,
            "queue_depth": self.queue_depth,
        }
