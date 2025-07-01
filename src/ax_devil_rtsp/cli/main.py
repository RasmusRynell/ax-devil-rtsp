from __future__ import annotations

import logging
import queue
import sys
import time
from types import SimpleNamespace

import click
import cv2
import numpy as np

from ..rtsp_data_retrievers import (
    RtspApplicationDataRetriever,
    RtspDataRetriever,
    RtspVideoDataRetriever,
)
from ..utils import build_axis_rtsp_url


def simple_video_processing_example(
    payload: dict, shared_config: dict
) -> np.ndarray:
    """
    Example video processing function that demonstrates the video_processing_fn feature.
    Adds a timestamp overlay and optionally applies brightness adjustment.
    """
    frame = payload["data"]
    processed = frame.copy()

    # Add timestamp overlay
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(
        processed, timestamp, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
    )

    # Apply brightness adjustment if configured
    brightness = shared_config.get("brightness_adjustment", 0)
    if brightness != 0:
        processed = cv2.convertScaleAbs(processed, alpha=1.0, beta=brightness)

    # Add frame counter
    shared_config["frame_count"] = shared_config.get("frame_count", 0) + 1
    frame_text = f"Frame: {shared_config['frame_count']}"
    cv2.putText(
        processed, frame_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1
    )

    return processed


def main(**kwargs):
    args = SimpleNamespace(**kwargs)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s",
    )

    logging.info(f"Starting with args: {args}")

    if getattr(args, "rtsp_url", None):
        rtsp_url = args.rtsp_url
    else:
        try:
            rtsp_url = build_axis_rtsp_url(
                ip=args.ip,
                username=args.username,
                password=args.password,
                video_source=getattr(args, "source", 1),
                get_video_data=not args.only_application_data,
                get_application_data=not args.only_video,
                rtp_ext=getattr(args, "rtp_ext", True),
                resolution=getattr(args, "resolution", None),
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
            "frame_count": 0,
        }
        logging.info(
            "[DEMO] Video processing enabled with brightness adjustment: "
            f"{args.brightness_adjustment}"
        )

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
        logging.info(
            "[DEMO] Using RtspApplicationDataRetriever "
            "(application data-only retriever)"
        )
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
        logging.info(
            "[DEMO] Using RtspDataRetriever (combined video+application data retriever)"
        )
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
                                if (
                                    cv2.getWindowProperty("Video", cv2.WND_PROP_VISIBLE)
                                    < 1
                                ):
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


def _shared_options(func):
    """Decorator for options common to all commands."""

    func = click.option(
        "--latency",
        default=100,
        show_default=True,
        type=int,
        help="RTSP latency in ms (to gather out of order packets)",
    )(func)

    func = click.option(
        "--only-video",
        is_flag=True,
        default=False,
        show_default=True,
        help=(
            "Enable only video frames (disable application data) - "
            "demonstrates RtspVideoDataRetriever"
        ),
    )(func)

    func = click.option(
        "--only-application-data",
        is_flag=True,
        default=False,
        show_default=True,
        help=(
            "Enable only application data XML (disable video) - "
            "demonstrates RtspApplicationDataRetriever"
        ),
    )(func)

    func = click.option(
        "--log-level",
        default="INFO",
        show_default=True,
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
        help="Logging verbosity",
    )(func)

    func = click.option(
        "--connection-timeout",
        default=30,
        show_default=True,
        type=int,
        help="Connection timeout in seconds",
    )(func)

    func = click.option(
        "--enable-video-processing",
        is_flag=True,
        default=False,
        show_default=True,
        help=(
            "Demonstrate video_processing_fn with timestamp overlay "
            "and brightness adjustment"
        ),
    )(func)

    func = click.option(
        "--brightness-adjustment",
        default=0,
        show_default=True,
        type=int,
        help="Brightness adjustment value for video processing example (-100 to 100)",
    )(func)

    func = click.option(
        "--manual-lifecycle",
        is_flag=True,
        default=False,
        show_default=True,
        help="Demonstrate manual start()/stop() instead of context manager",
    )(func)

    return func


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Retrieve RTSP video and application data from Axis devices."""
    pass


@cli.command("device")
@click.option(
    "--ip",
    envvar="AX_DEVIL_TARGET_ADDR",
    required=True,
    help="Camera IP address (env: AX_DEVIL_TARGET_ADDR)",
)
@click.option(
    "--username",
    envvar="AX_DEVIL_TARGET_USER",
    default="",
    show_default=True,
    help="Device username (env: AX_DEVIL_TARGET_USER)",
)
@click.option(
    "--password",
    envvar="AX_DEVIL_TARGET_PASS",
    default="",
    show_default=True,
    help="Device password (env: AX_DEVIL_TARGET_PASS)",
)
@click.option(
    "--source",
    default="1",
    show_default=True,
    help='What device "source"/"camera head" to use',
)
@click.option(
    "--rtp-ext/--no-rtp-ext",
    default=True,
    show_default=True,
    help="Enable or disable RTP extension",
)
@click.option(
    "--resolution",
    default=None,
    show_default=True,
    help=(
        "Video resolution (e.g. 1280x720 or 500x500) "
        "(default: None, lets device decide)"
    ),
)
@_shared_options
def device(**kwargs) -> None:
    """Build the RTSP URL from device info and connect."""
    main(**kwargs)


@cli.command("url")
@click.argument("rtsp_url")
@_shared_options
def url(rtsp_url: str, **kwargs) -> None:
    """Connect using an existing RTSP URL.

    Options that build the URL (e.g. ``--resolution``) are not available."""
    main(rtsp_url=rtsp_url, **kwargs)


if __name__ == "__main__":
    cli()
