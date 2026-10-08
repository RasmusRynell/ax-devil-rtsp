"""Axis media URL construction."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from .session import StreamConfig


def build_axis_rtsp_url(
    host: str,
    config: StreamConfig,
    *,
    username: str = "",
    password: str = "",
    port: int | None = None,
    camera: int | str = 1,
    resolution: str | None = None,
    capture_time: bool = True,
) -> str:
    """Build an Axis `axis-media/media.amp` URL that carries the streams `config` requests.

    Args:
        host: Camera IP address or host name.
        config: The session configuration; its `video` and `metadata` choose the media.
        username: Camera user; percent-encoded into the URL.
        password: Camera password; percent-encoded into the URL.
        port: RTSP port, or None for 554.
        camera: Video source (camera head or view area).
        resolution: Video resolution such as "1920x1080", or None for the camera default.
        capture_time: Ask the camera to send each video frame's capture time (`onvifreplayext=1`).
    """
    if not host:
        raise ValueError("no camera host given")
    credentials = f"{quote(username, safe='')}:{quote(password, safe='')}@" if username or password else ""
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    params = {"camera": str(camera), "audio": "0"}
    if config.video is None:
        params["video"] = "0"
    else:
        if resolution:
            params["resolution"] = resolution
        if capture_time:
            params["onvifreplayext"] = "1"
    if config.metadata:
        params["analytics"] = "polygon"
    return f"rtsp://{credentials}{netloc}/axis-media/media.amp?{urlencode(params)}"
