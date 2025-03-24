#!/usr/bin/env python3
"""
Example usage for the RTSPMetadataClient library (metadata only).

This example demonstrates both synchronous and asynchronous modes
to receive XML metadata from an Axis camera using GStreamer.
"""

import argparse
import asyncio
import logging
import signal
import threading

from rtsp_metadata_client import RTSPMetadataClient

# Set up basic logging configuration.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def run_sync_metadata_example(args):
    """
    Synchronous Metadata Example:
    Uses a default callback that prints the received XML metadata.
    """
    def metadata_callback(xml_data):
        try:
            xml_text = xml_data.decode('utf-8')
            print("----- Synchronous Metadata XML -----")
            print(xml_text)
        except Exception as e:
            print("Error decoding metadata XML:", e)
    
    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"
    logger.info("Running synchronous metadata example with RTSP URL: %s", rtsp_url)
    client = RTSPMetadataClient(rtsp_url, latency=args.latency, metadata_handler_callback=metadata_callback)
    client.start()

def run_async_metadata_example(args):
    """
    Asynchronous Metadata Example:
    - Runs the RTSPMetadataClient (GLib MainLoop) in a separate thread.
    - Uses an asyncio queue to process XML metadata in the main thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async_queue = asyncio.Queue(maxsize=10)
    
    def metadata_callback(xml_data):
        # Enqueue XML metadata onto the asyncio queue.
        asyncio.run_coroutine_threadsafe(async_queue.put(xml_data), loop)
    
    rtsp_url = f"rtsp://{args.username}:{args.password}@{args.ip}/{args.uri}"
    logger.info("Running asynchronous metadata example with RTSP URL: %s", rtsp_url)
    client = RTSPMetadataClient(rtsp_url, latency=args.latency, metadata_handler_callback=metadata_callback)
    
    client_thread = threading.Thread(target=client.start, daemon=True)
    client_thread.start()
    
    async def process_metadata():
        while True:
            xml_data = await async_queue.get()
            try:
                xml_text = xml_data.decode('utf-8')
                print("----- Asynchronous Metadata XML -----")
                print(xml_text)
            except Exception as e:
                print("Error decoding metadata XML:", e)
            async_queue.task_done()
    
    async def main():
        try:
            metadata_task = asyncio.create_task(process_metadata())
            await metadata_task
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
    parser = argparse.ArgumentParser(description="RTSP Metadata Client Example")
    parser.add_argument("--ip", required=True, help="Camera IP address")
    parser.add_argument("--username", required=True, help="RTSP username")
    parser.add_argument("--password", required=True, help="RTSP password")
    parser.add_argument("--uri", default="axis-media/media.amp?analytics=polygon",
                        help="RTSP URI path for metadata (e.g. analytics=polygon)")
    parser.add_argument("--latency", type=int, default=100, help="RTSP stream latency in ms (default: 100)")
    parser.add_argument("--log-level", default="DEBUG", help="Logging level (DEBUG, INFO, WARNING)")
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
        run_sync_metadata_example(args)
    else:
        run_async_metadata_example(args)
