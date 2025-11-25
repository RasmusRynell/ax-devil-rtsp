# ax-devil-rtsp

<div align="center">

Python package for streaming RTSP video and AXIS Scene Metadata (referred to here as "application data") from Axis devices. Includes a Python API with callbacks and a CLI demo for quick inspection.

See also [ax-devil-device-api](https://github.com/rasmusrynell/ax-devil-device-api) and [ax-devil-mqtt](https://github.com/rasmusrynell/ax-devil-mqtt) for related tools.

</div>

---

## Install

```bash
pip install ax-devil-rtsp
```

### System dependencies (Linux)

PyGObject and GStreamer must be available via your package manager.

```bash
# Check what you already have
python tools/dep.py --check

# Show Ubuntu/Debian install commands
python tools/dep.py --install
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
  ax-devil-rtsp device --device-ip 192.168.1.90 --device-username admin --device-password secret
  ```
- Use an existing RTSP URL:
  ```bash
  ax-devil-rtsp url "rtsp://admin:secret@192.168.1.90/axis-media/media.amp?analytics=polygon"
  ```
- Switch modes without changing the URL:
  ```bash
  # Video only
  ax-devil-rtsp device ... --only-video

  # Application data only
  ax-devil-rtsp device ... --only-application-data

  # Disable RTP extension data
  ax-devil-rtsp device ... --no-rtp-ext
  ```
- Adjust the stream: `--resolution 1280x720`, `--source 2`, `--latency 200`
- Demo helpers: `--enable-video-processing`, `--brightness-adjustment 25`, `--manual-lifecycle`
  (options like `--resolution` apply when building the URL via `device`)

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

## License

MIT License - see `LICENSE`.

## Disclaimer

This project is independent and not affiliated with Axis Communications AB. For official resources, visit the [Axis developer documentation](https://developer.axis.com/).
