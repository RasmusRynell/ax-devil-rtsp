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

__version__ = "0.1.0"

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
]