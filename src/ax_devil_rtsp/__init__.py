"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .gstreamer_data_grabber import CombinedRTSPClient

__version__ = "0.1.0"

__all__ = [
    "CombinedRTSPClient",
]
