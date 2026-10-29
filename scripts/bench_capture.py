#!/usr/bin/env python3
"""Benchmark script cho capture backend TouchLink.

Kịch bản:
  1. static   — màn hình tĩnh (chờ 10s, không cử động)
  2. scroll   — cuộn văn bản (chạy Notepad / cuộn bằng pyautogui)
  3. video    — phát video 720p (kịch bản benchmark tổng hợp)

Cách chạy::

    python scripts/bench_capture.py [--monitor 1] [--scenario static|scroll|video|all]
    python scripts/bench_capture.py --safe  # không di chuột thật

Kết quả ghi vào docs/BENCHMARK.md.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Thêm desktop/ vào path
_ROOT = os.path.join(os.path.dirname(__file__), "..", "desktop")
sys.path.insert(0, os.path.abspath(_ROOT))


def _measure(capturer, tile_engine, monitor: int, scale: int, quality: int,
              duration: float) -> dict:
    """Chạy capturer + tile engine trong ``duration`` giây, trả về metrics."""
    import psutil
    from capture.tile_engine import scale_frame

    proc = psutil.Process()
    capturer.start(monitor)
    tile_engine.reset()

    t_start = time.monotonic()
    t_cpu_start = proc.cpu_times()
    frames = 0
    bytes_sent = 0
    dirty_frames = 0

    while time.monotonic() - t_start < duration:
        frame = capturer.grab()
        if frame is None:
            time.sleep(0.01)
            continue
        arr = scale_frame(frame.data, scale) if scale < 100 else frame.data
        payload = tile_engine.process(arr, quality, force_keyframe=False)
        if payload is not None:
            dirty_frames += 1
            bytes_sent += len(payload)
        frames += 1
        time.sleep(max(0, 1 / 30 - 0.001))  # target 30fps loop

    t_end = time.monotonic()
    t_cpu_end = proc.cpu_times()
    elapsed = t_end - t_start
    cpu_user = (t_cpu_end.user - t_cpu_start.user) / elapsed * 100
    cpu_sys = (t_cpu_end.system - t_cpu_start.system) / elapsed * 100

    capturer.stop()

    fps = dirty_frames / elapsed if elapsed > 0 else 0
    bps = bytes_sent / elapsed if elapsed > 0 else 0

    return {
        "elapsed": round(elapsed, 1),
        "frames_grabbed": frames,
        "dirty_frames": dirty_frames,
        "fps_actual": round(fps, 1),
        "bytes_sent": bytes_sent,
        "bps": round(bps / 1024, 1),    # KB/s
        "cpu_user_pct": round(cpu_user, 1),
        "cpu_sys_pct": round(cpu_sys, 1),
    }


def run_scenario(name: str, monitor: int, duration: float, instruction: str) -> dict:
    """Chạy một kịch bản benchmark."""
    from capture.factory import make_capturer
    from capture.tile_engine import TileEngine, TILE_SIZE_DEFAULT

    print(f"\n{'='*60}")
    print(f"Kịch bản: {name}")
    print(f"Hướng dẫn: {instruction}")
    print(f"Thời gian: {duration}s — nhấn Enter để bắt đầu...")
    input()

    cap = make_capturer(prefer_dxgi=True)
    engine = TileEngine(TILE_SIZE_DEFAULT)

    print(f"Đang chạy {name} ({duration}s)...")
    metrics = _measure(cap, engine, monitor, scale=100, quality=75, duration=duration)

    print(f"  FPS dirty    : {metrics['fps_actual']}")
    print(f"  Byte/s       : {metrics['bps']} KB/s")
    print(f"  CPU user     : {metrics['cpu_user_pct']}%")
    print(f"  CPU sys      : {metrics['cpu_sys_pct']}%")
    print(f"  Dirty frames : {metrics['dirty_frames']}/{metrics['frames_grabbed']}")
    return {"scenario": name, **metrics}


def write_markdown(results: list[dict], backend: str) -> None:
    """Ghi kết quả vào docs/BENCHMARK.md."""
    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "BENCHMARK.md")
    ts = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# TouchLink Capture Benchmark\n",
        f"_Tự động sinh bởi `scripts/bench_capture.py` lúc {ts}_\n\n",
        f"**Backend:** `{backend}`\n\n",
        "| Kịch bản | FPS | KB/s | CPU user% | CPU sys% | Dirty/Total |\n",
        "|----------|-----|------|-----------|----------|-------------|\n",
    ]
    for r in results:
        ratio = f"{r['dirty_frames']}/{r['frames_grabbed']}"
        lines.append(
            f"| {r['scenario']} | {r['fps_actual']} | {r['bps']} "
            f"| {r['cpu_user_pct']} | {r['cpu_sys_pct']} | {ratio} |\n"
        )
    lines.append("\n## DoD Checklist\n\n")
    # Kiểm tra DoD
    static_r = next((r for r in results if "static" in r["scenario"].lower()), None)
    scroll_r = next((r for r in results if "scroll" in r["scenario"].lower()), None)
    if static_r:
        cpu_ok = static_r["cpu_user_pct"] < 3
        bw_ok = static_r["bps"] < 50  # < 50 KB/s ~ gần 0
        lines.append(f"- Màn hình tĩnh CPU < 3%: {'✅' if cpu_ok else '❌'} "
                      f"({static_r['cpu_user_pct']}%)\n")
        lines.append(f"- Màn hình tĩnh bandwidth gần 0: {'✅' if bw_ok else '❌'} "
                      f"({static_r['bps']} KB/s)\n")
    if scroll_r:
        fps_ok = scroll_r["fps_actual"] >= 15
        lines.append(f"- Cuộn văn bản ≥ 15 fps: {'✅' if fps_ok else '❌'} "
                      f"({scroll_r['fps_actual']} fps)\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"\nKết quả đã ghi vào {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TouchLink Capture Benchmark")
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--scenario", default="all",
                        choices=["static", "scroll", "video", "all"])
    parser.add_argument("--duration", type=float, default=15.0,
                        help="Giây mỗi kịch bản (mặc định 15)")
    parser.add_argument("--safe", action="store_true",
                        help="Không di chuột/phím thật")
    args = parser.parse_args()

    try:
        import psutil  # noqa
    except ImportError:
        print("Cần cài psutil: pip install psutil")
        sys.exit(1)

    scenarios_map = {
        "static": ("static", "ĐỪNG di chuyển chuột hay gõ phím trong suốt bài test"),
        "scroll": ("scroll", "Mở Notepad với nhiều văn bản, cuộn liên tục"),
        "video": ("video 720p", "Phát video 720p full screen trong trình duyệt"),
    }
    if args.scenario == "all":
        keys = ["static", "scroll", "video"]
    else:
        keys = [args.scenario]

    # Lấy tên backend
    _ROOT2 = os.path.join(os.path.dirname(__file__), "..", "desktop")
    sys.path.insert(0, os.path.abspath(_ROOT2))
    from capture.factory import make_capturer
    _tmp_cap = make_capturer(prefer_dxgi=True)
    backend = _tmp_cap.name

    results = []
    for k in keys:
        name, instruction = scenarios_map[k]
        r = run_scenario(name, args.monitor, args.duration, instruction)
        results.append(r)

    write_markdown(results, backend)
    print("\nBenchmark hoàn thành.")


if __name__ == "__main__":
    main()
