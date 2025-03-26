"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .video_gstreamer import VideoGStreamerClient
from .metadata_gstreamer import SceneMetadataClient
from .metadata_raw import SceneMetadataRawClient

__version__ = "0.1.0"

__all__ = [
    "VideoGStreamerClient",
    "SceneMetadataClient",
    "SceneMetadataRawClient",
]
