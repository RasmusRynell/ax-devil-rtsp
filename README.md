<p align="center">
  <img src="./resources/ax-devil-banner.png" alt="ax-devil banner" width="100%"/>
</p>

# ax-devil-rtsp

<div align="center">

Python package for receiving RTSP video and AXIS Scene Metadata from Axis cameras, with per-frame capture times for
matching the two. Includes a Python API with callbacks and a CLI for quick inspection.

See also [ax-devil-device-api](https://github.com/rasmusrynell/ax-devil-device-api) and [ax-devil-mqtt](https://github.com/rasmusrynell/ax-devil-mqtt) for related tools.

</div>

---

## Install

```bash
pip install ax-devil-rtsp
```

That is all: decoding uses [PyAV](https://pyav.basswood-io.com/), whose wheels bundle FFmpeg for Linux, macOS and
Windows. No system packages are needed. `pip install 'ax-devil-rtsp[display]'` adds OpenCV for the CLI's video window.

`ax-devil-rtsp doctor` shows the PyAV and FFmpeg versions, whether the H.264 and H.265 decoders are present, and which
hardware decoding devices FFmpeg can use.

---

## Python API

```python
import time

from ax_devil_rtsp import SceneMetadata, StreamConfig, StreamSession, VideoOutput, VideoSample, build_axis_rtsp_url

config = StreamConfig(video=VideoOutput.RGB24, metadata=True)
url = build_axis_rtsp_url("192.168.1.90", config, username="root", password="secret", resolution="1280x720")


def on_video(sample: VideoSample) -> None:
    print("frame", sample.data.shape, "captured at", sample.capture_time_ns)


def on_metadata(document: SceneMetadata) -> None:
    print("metadata", len(document.xml), "characters, UtcTime", document.utc_time_ns)


with StreamSession(url, config, on_video=on_video, on_metadata=on_metadata) as session:
    time.sleep(10)
if session.failure:
    print("stream failed:", session.failure)
```

### Sessions

- A `StreamSession` is one RTSP connection with a fixed `StreamConfig`. It receives at most one video and one scene
  metadata stream. It is one-shot: create a new session to reconnect.
- `start()` returns once the camera accepted PLAY. It raises `StreamError` when the connection, authentication or
  stream setup fails, or `StartCancelledError` if `stop()` was called first. `with session:` starts, then stops and
  waits on exit.
- `stop()` never blocks and may be called from callbacks. `join()` waits for the session to end.
- Sessions are independent; run as many as you need.

### Callbacks and threads

Each session runs one receive thread. It reads the socket, reassembles RTP, decodes, converts and calls your
callbacks one at a time, in stream order. There are no hidden queues: a slow callback slows only its own session, and
the camera's TCP stream backs up instead of memory growing. Hand data to other threads yourself, and drop frames there
if your consumer is slower than the camera.

A separate sender keeps RTSP alive even while media is idle or a callback is blocked. It never invokes callbacks
and ends with the session. Stopping shuts down the TCP connection immediately rather than waiting to send TEARDOWN.

Every delivered value is owned by the receiver; keep it as long as you like.

If a callback raises, the session stops and that exception becomes `session.failure`. If the connection, the camera or
decoding fails, `failure` is a `StreamError` whose message never contains credentials. Either is also passed to
`on_failure`, once, if the session was already running.

### What you receive

`StreamConfig.video` chooses what `VideoSample.data` is for the whole session:

| `VideoOutput` | `data` |
|---|---|
| `ENCODED` | Annex-B H.264/H.265 access unit `bytes`, nothing decoded. `session.video_codec` says which codec |
| `DECODED` | `av.VideoFrame` in the decoder's native pixel format, for your own conversion or GPU upload |
| `RGB24`, `BGR24` | `uint8` NumPy array, shape (height, width, 3) |
| `RGBA`, `BGRA` | `uint8` NumPy array, shape (height, width, 4), ready for Qt `Format_RGBX8888` or GPU textures |
| `GRAY` | `uint8` NumPy array, shape (height, width) |

`VideoSample` is generic, so typed callbacks can declare what they get, for example
`VideoSample[NDArray[np.uint8]]`. Each sample also has the frame's `rtp_timestamp`, `keyframe` flag and
`capture_time_ns`.

`SceneMetadata` holds one complete scene metadata XML document as `xml`, plus its `rtp_timestamp` and
`capture_time_ns`. Parsing the XML is up to you.

`StreamConfig.hwaccel` names an FFmpeg hardware device type such as `"vaapi"` or `"cuda"` for decoding.

### Matching video and metadata

With `onvifreplayext=1` in the URL (on by default in `build_axis_rtsp_url`), the camera sends the capture time of
every video frame. `sample.capture_time_ns` holds it in Unix nanoseconds. A scene metadata document names the frame it
describes in its `UtcTime` attribute; `document.utc_time_ns` returns it. On Axis cameras the two agree within about a
millisecond, the precision of `UtcTime`. `ax-devil-rtsp stream` prints this distance every second.

### URLs

`build_axis_rtsp_url(host, config, ...)` builds an Axis `axis-media/media.amp` URL that asks for exactly the streams in
`config`: `analytics=polygon` when metadata is requested, `video=0` when video is not. Options: `username`,
`password`, `port`, `camera` (video source), `resolution` and `capture_time`.

Any other RTSP URL is used as given, including its credentials. Only `rtsp://` over TCP is supported.

If a metadata stream gives `400 Bad Request`, the camera's scene metadata producer is probably disabled; enable
`AnalyticsSceneDescription` for that channel, for example with
`ax-devil-device-api analytics-metadata enable AnalyticsSceneDescription -c 1`.

### Logging

The package logs through the standard `logging` module under the `ax_devil_rtsp` logger and configures no handlers.

---

## CLI

Set `AX_DEVIL_TARGET_ADDR`, `AX_DEVIL_TARGET_USER` and `AX_DEVIL_TARGET_PASS` to skip the device options.

```bash
# Video and metadata; prints frame rate, capture-time coverage, metadata rate and sync once per second
ax-devil-rtsp stream --device-ip 192.168.1.90 --device-username root --device-password secret

# Show the video in a window (needs ax-devil-rtsp[display])
ax-devil-rtsp stream --display

# Metadata only, printing each document
ax-devil-rtsp stream --video none --print-xml

# Any RTSP URL, encoded video only
ax-devil-rtsp stream --url "rtsp://root:secret@192.168.1.90/axis-media/media.amp" --video encoded --no-metadata

ax-devil-rtsp doctor
```

Run `ax-devil-rtsp stream --help` for every option.

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest           # offline: a local fake camera serves real H.264/H.265 and metadata over RTSP
ruff check . && ruff format --check .
mypy
```

`tools/bench.py` measures CPU, memory, frame rate, latency and sync for one or more sessions against a real camera.

---

## Disclaimer

This project is an independent, community-driven implementation and is **not** affiliated with or endorsed by Axis Communications AB. For official APIs and development resources, see the [Axis Developer Community](https://www.axis.com/en-us/developer).

## License

MIT License - see [LICENSE](LICENSE) for details.
