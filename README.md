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

On Linux, this package depends on native GStreamer, GI, and Cairo libraries.

```bash
sudo apt-get update
sudo apt-get install -y \
  gcc cmake pkg-config python3-dev libcairo2-dev libffi-dev libglib2.0-dev \
  libgirepository-2.0-dev gobject-introspection \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-libav

pip install ax-devil-rtsp
```

On Arch Linux:

```bash
sudo pacman -S --needed base-devel cairo glib2 libffi pkgconf gstreamer \
  gst-plugins-base-libs gst-plugins-good gst-plugins-bad-libs gst-libav
```

On Windows and macOS, pip installs everything, including GStreamer and PyGObject
from the official [GStreamer wheels](https://pypi.org/project/gstreamer-meta/)
(CPython 3.10 to 3.14; on Windows 64-bit or 32-bit, about 100 MB download):

```bash
pip install ax-devil-rtsp
```

On Windows, ARM64 Python is not supported because the wheels have no ARM64 build;
on an ARM64 machine, use x64 Python. When Python starts, the wheels add their GStreamer to
`PATH`, `PYTHONPATH` and the `GST_*`, `GI_*` and `XDG_*` variables of the process,
and programs it launches inherit them.

### Check your setup

`ax-devil-rtsp doctor` checks GStreamer and prints the install command for anything
missing (apt, pacman, and pip on Windows/macOS). Add `--json` for machine-readable output.

From Python, for example in another project:

```python
from ax_devil_rtsp import check_environment, install_command

report = check_environment()
if not report.ok:
    print(report.install_command)  # only the missing packages

print(install_command())  # full setup command for this OS, None if unsupported
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

### Raw socket metadata client

A minimal RTSP client in plain Python sockets, without GStreamer. It's handy for quick
tests and as a readable example of the RTSP handshake.

```python
from ax_devil_rtsp.raw_socket.metadata_raw import SceneMetadataRawClient

client = SceneMetadataRawClient(
    "rtsp://admin:secret@192.168.1.90/axis-media/media.amp?analytics=polygon&video=0",
    raw_data_callback=print,  # called with each XML document as a string
)
client.start()  # blocks until the stream ends or client.stop() is called
```

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
