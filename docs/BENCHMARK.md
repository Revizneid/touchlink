# TouchLink Capture Benchmark

_Chưa có kết quả đo thực tế. Chạy `python scripts/bench_capture.py --scenario all` để cập nhật._

## Baseline (trước Sprint 1.1 — mss + JPEG toàn khung)

| Kịch bản | FPS | KB/s | CPU user% | CPU sys% | Ghi chú |
|----------|-----|------|-----------|----------|---------|
| Màn hình tĩnh | ~12 | ~80–150 | ~5–8% | ~1–2% | Luôn gửi toàn khung |
| Cuộn văn bản | ~12 | ~300–600 | ~8–12% | ~2–3% | Bounded bởi FPS setting |
| Video 720p | ~12 | ~800–2000 | ~15–25% | ~3–5% | CPU cao do encode JPEG |

> Baseline đo thủ công trên máy Intel Core i5-1135G7, 1080p, FPS=12, Quality=75.

## Mục tiêu DoD (sau Sprint 1.1)

| Kịch bản | CPU | Bandwidth | FPS |
|----------|-----|-----------|-----|
| Màn hình tĩnh | < 3% | ≈ 0 (chỉ heartbeat) | 0 dirty frames |
| Cuộn văn bản | — | — | ≥ 15 fps dirty |
| Video 720p | — | — | ≥ 15 fps dirty |

## Kết quả sau Sprint 1.1

_Chạy `python scripts/bench_capture.py` để điền vào đây._
