from __future__ import annotations
import argparse
import logging
import cv2
import time
import sys
import queue
import numpy as np

from ..rtsp_data_retrievers import RtspDataRetriever, RtspVideoDataRetriever, RtspApplicationDataRetriever
from ..utils import build_axis_rtsp_url


def simple_video_processing_example(frame: np.ndarray, shared_config: dict) -> np.ndarray:
    """
    Example video processing function that demonstrates the video_processing_fn feature.
    Adds a timestamp overlay and optionally applies brightness adjustment.
    """
    processed = frame.copy()
    
    # Add timestamp overlay
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(processed, timestamp, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # Apply brightness adjustment if configured
    brightness = shared_config.get("brightness_adjustment", 0)
    if brightness != 0:
        processed = cv2.convertScaleAbs(processed, alpha=1.0, beta=brightness)
    
    # Add frame counter
    shared_config["frame_count"] = shared_config.get("frame_count", 0) + 1
    frame_text = f"Frame: {shared_config['frame_count']}"
    cv2.putText(processed, frame_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    
    return processed


def parse_args():
    parser = argparse.ArgumentParser(
        description="CLI for RTSP Data Retriever (video, application data, RTP extension, session metadata)"
    )
    parser.add_argument(
        "--ip", help="Camera IP address (required unless --rtsp-url provided)"
    )
    parser.add_argument("--username", default="", help="Device username")
    parser.add_argument("--password", default="", help="Device password")
    parser.add_argument(
        "--source", default="1", help='What device "source"/"camera head" to use'
    )
    parser.add_argument("--latency", type=int, default=100, help="RTSP latency in ms (to gather out of order packets)")
    parser.add_argument(
        "--only-video", action="store_true", help="Enable only video frames (disable application data) - demonstrates RtspVideoDataRetriever", default=False
    )
    parser.add_argument(
        "--only-application-data", action="store_true", help="Enable only application data XML (disable video) - demonstrates RtspApplicationDataRetriever", default=False
    )
    parser.add_argument(
        "--no-rtp-ext", action="store_false", dest="rtp_ext", help="Disable RTP extension", default=True
    )
    parser.add_argument(
        "--rtsp-url", help="Full RTSP URL, overrides all other arguments"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--connection-timeout",
        type=int,
        default=30,
        help="Connection timeout in seconds",
    )
    parser.add_argument(
        "--resolution", default=None, help="Video resolution (e.g. 1280x720 or 500x500) (default: None, lets device decide)"
    )
    # Advanced feature demonstrations
    parser.add_argument(
        "--enable-video-processing", action="store_true", 
        help="Demonstrate video_processing_fn with timestamp overlay and brightness adjustment", default=False
    )
    parser.add_argument(
        "--brightness-adjustment", type=int, default=0,
        help="Brightness adjustment value for video processing example (-100 to 100)"
    )
    parser.add_argument(
        "--manual-lifecycle", action="store_true",
        help="Demonstrate manual start()/stop() instead of context manager", default=False
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s",
    )
    logging.info(f"Starting with args: {args}")

    if args.rtsp_url:
        rtsp_url = args.rtsp_url
    else:
        try:
            rtsp_url = build_axis_rtsp_url(
                ip=args.ip,
                username=args.username,
                password=args.password,
                video_source=args.source,
                get_video_data=not args.only_application_data,
                get_application_data=not args.only_video,
                rtp_ext=args.rtp_ext,
                resolution=args.resolution,
            )
        except ValueError as e:
            logging.error(e)
            sys.exit(1)
    logging.info(f"Starting stream on {rtsp_url=}")

    # Callback functions for handling different data types
    # Queue for transferring frames to the main thread
    video_frames: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1)

    def on_video_data(payload):
        if args.only_application_data:
            return
        frame = payload["data"]
        diag = payload["diagnostics"]
        try:
            video_frames.put_nowait(frame)
        except queue.Full:
            # Drop frame if the display thread is lagging
            pass

    def on_application_data(payload):
        if args.only_video:
            return
        xml = payload["data"]
        diag = payload["diagnostics"]
        logging.info(f"[APPLICATION DATA] {len(xml)} bytes, diag={diag}")
        logging.info(xml)

    def on_session_start(payload):
        logging.info(f"[SESSION METADATA] {payload}")

    def on_error(payload):
        error_type = payload.get("error_type", "Unknown")
        message = payload.get("message", "Unknown error")
        error_count = payload.get("error_count", 0)
        logging.error(f"[ERROR] {error_type}: {message} (total errors: {error_count})")

    # Set up video processing if requested
    video_processing_fn = None
    shared_config = None
    if args.enable_video_processing and not args.only_application_data:
        video_processing_fn = simple_video_processing_example
        shared_config = {
            "brightness_adjustment": args.brightness_adjustment,
            "frame_count": 0
        }
        logging.info(f"[DEMO] Video processing enabled with brightness adjustment: {args.brightness_adjustment}")

    # Create the retriever with appropriate callbacks
    video_callback = None if args.only_application_data else on_video_data
    application_data_callback = None if args.only_video else on_application_data

    # Choose the appropriate retriever class based on flags
    if args.only_video:
        logging.info("[DEMO] Using RtspVideoDataRetriever (video-only retriever)")
        retriever = RtspVideoDataRetriever(
            rtsp_url=rtsp_url,
            on_video_data=video_callback,
            on_error=on_error,
            on_session_start=on_session_start,
            latency=args.latency,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config,
            connection_timeout=args.connection_timeout,
            log_level=getattr(logging, args.log_level.upper(), logging.INFO),
        )
    elif args.only_application_data:
        logging.info("[DEMO] Using RtspApplicationDataRetriever (application data-only retriever)")
        retriever = RtspApplicationDataRetriever(
            rtsp_url=rtsp_url,
            on_application_data=application_data_callback,
            on_error=on_error,
            on_session_start=on_session_start,
            latency=args.latency,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config,
            connection_timeout=args.connection_timeout,
            log_level=getattr(logging, args.log_level.upper(), logging.INFO),
        )
    else:
        logging.info("[DEMO] Using RtspDataRetriever (combined video+application data retriever)")
        retriever = RtspDataRetriever(
            rtsp_url=rtsp_url,
            on_video_data=video_callback,
            on_application_data=application_data_callback,
            on_session_start=on_session_start,
            on_error=on_error,
            latency=args.latency,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config,
            connection_timeout=args.connection_timeout,
            log_level=getattr(logging, args.log_level.upper(), logging.INFO),
        )

    try:
        if args.manual_lifecycle:
            logging.info("[DEMO] Using manual lifecycle (start/stop methods)")
            # Manual lifecycle demonstration
            retriever.start()
            logging.info("RTSP Data Retriever started manually")
            logging.info("Press Ctrl+C to stop, or 'q' in video window to quit")
            
            # Pre-create the video window so visibility checks won't fail
            if not args.only_application_data:
                try:
                    cv2.namedWindow("Video")
                except cv2.error as e:  # Window creation failed (e.g. headless)
                    logging.error(f"Unable to create video window: {e}")
                    raise

            try:
                while retriever.is_running:
                    time.sleep(0.01)
                    if not args.only_application_data:
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
            finally:
                retriever.stop()  # Manual stop
        else:
            logging.info("[DEMO] Using context manager (with statement)")
            # Use context manager for automatic resource cleanup
            with retriever:
                logging.info("RTSP Data Retriever started")
                logging.info("Press Ctrl+C to stop, or 'q' in video window to quit")
                # Pre-create the video window so visibility checks won't fail
                if not args.only_application_data:
                    try:
                        cv2.namedWindow("Video")
                    except cv2.error as e:  # Window creation failed (e.g. headless)
                        logging.error(f"Unable to create video window: {e}")
                        raise

                # Keep the main thread alive and handle keyboard interrupt
                try:
                    while retriever.is_running:
                        time.sleep(0.01)
                        if not args.only_application_data:
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
        if not args.only_application_data:
            cv2.destroyAllWindows()


def cli() -> None:
    """Console-script entry point."""
    main()


if __name__ == "__main__":
    cli()
