"""
Utility functions for GStreamer RTSP operations.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from typing import Any, Callable, Dict, Optional

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import Gst

logger = logging.getLogger("ax-devil-rtsp.gstreamer.utils")


def _map_buffer(buf: Gst.Buffer) -> tuple[bool, Gst.MapInfo]:
    """Map a GStreamer buffer for reading."""
    return buf.map(Gst.MapFlags.READ)


def _to_rgb_array(info: Gst.MapInfo, width: int, height: int, fmt: str) -> np.ndarray:
    """Convert raw buffer data into an RGB numpy array based on format."""
    data = info.data
    if fmt == "RGB":
        return np.frombuffer(data, np.uint8).reshape(height, width, 3)
    if fmt in ("RGB16", "BGR16"):
        return np.frombuffer(data, np.uint16).reshape(height, width)
    raise ValueError(f"Unsupported pixel format {fmt}")


def run_combined_client_simple_example(
    rtsp_url: str,
    *,
    latency: int = 200,
    queue: Optional[mp.Queue] = None,
    video_processing_fn: Optional[Callable[[Dict[str, Any], dict], Any]] = None,
    shared_config: Optional[dict] = None,
) -> None:
    """Example runner: spawns client and logs or queues payloads."""
    from .client import CombinedRTSPClient
    
    def vid_cb(pl: dict) -> None:
        if queue:
            queue.put({**pl, 'kind': 'video'})
        else:
            logger.info("VIDEO frame %s", pl['data'].shape)

    def application_data_cb(pl: dict) -> None:
        if queue:
            queue.put({**pl, 'kind': 'application_data'})
        else:
            logger.info("XML %d bytes", len(pl['data']))

    def sess_cb(md: dict) -> None:
        logger.debug("SESSION-MD: %s", md)

    def err_cb(error: dict) -> None:
        if queue:
            queue.put({**error, 'kind': 'error'})
        else:
            logger.error("ERROR %s: %s", error.get('error_type'), error.get('message'))

    client = CombinedRTSPClient(
        rtsp_url,
        latency=latency,
        video_frame_callback=vid_cb,
        application_data_callback=application_data_cb,
        stream_session_metadata_callback=sess_cb,
        error_callback=err_cb,
        video_processing_fn=video_processing_fn,
        shared_config=shared_config or {},
    )
    client.start() 