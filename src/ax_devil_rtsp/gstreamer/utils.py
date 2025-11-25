"""
Utility functions for GStreamer RTSP operations.
"""

from __future__ import annotations
from ..utils.logging import get_logger
from gi.repository import Gst

import multiprocessing as mp
from typing import Any, Callable, Dict, Optional

import gi
import numpy as np

gi.require_version("Gst", "1.0")


logger = get_logger(__name__)


def _map_buffer(buf: Gst.Buffer) -> tuple[bool, Gst.MapInfo]:
    """Map a GStreamer buffer for reading."""
    return buf.map(Gst.MapFlags.READ)


def _to_rgb_array(info: Gst.MapInfo, width: int, height: int, fmt: str) -> np.ndarray:
    """Optimized conversion of GStreamer buffer to RGB numpy array."""
    view = memoryview(info.data)

    if fmt == "RGB":
        return np.frombuffer(view, np.uint8).reshape((height, width, 3))

    elif fmt == "BGR":
        arr = np.frombuffer(view, np.uint8).reshape((height, width, 3))
        # Swap channels without copying using a slice view
        return arr[..., ::-1]

    elif fmt in ("RGBx", "xRGB"):
        arr = np.frombuffer(view, np.uint8).reshape((height, width, 4))
        return arr[..., :3]  # No copy unless forced downstream

    elif fmt in ("BGRx", "xBGR"):
        arr = np.frombuffer(view, np.uint8).reshape((height, width, 4))
        # Drop alpha and swap with a zero-copy slice
        return arr[..., 2::-1]

    elif fmt == "RGBA":
        arr = np.frombuffer(view, np.uint8).reshape((height, width, 4))
        return arr[..., :3]

    elif fmt == "BGRA":
        arr = np.frombuffer(view, np.uint8).reshape((height, width, 4))
        # Discard alpha channel and reverse order via view
        return arr[..., 2::-1]

    elif fmt == "RGB16":
        arr = np.frombuffer(view, np.uint16).reshape((height, width, 3))
        return arr

    elif fmt == "BGR16":
        arr = np.frombuffer(view, np.uint16).reshape((height, width, 3))
        # 16-bit channel swap using slicing for a view
        return arr[..., ::-1]

    raise ValueError(f"Unsupported pixel format: {fmt}")


def run_combined_client_simple_example(
    rtsp_url: str,
    *,
    latency: int = 200,
    queue: Optional[mp.Queue] = None,
    video_processing_fn: Optional[Callable[[
        Dict[str, Any], dict], Any]] = None,
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
            logger.error("ERROR %s: %s", error.get(
                'error_type'), error.get('message'))

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
