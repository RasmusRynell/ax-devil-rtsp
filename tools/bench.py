"""Benchmark N concurrent stream sessions in one process against a real camera.

    python tools/bench.py --streams 4 --video rgba --seconds 20
    python tools/bench.py --url "rtsp://user:pass@camera/axis-media/media.amp?videocodec=h265&onvifreplayext=1"

Without --url the camera comes from AX_DEVIL_TARGET_ADDR, AX_DEVIL_TARGET_USER and AX_DEVIL_TARGET_PASS.
Prints one JSON line: process CPU (% of one core), RSS, fps, capture-time coverage, delivery age (host clock minus
capture time, so it includes any camera clock offset; compare runs, not absolute values), metadata rate,
metadata-to-nearest-frame distance and time to first frame. Linux only (reads /proc).
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections import deque
from typing import Any

import av

from ax_devil_rtsp import SceneMetadata, StreamConfig, StreamSession, VideoOutput, VideoSample, build_axis_rtsp_url


class Stats:
    """Measurements of one session; callbacks run on that session's receive thread."""

    def __init__(self, started: float) -> None:
        self.started = started
        self.measuring = False
        self.first_frame_s: float | None = None
        self.frames = 0
        self.frames_with_capture_time = 0
        self.ages_ms: list[float] = []
        self.documents = 0
        self.sync_ms: list[float] = []
        self.capture_times: deque[int] = deque(maxlen=120)
        self.lock = threading.Lock()

    def on_video(self, sample: VideoSample[Any]) -> None:
        now_ns = time.time_ns()
        if self.first_frame_s is None:
            self.first_frame_s = time.monotonic() - self.started
        if sample.capture_time_ns is not None:
            with self.lock:
                self.capture_times.append(sample.capture_time_ns)
        if not self.measuring:
            return
        self.frames += 1
        if sample.capture_time_ns is not None:
            self.frames_with_capture_time += 1
            self.ages_ms.append((now_ns - sample.capture_time_ns) / 1e6)

    def on_metadata(self, document: SceneMetadata) -> None:
        if not self.measuring:
            return
        self.documents += 1
        utc_time_ns = document.utc_time_ns
        with self.lock:
            capture_times = list(self.capture_times)
        if utc_time_ns is not None and capture_times:
            self.sync_ms.append(min(abs(utc_time_ns - t) for t in capture_times) / 1e6)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 2)


def memory_mb() -> dict[str, float]:
    with open("/proc/self/status") as status:
        fields = dict(line.split(":", 1) for line in status if line.startswith(("VmRSS", "VmHWM")))
    return {key: round(int(value.split()[0]) / 1024, 1) for key, value in fields.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="complete RTSP URL; overrides the AX_DEVIL_TARGET_* camera")
    parser.add_argument("--streams", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--video", choices=[output.value for output in VideoOutput], default="rgba")
    parser.add_argument("--no-metadata", action="store_true")
    parser.add_argument("--resolution")
    parser.add_argument("--hwaccel")
    parser.add_argument("--out", help="also append the JSON line to this file")
    args = parser.parse_args()

    config = StreamConfig(video=VideoOutput(args.video), metadata=not args.no_metadata, hwaccel=args.hwaccel)
    url = args.url or build_axis_rtsp_url(
        os.environ["AX_DEVIL_TARGET_ADDR"],
        config,
        username=os.environ.get("AX_DEVIL_TARGET_USER", ""),
        password=os.environ.get("AX_DEVIL_TARGET_PASS", ""),
        resolution=args.resolution,
    )
    started = time.monotonic()
    stats = [Stats(started) for _ in range(args.streams)]
    sessions = [
        StreamSession(url, config, on_video=s.on_video, on_metadata=s.on_metadata if config.metadata else None)
        for s in stats
    ]
    for session in sessions:
        session.start()

    time.sleep(args.warmup)
    for s in stats:
        s.measuring = True
    cpu_before, wall_before = sum(os.times()[:2]), time.monotonic()
    time.sleep(args.seconds)
    cpu, wall = sum(os.times()[:2]) - cpu_before, time.monotonic() - wall_before
    for s in stats:
        s.measuring = False
    memory = memory_mb()
    for session in sessions:
        session.stop()
    for session in sessions:
        session.join(5)

    frames = sum(s.frames for s in stats)
    ages = [age for s in stats for age in s.ages_ms]
    sync = [distance for s in stats for distance in s.sync_ms]
    first_frames = [s.first_frame_s for s in stats if s.first_frame_s is not None]
    result = {
        "video": args.video,
        "codecs": sorted({session.video_codec or "" for session in sessions}),
        "streams": args.streams,
        "resolution": args.resolution or "default",
        "hwaccel": args.hwaccel,
        "pyav": av.__version__,
        "cpu_pct_one_core": round(cpu / wall * 100, 1),
        "cpu_pct_per_stream": round(cpu / wall * 100 / args.streams, 1),
        "rss_mb": memory.get("VmRSS"),
        "rss_peak_mb": memory.get("VmHWM"),
        "fps_per_stream": round(frames / wall / args.streams, 2),
        "capture_time_coverage": round(sum(s.frames_with_capture_time for s in stats) / frames, 3) if frames else 0,
        "age_ms_p50": percentile(ages, 0.5),
        "age_ms_p95": percentile(ages, 0.95),
        "metadata_docs_per_s_per_stream": round(sum(s.documents for s in stats) / wall / args.streams, 2),
        "sync_ms_p50": percentile(sync, 0.5),
        "sync_ms_p95": percentile(sync, 0.95),
        "time_to_first_frame_s": round(sum(first_frames) / len(first_frames), 2) if first_frames else None,
        "failures": [str(session.failure) for session in sessions if session.failure is not None],
    }
    line = json.dumps(result)
    print(line)
    if args.out:
        with open(args.out, "a") as out:
            out.write(f"{line}\n")


if __name__ == "__main__":
    main()
