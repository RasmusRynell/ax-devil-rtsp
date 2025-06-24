from __future__ import annotations
import argparse
import logging
import cv2
import time
import sys
import queue
import numpy as np

from ..rtsp_data_retrievers import RtspDataRetriever
from ..utils import build_axis_rtsp_url


def parse_args():
    parser = argparse.ArgumentParser(
        description="CLI for RTSP Data Retriever (video, metadata, RTP extension, session metadata)"
    )
    parser.add_argument("--ip", help="Camera IP address (required unless --rtsp-url provided)")
    parser.add_argument("--username", default="", help="Device username")
    parser.add_argument("--password", default="", help="Device password")
    parser.add_argument("--source", default="1", help="What device \"source\"/\"camera head\" to use")
    parser.add_argument("--latency", type=int, default=100, help="RTSP latency in ms")
    parser.add_argument("--no-video", action="store_true", help="Disable video frames", default=False)
    parser.add_argument("--no-metadata", action="store_true", help="Disable metadata XML", default=False)
    parser.add_argument("--rtp-ext", action="store_true", help="Enable RTP extension", default=True)
    parser.add_argument("--rtsp-url", help="Full RTSP URL, overrides all other arguments")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--connection-timeout", type=int, default=30, help="Connection timeout in seconds")
    parser.add_argument("--resolution", default="500x500", help="Video resolution (e.g. 1280x720)")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s",
    )
    
    if args.rtsp_url:
        rtsp_url = args.rtsp_url
    else:
        try:
            rtsp_url = build_axis_rtsp_url(
                ip=args.ip,
                username=args.username,
                password=args.password,
                video_source=args.source,
                get_video_data=not args.no_video,
                get_application_data=not args.no_metadata,
                rtp_ext=args.rtp_ext,
                resolution=args.resolution,
            )
        except ValueError as e:
            logging.error(e)
            sys.exit(1)
    print(f"Starting stream on {rtsp_url=}")

    # Callback functions for handling different data types
    # Queue for transferring frames to the main thread
    video_frames: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1)

    def on_video_data(payload):
        if args.no_video:
            return
        frame = payload["data"]
        diag = payload["diagnostics"]
        print(f"[VIDEO] frame shape={frame.shape}, diag={diag}")
        try:
            video_frames.put_nowait(frame)
        except queue.Full:
            # Drop frame if the display thread is lagging
            pass

    def on_application_data(payload):
        if args.no_metadata:
            return
        xml = payload["data"]
        diag = payload["diagnostics"]
        print(f"[METADATA] {len(xml)} bytes, diag={diag}")
        print(xml)

    def on_session_start(payload):
        print(f"[SESSION METADATA] {payload}")

    def on_error(payload):
        error_type = payload.get("error_type", "Unknown")
        message = payload.get("message", "Unknown error")
        error_count = payload.get("error_count", 0)
        print(f"[ERROR] {error_type}: {message} (total errors: {error_count})")

    # Create the retriever with appropriate callbacks
    video_callback = None if args.no_video else on_video_data
    metadata_callback = None if args.no_metadata else on_application_data

    retriever = RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=video_callback,
        on_application_data=metadata_callback,
        on_session_start=on_session_start,
        on_error=on_error,
        latency=args.latency,
        connection_timeout=args.connection_timeout,
    )

    try:
        # Use context manager for automatic resource cleanup
        with retriever:
            logging.info("RTSP Data Retriever started")
            print("Press Ctrl+C to stop, or 'q' in video window to quit")

            # Pre-create the video window so visibility checks won't fail
            if not args.no_video:
                try:
                    cv2.namedWindow("Video")
                except cv2.error as e:  # Window creation failed (e.g. headless)
                    logging.error(f"Unable to create video window: {e}")
                    args.no_video = True

            # Keep the main thread alive and handle keyboard interrupt
            try:
                while retriever.is_running:
                    time.sleep(0.01)
                    if not args.no_video:
                        # Display latest frame if available
                        try:
                            frame = video_frames.get_nowait()
                            cv2.imshow("Video", frame)
                        except queue.Empty:
                            pass
                        # Close if window was closed or user pressed 'q'
                        try:
                            if cv2.getWindowProperty("Video", cv2.WND_PROP_VISIBLE) < 1:
                                break
                            if cv2.waitKey(1) & 0xFF == ord("q"):
                                break
                        except cv2.error:
                            break
            except KeyboardInterrupt:
                logging.info("Interrupted by user")
                
    except Exception as e:
        logging.error(f"Error running retriever: {e}")
    finally:
        logging.info("Cleaning up...")
        if not args.no_video:
            cv2.destroyAllWindows()


def cli() -> None:
    """Console-script entry point."""
    main()


if __name__ == "__main__":
    cli()
