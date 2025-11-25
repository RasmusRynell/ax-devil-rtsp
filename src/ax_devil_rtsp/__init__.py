"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .rtsp_data_retrievers import (
    RtspPayload,
    VideoDataCallback,
    ApplicationDataCallback,
    ErrorCallback,
    SessionStartCallback,
    RtspDataRetriever,
    RtspVideoDataRetriever,
    RtspApplicationDataRetriever,
)
from .utils import build_axis_rtsp_url
from .deps import ensure_gi_ready

__version__ = "0.2.0"

__all__ = [
    "RtspPayload",
    "VideoDataCallback",
    "ApplicationDataCallback",
    "ErrorCallback",
    "SessionStartCallback",
    "RtspDataRetriever",
    "RtspVideoDataRetriever",
    "RtspApplicationDataRetriever",
    "build_axis_rtsp_url",
    "ensure_gi_ready",
]
