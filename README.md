<p align="center">
  <img src="./resources/ax-devil-banner.png" alt="ax-devil banner" width="100%"/>
</p>

# ax-devil-rtsp

<div align="center">

Python package for streaming RTSP video and AXIS Scene Metadata (referred to here as "application data") from Axis devices. Includes a Python API with callbacks and a CLI demo for quick inspection.

See also [ax-devil-device-api](https://github.com/rasmusrynell/ax-devil-device-api) and [ax-devil-mqtt](https://github.com/rasmusrynell/ax-devil-mqtt) for related tools.

</div>

---

## Install

This package is the RTSP/GStreamer layer for the ax-devil tools. It is intentionally separate from the desktop app so that core/offline workflows can run without native RTSP dependencies.

### Current platform status

- Linux is the supported runtime today.
- Windows is not ready yet. The Python package imports can be made installable, but live RTSP still needs a working native GStreamer + GObject Introspection (`gi`) stack for Windows.
- The current Windows failure is not an Axis or Python API issue. It is the native binding layer: `PyGObject`/`gi` is not available in a normal Windows Python/uv environment, and building it from PyPI can fail because it expects compatible GStreamer/GI libraries and toolchains.

What needs to be fixed for Windows:

- Choose and document a supported Windows GStreamer distribution strategy, most likely MSYS2 or the official GStreamer runtime/development installers.
- Make `doctor` detect that setup and print Windows-specific guidance instead of Linux package names.
- Verify the required GStreamer elements and typelibs are available on Windows: `rtspsrc`, `rtph264depay`, `h264parse`, `avdec_h264`, `videoconvert`, `appsink`, `rtpjitterbuffer`, `Gst`, and `GstRtp`.
- Run an end-to-end RTSP test against an Axis device on Windows.

Until that work is done, use Linux/WSL for live RTSP development.

### Linux system dependencies

On Linux, this package depends on native GStreamer, GI, and Cairo libraries.

```bash
sudo apt-get update
sudo apt-get install -y \
  gcc cmake pkg-config python3-dev libcairo2-dev libffi-dev libglib2.0-dev \
  libgirepository-2.0-dev gobject-introspection \
  python3-gi python3-gst-1.0 \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav

pip install ax-devil-rtsp
```

### System dependencies (Linux)

```bash
# Check your environment after install
ax-devil-rtsp doctor
```

---

## Configure (optional)

Avoid repeating device credentials by exporting:

- `AX_DEVIL_TARGET_ADDR` – Device IP or hostname
- `AX_DEVIL_TARGET_USER` – Device username
- `AX_DEVIL_TARGET_PASS` – Device password

---

## CLI

Run `ax-devil-rtsp --help` for the full reference. Common flows:

- Connect to a device (builds the RTSP URL for you):
  ```bash
  ax-devil-rtsp --device-ip 192.168.1.90 --device-username admin --device-password secret
  ```
- Use an existing RTSP URL:
  ```bash
  ax-devil-rtsp --url "rtsp://admin:secret@192.168.1.90/axis-media/media.amp?analytics=polygon"
  ```
- Switch modes without changing the URL:
  ```bash
  # Video only
  ax-devil-rtsp ... --only-video

  # Application data only
  ax-devil-rtsp ... --only-application-data

  # Disable RTP extension data
  ax-devil-rtsp ... --no-rtp-ext
  ```
- Adjust the stream: `--resolution 1280x720`, `--source 2`, `--latency 200`
  (only applies when building the URL without `--url`)
- Optional helpers: `--enable-video-processing`, `--brightness-adjustment 25`, `--manual-lifecycle`
  (`--url` skips device-specific URL construction)
- Check host dependencies and workaround status: `ax-devil-rtsp doctor`

---

## Python API

```python
import time
from multiprocessing import freeze_support
from ax_devil_rtsp import RtspDataRetriever, build_axis_rtsp_url


def on_video_data(payload):
    frame = payload["data"]
    print(f"Video frame: {frame.shape}")


def on_application_data(payload):
    print(f"Application data bytes: {len(payload['data'])}")


def on_session_start(payload):
    media = payload.get("caps_parsed", {}).get("media") or payload.get(
        "structure_parsed", {}
    ).get("media")
    print(f"Session start for {media}: {payload['stream_name']}")


def on_error(payload):
    print(f"Error: {payload['message']}")


def main():
    rtsp_url = build_axis_rtsp_url(
        ip="192.168.1.90",
        username="username",
        password="password",
        video_source=1,
        get_video_data=True,
        get_application_data=True,
        rtp_ext=True,
        resolution="640x480",
    )

    retriever = RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_application_data=on_application_data,
        on_session_start=on_session_start,
        on_error=on_error,
        latency=100,
    )

    with retriever:
        print("Streaming... Press Ctrl+C to stop")
        while True:
            time.sleep(0.1)

# Expect `on_session_start` to run once for each RTP pad (typically
# one for video and one for application metadata). Use the parsed
# `media` field to tell them apart, as shown above.

if __name__ == "__main__":
    freeze_support()  # Required on Windows because the package forces 'spawn'
    main()
```

- `RtspVideoDataRetriever` and `RtspApplicationDataRetriever` are available for video-only or metadata-only flows.
- `on_session_start` is invoked once per RTP pad; the parsed `media` value distinguishes video vs. application data.
- Because the package forces the multiprocessing start method to `'spawn'`, keep the
  `if __name__ == "__main__":` guard around your entry point (all platforms).

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest
ruff check .
black src tests
```

---

## Disclaimer

This project is an independent, community-driven implementation and is **not** affiliated with or endorsed by Axis Communications AB. For official APIs and development resources, see the [Axis Developer Community](https://www.axis.com/en-us/developer).

## License

MIT License - see [LICENSE](LICENSE) for details.
