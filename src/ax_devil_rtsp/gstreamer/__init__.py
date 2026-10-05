"""
GStreamer-based RTSP client components.

This module provides the core GStreamer-based RTSP client functionality
for handling video and application data streams from Axis cameras.
"""

from ..utils.deps import use_gstreamer_wheels

# The submodules import gi at import time.
use_gstreamer_wheels()

from .client import CombinedRTSPClient  # noqa: E402
from .utils import run_combined_client_simple_example  # noqa: E402

__all__ = [
    "CombinedRTSPClient",
    "run_combined_client_simple_example"
]
