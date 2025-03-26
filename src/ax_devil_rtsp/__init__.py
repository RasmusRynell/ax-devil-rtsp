"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .metadata_gstreamer import AxisMetadataClient
from .metadata_raw import RTSPProtocolClient, MetadataHandler
from .video_gstreamer import VideoGStreamerClient

__version__ = "0.1.0"

__all__ = [
    "AxisMetadataClient",
    "RTSPProtocolClient",
    "MetadataHandler",
    "VideoGStreamerClient",
]
