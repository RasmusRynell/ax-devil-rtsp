"""Receive RTSP video and Axis scene metadata from Axis cameras."""

from .rtsp import StreamError
from .session import SceneMetadata, StartCancelledError, StreamConfig, StreamSession, VideoOutput, VideoSample
from .url import build_axis_rtsp_url

__version__ = "0.5.1"

__all__ = [
    "SceneMetadata",
    "StartCancelledError",
    "StreamConfig",
    "StreamError",
    "StreamSession",
    "VideoOutput",
    "VideoSample",
    "build_axis_rtsp_url",
]
