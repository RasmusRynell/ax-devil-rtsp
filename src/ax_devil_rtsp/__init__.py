"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .gstreamer_data_grabber import CombinedRTSPClient
from .deps import ensure_gi_ready

__version__ = "0.1.0"

__all__ = [
    "CombinedRTSPClient",
    "ensure_gi_ready",
]
