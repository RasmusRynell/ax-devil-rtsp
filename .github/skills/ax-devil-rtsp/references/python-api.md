# Python API Reference

```python
from ax_devil_rtsp import (
    SceneMetadata,  # one scene metadata XML document
    StartCancelledError,  # stop() was called before the session was ready
    StreamConfig,  # what a session receives
    StreamError,  # credential-safe connection/protocol failure
    StreamSession,  # one RTSP connection
    VideoOutput,  # what each video frame is delivered as
    VideoSample,  # one video frame or access unit
    build_axis_rtsp_url,  # Axis URL from host, credentials and a StreamConfig
)
```

## StreamConfig

```python
StreamConfig(
    video: VideoOutput | None = VideoOutput.RGB24,  # None: no video
    metadata: bool = False,
    hwaccel: str | None = None,   # FFmpeg device type, e.g. "vaapi", "cuda"; see `ax-devil-rtsp doctor`
    timeout: float = 15.0,        # seconds to become ready, and without data before failing
)
```

At least one of `video` and `metadata` must be requested.

| `VideoOutput` | `VideoSample.data` |
|---|---|
| `ENCODED` | Annex-B H.264/H.265 `bytes` (first one starts with the SDP parameter sets) |
| `DECODED` | `av.VideoFrame`, decoder's native pixel format |
| `RGB24`, `BGR24` | `uint8` array `(height, width, 3)` |
| `RGBA`, `BGRA` | `uint8` array `(height, width, 4)` |
| `GRAY` | `uint8` array `(height, width)` |

## StreamSession

```python
StreamSession(
    url: str,
    config: StreamConfig,
    *,
    on_video: Callable[[VideoSample], None] | None = None,      # exactly when config.video is set
    on_metadata: Callable[[SceneMetadata], None] | None = None, # exactly when config.metadata is True
    on_failure: Callable[[BaseException], None] | None = None,  # once, if it fails after start() returned
)
```

| Member | Meaning |
|---|---|
| `start()` | Connects; returns when PLAY succeeded. Raises `StreamError` or `StartCancelledError`. One-shot |
| `stop()` | Non-blocking, idempotent, safe in callbacks |
| `join(timeout=None)` | Wait for the session to end; not from a callback |
| `with session:` | `start()`, then `stop()` and `join()` on exit |
| `is_running` | Receive thread alive |
| `failure` | `None`, a `StreamError`, or the exception a callback raised |
| `video_codec` | `"h264"` or `"hevc"` after `start()`, else `None` |
| `name` | The URL without credentials |

Callbacks run on the session's own receive thread, one at a time, in stream order. No queue sits in between: a slow
callback slows its own session only. Delivered objects belong to the receiver.

## VideoSample and SceneMetadata

```python
VideoSample.data  # see VideoOutput; generic: VideoSample[NDArray[np.uint8]], VideoSample[bytes], ...
VideoSample.rtp_timestamp  # 90 kHz RTP timestamp
VideoSample.capture_time_ns  # Axis capture time, Unix ns, or None
VideoSample.keyframe  # bool

SceneMetadata.xml  # str, one complete document
SceneMetadata.rtp_timestamp
SceneMetadata.capture_time_ns  # Unix ns or None
SceneMetadata.utc_time_ns  # first UtcTime in the XML as Unix ns, or None
```

## build_axis_rtsp_url

```python
build_axis_rtsp_url(
    host: str,
    config: StreamConfig,       # chooses video=0 / analytics=polygon
    *,
    username: str = "",
    password: str = "",         # percent-encoded into the URL
    port: int | None = None,
    camera: int | str = 1,
    resolution: str | None = None,   # e.g. "1280x720"
    capture_time: bool = True,       # onvifreplayext=1, needed for capture_time_ns
) -> str
```

## Examples

### NumPy frames and metadata

```python
import time
from ax_devil_rtsp import StreamConfig, StreamSession, VideoOutput, build_axis_rtsp_url

config = StreamConfig(video=VideoOutput.BGR24, metadata=True)
url = build_axis_rtsp_url("192.168.1.90", config, username="root", password="secret")

with StreamSession(
    url,
    config,
    on_video=lambda sample: print(sample.data.shape, sample.capture_time_ns),
    on_metadata=lambda document: print(document.utc_time_ns, len(document.xml)),
) as session:
    time.sleep(10)
```

### Latest frame for a GUI thread (drop, don't queue)

```python
import threading

latest = None
lock = threading.Lock()


def on_video(sample):
    global latest
    with lock:
        latest = sample  # the GUI thread reads `latest`; older frames are dropped
```

### Match metadata to frames

```python
from collections import deque

recent = deque(maxlen=60)  # (capture_time_ns, sample)


def on_video(sample):
    if sample.capture_time_ns is not None:
        recent.append((sample.capture_time_ns, sample))


def on_metadata(document):
    t = document.utc_time_ns
    if t is not None and recent:
        capture, frame = min(list(recent), key=lambda item: abs(item[0] - t))
        print(f"document matches frame {frame.rtp_timestamp}, {abs(capture - t) / 1e6:.1f} ms apart")
```

When video and metadata come from the same session, both callbacks run on the same thread, so no lock is needed here.

### Failure handling

```python
from ax_devil_rtsp import StreamError

session = StreamSession(url, config, on_video=on_video, on_failure=lambda exc: print("failed:", exc))
try:
    session.start()
except StreamError as exc:
    print("could not start:", exc)
```
