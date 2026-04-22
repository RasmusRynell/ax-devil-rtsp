# ax-devil-rtsp Python API Reference

**Install**: `pip install ax-devil-rtsp` (or `uv pip install ax-devil-rtsp`)
**System deps**: GStreamer + GI bindings (see `ax-devil-rtsp doctor`)
**Depends on**: `numpy`, `opencv-python`, `click`, `rich`, `urllib3`, `PyGObject`

The Python API does not read environment variables directly. You must pass `ip`, `username`, and `password` explicitly to `build_axis_rtsp_url()`. The CLI falls back to `AX_DEVIL_TARGET_ADDR`, `AX_DEVIL_TARGET_USER`, and `AX_DEVIL_TARGET_PASS` when flags are omitted.

Public exports from `ax_devil_rtsp`:

- `RtspDataRetriever` — Combined video + application data retriever
- `RtspVideoDataRetriever` — Video-only retriever
- `RtspApplicationDataRetriever` — Application data (metadata) only retriever
- `build_axis_rtsp_url()` — Build RTSP URL from device parameters
- Callback type aliases: `VideoDataCallback`, `ApplicationDataCallback`, `ErrorCallback`, `SessionStartCallback`
- `RtspPayload` — Type alias: `Dict[str, Any]`
- `ensure_gi_ready()` — Verify GStreamer/GI bindings are available (raises on failure)

## build_axis_rtsp_url

Constructs an RTSP URL for Axis cameras.

```python
from ax_devil_rtsp import build_axis_rtsp_url

url = build_axis_rtsp_url(
    ip="<device-ip>",              # Required
    username="<user>",             # Required
    password="<pass>",             # Required
    video_source=1,                # Required: camera head index
    get_video_data=True,           # Required: include video stream
    get_application_data=True,     # Required: include metadata stream
    rtp_ext=True,                  # Enable RTP extension (NTP timestamps)
    resolution="640x480",          # Optional: None lets device decide
)
# Returns: "rtsp://user:pass@ip/axis-media/media.amp?analytics=polygon&camera=1&..."
```

- At least one of `get_video_data` or `get_application_data` must be True.
- When `get_video_data=False`, video and audio are disabled in the URL.
- `resolution` only applies when `get_video_data=True`.

## Callback Signatures

```python
# Video data callback
def on_video_data(payload: dict) -> None:
    frame = payload["data"]  # numpy.ndarray, RGB format, shape (H, W, 3)
    # payload may also contain "latest_rtp_data" with NTP timestamp info

# Application data callback
def on_application_data(payload: dict) -> None:
    xml_bytes = payload["data"]       # bytes: ONVIF Scene Metadata XML
    diagnostics = payload["diagnostics"]  # dict with timing/stats

# Session start callback (fires once per RTP pad — typically video + app data)
def on_session_start(payload: dict) -> None:
    media = payload.get("caps_parsed", {}).get("media") \
         or payload.get("structure_parsed", {}).get("media")
    # media is "video" or "application"
    stream_name = payload["stream_name"]

# Error callback
def on_error(payload: dict) -> None:
    error_type = payload["error_type"]   # str
    message = payload["message"]         # str
```

## RtspDataRetriever

Combined video + application data retriever. Runs GStreamer in a subprocess.

```python
from ax_devil_rtsp import RtspDataRetriever, build_axis_rtsp_url

url = build_axis_rtsp_url(
    ip="<device-ip>", username="<user>", password="<pass>",
    video_source=1, get_video_data=True, get_application_data=True, rtp_ext=True,
)

retriever = RtspDataRetriever(
    rtsp_url=url,                           # Required
    on_video_data=on_video_data,            # Optional callback
    on_application_data=on_application_data,# Optional callback
    on_error=on_error,                      # Optional callback
    on_session_start=on_session_start,      # Optional callback
    latency=200,                            # GStreamer latency in ms (default: 200)
    video_processing_fn=None,               # Optional: process frames in GStreamer process
    shared_config=None,                     # Optional: dict shared with video_processing_fn
    connection_timeout=30,                  # Seconds (default: 30)
    log_level=None,                         # Optional: logging level for subprocess
    queue_idle_timeout=10.0,                # Seconds idle before exiting (default: 10)
)

# Context manager (recommended)
with retriever:
    while retriever.is_running:
        time.sleep(0.1)

# Or manual lifecycle
retriever.start()
# ... do work ...
retriever.stop()
```

Key behaviors:
- GStreamer runs in a **spawned subprocess**. The package forces `mp.set_start_method('spawn')`.
- **ALWAYS** use `if __name__ == "__main__":` guard. Call `freeze_support()` for Windows compatibility.
- The Python API default latency is `200` ms (the CLI default is `100` ms).
- `start()` raises `RuntimeError` if already started.
- `stop()` terminates the subprocess and cleans up.
- `is_running` property checks if the subprocess is alive.
- Callbacks fire on a dispatcher thread in the main process (not the subprocess).

## RtspVideoDataRetriever

Video-only retriever. Same interface as `RtspDataRetriever` but without `on_application_data`.

```python
from ax_devil_rtsp import RtspVideoDataRetriever

retriever = RtspVideoDataRetriever(
    rtsp_url=url,
    on_video_data=on_video_data,
    on_error=on_error,
    on_session_start=on_session_start,
    latency=200,
    connection_timeout=30,
)
```

## RtspApplicationDataRetriever

Application data (metadata) only. Same interface but without `on_video_data`.

```python
from ax_devil_rtsp import RtspApplicationDataRetriever

retriever = RtspApplicationDataRetriever(
    rtsp_url=url,
    on_application_data=on_application_data,
    on_error=on_error,
    on_session_start=on_session_start,
    latency=200,
    connection_timeout=30,
)
```

## Typical Python Workflows

### Stream video and metadata with callbacks

```python
import time
from multiprocessing import freeze_support
from ax_devil_rtsp import RtspDataRetriever, build_axis_rtsp_url

def on_video_data(payload):
    frame = payload["data"]
    print(f"Video frame: {frame.shape}")

def on_application_data(payload):
    print(f"Application data: {len(payload['data'])} bytes")

def on_error(payload):
    print(f"Error: {payload['message']}")

def main():
    url = build_axis_rtsp_url(
        ip="<device-ip>", username="<user>", password="<pass>",
        video_source=1, get_video_data=True, get_application_data=True, rtp_ext=True,
    )
    with RtspDataRetriever(rtsp_url=url, on_video_data=on_video_data,
                           on_application_data=on_application_data, on_error=on_error) as r:
        while r.is_running:
            time.sleep(0.1)

if __name__ == "__main__":
    freeze_support()
    main()
```

### Collect only scene metadata (no video)

```python
from ax_devil_rtsp import RtspApplicationDataRetriever, build_axis_rtsp_url

url = build_axis_rtsp_url(
    ip="<device-ip>", username="<user>", password="<pass>",
    video_source=1, get_video_data=False, get_application_data=True, rtp_ext=True,
)

metadata_frames = []

def on_app_data(payload):
    metadata_frames.append(payload["data"])

with RtspApplicationDataRetriever(rtsp_url=url, on_application_data=on_app_data) as r:
    import time
    time.sleep(10)  # Collect for 10 seconds
print(f"Collected {len(metadata_frames)} metadata frames")
```
