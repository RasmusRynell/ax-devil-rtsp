#!/usr/bin/env python3
"""CLI tools for video streaming and metadata handling from Axis cameras."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import NoReturn

import cv2
import numpy as np
from numpy.typing import NDArray

from ax_devil_rtsp.metadata_gstreamer import AxisMetadataClient
from ax_devil_rtsp.metadata_raw import run_metadata_client
from ax_devil_rtsp.logging import configure_logging

logger = logging.getLogger("ax-devil-rtsp.cli")

def build_rtsp_url(args: argparse.Namespace) -> str:
    """Build RTSP URL from command line args."""
    return f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"

def print_metadata(xml_text: str) -> None:
    """Log and print camera metadata."""
    logger.debug("Received metadata:\n%s", xml_text)
    print(xml_text)

def display_video_stream(args: argparse.Namespace) -> None:
    """Display RTSP video stream in a window. Press 'q' to quit."""
    rtsp_url = build_rtsp_url(args)
    logger.debug("Attempting to open RTSP stream: %s", rtsp_url)
    cap = cv2.VideoCapture(rtsp_url)
    
    if not cap.isOpened():
        logger.error("Failed to open RTSP stream: %s", rtsp_url)
        return
    
    window_name = "RTSP Stream"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    
    if args.fullscreen:
        logger.debug("Setting fullscreen mode")
        cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        logger.debug("Setting window size: %dx%d", args.width, args.height)
        cv2.resizeWindow(window_name, args.width, args.height)
    
    logger.info("Starting video stream display")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to read frame from stream")
                break
            
            cv2.imshow(window_name, frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Stream display stopped by user")
                break
                
    except KeyboardInterrupt:
        logger.info("Stream display interrupted by user")
    finally:
        logger.debug("Cleaning up video capture resources")
        cap.release()
        cv2.destroyAllWindows()

def metadata_gstreamer(args: argparse.Namespace) -> None:
    """Run GStreamer-based metadata client."""
    rtsp_url = build_rtsp_url(args)
    logger.info("Starting GStreamer metadata client")
    try:
        client = AxisMetadataClient(rtsp_url, latency=args.latency, raw_data_callback=print_metadata)
        client.start()
    except Exception as e:
        logger.error("Failed to start GStreamer metadata client: %s", e)
        sys.exit(1)
    finally:
        logger.info("Shutting down AxisMetadataClient")

def metadata_raw(args: argparse.Namespace) -> None:
    """Run raw RTSP metadata client."""
    run_metadata_client(args)

def cli() -> NoReturn:
    """CLI entry point for video streaming and metadata tools."""
    parser = argparse.ArgumentParser(
        description="Axis Devil RTSP Client Tools",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Add --debug flag for debug logging
    parser.add_argument("--debug",
                       action="store_true",
                       help="Enable debug logging")
    
    parser.add_argument("--ip", 
                       default=os.getenv("AX_DEVIL_TARGET_ADDR", "192.168.1.81"),
                       help="Camera IP address")
    parser.add_argument("--username", 
                       default=os.getenv("AX_DEVIL_TARGET_USER", "root"),
                       help="RTSP username")
    parser.add_argument("--password", 
                       default=os.getenv("AX_DEVIL_TARGET_PASS", "fusion"),
                       help="RTSP password")
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    gst_parser = subparsers.add_parser('metadata-gst', 
                                      help='GStreamer-based metadata client')
    gst_parser.add_argument("--uri", 
                           default="axis-media/media.amp?analytics=polygon",
                           help="RTSP URI path")
    gst_parser.add_argument("--latency",
                           type=int,
                           default=100,
                           help="RTSP latency in ms")
    
    raw_parser = subparsers.add_parser('metadata-raw',
                                      help='Raw RTSP metadata client')

    video_parser = subparsers.add_parser('video',
                                        help='Display video stream in a window')
    video_parser.add_argument("--uri",
                             default="axis-media/media.amp",
                             help="RTSP URI path")
    video_parser.add_argument("--width",
                             type=int,
                             default=1280,
                             help="Initial window width")
    video_parser.add_argument("--height",
                             type=int,
                             default=720,
                             help="Initial window height")
    video_parser.add_argument("--fullscreen",
                             action="store_true",
                             help="Start in fullscreen mode")

    args = parser.parse_args()

    # Configure logging based on debug flag
    configure_logging(level=logging.DEBUG if args.debug else logging.INFO)

    if args.command == 'metadata-gst':
        metadata_gstreamer(args)
    elif args.command == 'metadata-raw':
        metadata_raw(args)
    elif args.command == 'video':
        display_video_stream(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    cli()