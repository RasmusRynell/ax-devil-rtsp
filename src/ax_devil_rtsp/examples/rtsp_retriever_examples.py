"""
Comprehensive functional test for RTSP data retriever classes.

This script demonstrates and tests all major retriever features and modes:
- Combined video+metadata
- Video-only
- Metadata-only
- Axis-style URL construction
- Context manager and manual start/stop
- RTP extension

All parameters (IP, credentials, resolution, etc.) are configurable via command-line arguments.
The script collects errors and reports a summary at the end, exiting with code 1 if any errors occurred.
"""

import time
import argparse
import sys
from ax_devil_rtsp.rtsp_data_retrievers import (
    RtspDataRetriever, RtspVideoDataRetriever, RtspApplicationDataRetriever, RtspPayload
)
from ax_devil_rtsp.utils import build_axis_rtsp_url

def parse_args():
    parser = argparse.ArgumentParser(description="Comprehensive RTSP retriever functional test.")
    parser.add_argument("--ip", required=True, help="Camera IP address")
    parser.add_argument("--username", default="", help="Device username")
    parser.add_argument("--password", default="", help="Device password")
    parser.add_argument("--source", type=int, default=1, help="Device source/camera head")
    parser.add_argument("--resolution", default="640x480", help="Video resolution (e.g. 1280x720)")
    parser.add_argument("--duration", type=int, default=2, help="Test duration in seconds for each retriever")
    parser.add_argument("--rtp-ext", action="store_true", help="Enable RTP extension for one example")
    return parser.parse_args()


def main():
    args = parse_args()
    errors = []

    def print_video(payload: RtspPayload) -> None:
        print("[VIDEO] Frame received", payload.get("diagnostics", {}))

    def print_metadata(payload: RtspPayload) -> None:
        print("[METADATA] Data received", payload.get("diagnostics", {}))

    def print_error(payload: RtspPayload) -> None:
        print("[ERROR]", payload.get("message"))
        errors.append(payload)

    def print_session_start(payload: RtspPayload) -> None:
        print("[SESSION START]", payload)
        # Optionally print more details if present
        if "stream_name" in payload:
            print("  Stream name:", payload["stream_name"])
        if "caps" in payload:
            print("  Caps:", payload["caps"])
        if "structure" in payload:
            print("  Structure:", payload["structure"])

    # --- Example 1: Using direct RTSP URL with context manager ---
    print("\n--- Example 1: Direct RTSP URL ---")
    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/axis-media/media.amp?camera={args.source}"
    with RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=print_video,
        on_application_data=print_metadata,
        on_error=print_error,
        on_session_start=print_session_start,
    ):
        print("Retriever running (direct URL)...")
        time.sleep(args.duration)

    # --- Example 2: Axis-style URL (video + metadata) ---
    print("\n--- Example 2: Axis-style URL (video + metadata) ---")
    axis_url = build_axis_rtsp_url(
        ip=args.ip,
        username=args.username,
        password=args.password,
        video_source=args.source,
        get_video_data=True,
        get_application_data=True,
        rtp_ext=False,
        resolution=args.resolution,
    )
    with RtspDataRetriever(
        rtsp_url=axis_url,
        on_video_data=print_video,
        on_application_data=print_metadata,
        on_error=print_error,
        on_session_start=print_session_start,
    ):
        print("Retriever running (Axis params)...")
        time.sleep(args.duration)

    # --- Example 3: Video-only retriever ---
    print("\n--- Example 3: Video-only retriever ---")
    video_url = build_axis_rtsp_url(
        ip=args.ip,
        username=args.username,
        password=args.password,
        video_source=args.source,
        get_video_data=True,
        get_application_data=False,
        rtp_ext=False,
        resolution=args.resolution,
    )
    video_retriever = RtspVideoDataRetriever(
        rtsp_url=video_url,
        on_video_data=print_video,
        on_error=print_error,
        on_session_start=print_session_start,
    )
    video_retriever.start()
    print("Video retriever running...")
    time.sleep(args.duration)
    video_retriever.stop()

    # --- Example 4: Application-data-only retriever ---
    print("\n--- Example 4: Application-data-only retriever ---")
    app_url = build_axis_rtsp_url(
        ip=args.ip,
        username=args.username,
        password=args.password,
        video_source=args.source,
        get_video_data=False,
        get_application_data=True,
        rtp_ext=False,
        resolution=args.resolution,
    )
    app_retriever = RtspApplicationDataRetriever(
        rtsp_url=app_url,
        on_application_data=print_metadata,
        on_error=print_error,
        on_session_start=print_session_start,
    )
    app_retriever.start()
    print("Application-data retriever running...")
    time.sleep(args.duration)
    app_retriever.stop()

    # --- Example 5: Axis-style URL with RTP extension (if requested) ---
    if args.rtp_ext:
        print("\n--- Example 5: Axis-style URL with RTP extension ---")
        rtp_url = build_axis_rtsp_url(
            ip=args.ip,
            username=args.username,
            password=args.password,
            video_source=args.source,
            get_video_data=True,
            get_application_data=True,
            rtp_ext=True,
            resolution=args.resolution,
        )
        with RtspDataRetriever(
            rtsp_url=rtp_url,
            on_video_data=print_video,
            on_application_data=print_metadata,
            on_error=print_error,
            on_session_start=print_session_start,
        ):
            print("Retriever running (RTP extension enabled)...")
            time.sleep(args.duration)

    # --- Error summary ---
    print("\n--- Test Summary ---")
    if errors:
        print(f"Encountered {len(errors)} error(s) during test run:")
        for err in errors:
            print("  -", err.get("message"))
        sys.exit(1)
    else:
        print("All retriever examples ran without errors.")
        sys.exit(0)

if __name__ == "__main__":
    main() 