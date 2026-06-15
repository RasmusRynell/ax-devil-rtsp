"""
AX Devil RTSP - A Python package for handling RTSP streams from Axis cameras.
"""

from .recording import RawRecordingConfig
from .rtsp_data_retrievers import (
    ApplicationDataCallback,
    ErrorCallback,
    RtspApplicationDataRetriever,
    RtspDataRetriever,
    RtspPayload,
    RtspVideoDataRetriever,
    SessionStartCallback,
    VideoDataCallback,
)
from .utils import build_axis_rtsp_url
from .utils.deps import ensure_gi_ready

__version__ = "0.2.3"

__all__ = [
    "RtspPayload",
    "VideoDataCallback",
    "ApplicationDataCallback",
    "ErrorCallback",
    "SessionStartCallback",
    "RtspDataRetriever",
    "RtspVideoDataRetriever",
    "RtspApplicationDataRetriever",
    "RawRecordingConfig",
    "build_axis_rtsp_url",
    "ensure_gi_ready",
]
