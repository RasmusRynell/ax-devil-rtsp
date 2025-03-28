import argparse
import logging
import os
import sys
import time
import multiprocessing
import cv2

from ax_devil_rtsp.metadata_gstreamer import run_scene_metadata_client_simple_example
from ax_devil_rtsp.video_gstreamer import run_video_client_simple_example, example_processing_fn

logger = logging.getLogger("axis-cli")

def run_metadata(args):
    """Run the metadata client and print unified payloads."""
    multiprocessing.set_start_method("spawn", force=True)
    queue = multiprocessing.Queue()

    # Build the RTSP URL: use --rtsp-url if provided; otherwise, construct one using credentials and the default metadata URI.
    rtsp_url = args.rtsp_url if args.rtsp_url else (
        f"rtsp://{args.username}:{args.password}@{args.ip}/axis-media/media.amp?analytics=polygon"
    )

    logger.info("Starting SceneMetadataClient with URL: %s", rtsp_url)
    process = multiprocessing.Process(
        target=run_scene_metadata_client_simple_example,
        args=(rtsp_url, args.latency, queue)
    )

    process.start()
    logger.info("Launched SceneMetadataClient subprocess with PID %d", process.pid)
    start_time = time.time()
    try:
        while time.time() - start_time < args.duration:
            try:
                payload = queue.get(timeout=1)
                print("Received payload:")
                print("Data:", payload.get("data"))
                print("Diagnostics:", payload.get("diagnostics"))
            except Exception:
                continue
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected in main process")
    finally:
        logger.info("Terminating SceneMetadataClient subprocess")
        process.terminate()
        process.join()


def run_video(args):
    """Run the video client and display video frames using OpenCV."""
    multiprocessing.set_start_method("spawn", force=True)
    queue = multiprocessing.Queue()
    manager = multiprocessing.Manager()
    shared_config = manager.dict()  # Allows runtime updates to processing configuration.

    # Build the RTSP URL: use --rtsp-url if provided; otherwise, construct one using credentials and the default video URI.
    rtsp_url = args.rtsp_url if args.rtsp_url else (
        f"rtsp://{args.username}:{args.password}@{args.ip}/axis-media/media.amp"
    )

    logger.info("Starting VideoGStreamerClient with URL: %s", rtsp_url)
    process = multiprocessing.Process(
        target=run_video_client_simple_example,
        args=(rtsp_url, args.latency, queue, example_processing_fn, shared_config)
    )

    process.start()
    logger.info("Launched VideoGStreamerClient subprocess with PID %d", process.pid)
    try:
        while True:
            try:
                payload = queue.get(timeout=1)
                frame = payload.get("data")
                diagnostics = payload.get("diagnostics", {})
                rtp_data = payload.get("latest_rtp_data", {})
                print(f"Received frame (shape: {frame.shape}) | Diagnostics: {diagnostics} | RTP Data: {rtp_data}")
                cv2.imshow("Video Frame", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            except Exception:
                continue
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected in main process")
    finally:
        logger.info("Terminating VideoGStreamerClient subprocess")
        process.terminate()
        process.join()
        cv2.destroyAllWindows()


def cli():    
    parser = argparse.ArgumentParser(
        description="Axis Production GStreamer Client CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # Global options.
    parser.add_argument("--username", default=os.getenv("AX_DEVIL_TARGET_USER", "root"),
                        help="RTSP username")
    parser.add_argument("--password", default=os.getenv("AX_DEVIL_TARGET_PASS", "fusion"),
                        help="RTSP password")
    parser.add_argument("--ip", default=os.getenv("AX_DEVIL_TARGET_ADDR", "192.168.1.81"),
                        help="Camera IP address")
    parser.add_argument("--latency", type=int, default=100, help="RTSP latency in ms")
    parser.add_argument("--rtsp-url",
                        help="Full RTSP URL; overrides username, password, ip, and uri if provided")
    parser.add_argument("--log-level", type=str, default="ERROR", help="Log level")

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # Subcommand for the metadata client.
    metadata_parser = subparsers.add_parser("metadata", help="Run the metadata client")
    metadata_parser.add_argument("--duration", type=int, default=10,
                                 help="Duration (in seconds) to run the metadata client")

    # Subcommand for the video client.
    video_parser = subparsers.add_parser("video", help="Run the video client")

    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s"
    )

    if args.command == "metadata":
        run_metadata(args)
    elif args.command == "video":
        run_video(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
