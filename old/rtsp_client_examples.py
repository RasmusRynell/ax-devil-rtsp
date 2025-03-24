#!/usr/bin/env python3
"""
Example usage for the RTSPClient library.
"""

import argparse
import asyncio
import logging
import signal
import threading

from rtsp_client import RTSPClient

# Set up basic logging configuration (the level here is a placeholder).
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def run_sync_example(args):
    """
    Synchronous Example:
    Uses a default synchronous callback that prints frame information.
    """
    def sync_callback(buffer, rtp_info):
        if rtp_info:
            print(f"Synchronous RTP Info: {rtp_info}")
        else:
            print("No RTP extension data available in sync callback.")

    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"
    logger.info("Running synchronous example with RTSP URL: %s", rtsp_url)
    client = RTSPClient(rtsp_url, latency=args.latency, frame_handler_callback=sync_callback)
    client.start()

def run_async_example(args):
    """
    Asynchronous Example:
      - Runs the asyncio event loop in the main thread.
      - Runs RTSPClient (GLib MainLoop) in a separate thread.
      - The frame callback enqueues frames onto an asyncio queue managed by the main thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Create an asyncio queue for frame processing.
    async_queue = asyncio.Queue(maxsize=10)

    def async_callback(buffer, rtp_info):
        # This callback is called from the RTSPClient thread.
        # Use run_coroutine_threadsafe to add the frame to the main thread's asyncio queue.
        asyncio.run_coroutine_threadsafe(async_queue.put((buffer, rtp_info)), loop)

    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"
    logger.info("Running asynchronous example with RTSP URL: %s", rtsp_url)
    client = RTSPClient(rtsp_url, latency=args.latency, frame_handler_callback=async_callback)

    # Start the RTSPClient in a separate thread.
    client_thread = threading.Thread(target=client.start, daemon=True)
    client_thread.start()

    async def process_frames():
        while True:
            buffer, rtp_info = await async_queue.get()
            if rtp_info:
                print(f"Async processing RTP Info: {rtp_info}")
            else:
                print("No RTP extension data available in async processing.")
            async_queue.task_done()

    async def main():
        try:
            frame_task = asyncio.create_task(process_frames())
            await frame_task
        except asyncio.CancelledError:
            logger.info("Async tasks canceled.")

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
        client.stop()
        client_thread.join()
        loop.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RTSP Client Example")
    parser.add_argument("--ip", required=True, help="Camera IP address")
    parser.add_argument("--username", required=True, help="RTSP username")
    parser.add_argument("--password", required=True, help="RTSP password")
    parser.add_argument("--uri", default="axis-media/media.amp?onvifreplayext=1",
                        help="RTSP URI path (default includes onvifreplayext=1)")
    parser.add_argument("--latency", type=int, default=100, help="RTSP stream latency in ms (default: 100)")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")
    parser.add_argument("--mode", default="async", choices=["sync", "async"],
                        help="Example mode: 'sync' for synchronous callback, 'async' for asynchronous callback")
    args = parser.parse_args()

    # Set the root logger's level based on the provided argument.
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, args.log_level.upper(), logging.DEBUG))
    logger.info("Root logger level set to %s", args.log_level.upper())

    # Graceful shutdown on SIGINT.
    def shutdown_handler(signum, frame):
        logger.info("Signal %s received. Shutting down...", signum)
        exit(0)
    signal.signal(signal.SIGINT, shutdown_handler)

    if args.mode == "sync":
        run_sync_example(args)
    else:
        run_async_example(args)
