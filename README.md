# ax-devil-rtsp

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Type Hints](https://img.shields.io/badge/Type%20Hints-Strict-brightgreen.svg)](https://www.python.org/dev/peps/pep-0484/)

A Python library for RTSP streaming from Axis cameras with video and AXIS Scene metadata support.

*The words 'AXIS Scene Metadata' is hereby called 'application data' in this project.*

See also: [ax-devil-device-api](https://github.com/rasmusrynell/ax-devil-device-api) and [ax-devil-mqtt](https://github.com/rasmusrynell/ax-devil-mqtt) for other Axis device management tools.

</div>

---

## 📋 Contents

- [Feature Overview](#-feature-overview)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Testing](#-testing)
- [Development Setup](#-development-setup)
- [License](#-license)

---

## 🔍 Feature Overview

<table>
  <thead>
    <tr>
      <th>Feature</th>
      <th>Description</th>
      <th align="center">Python API</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>🔄 Combined Streaming</b></td>
      <td>Simultaneous video and application data streaming (default)</td>
      <td align="center"><code>RtspDataRetriever</code></td>
    </tr>
    <tr>
      <td><b>📹 Video Only</b></td>
      <td>Stream video frames without application data</td>
      <td align="center"><code>RtspVideoDataRetriever</code></td>
    </tr>
    <tr>
      <td><b>📊 Application Data (AXIS Scene Metadata) Only</b></td>
      <td>Stream scene application data without video</td>
      <td align="center"><code>RtspApplicationDataRetriever</code></td>
    </tr>
    <tr>
      <td><b>⚡ Real-time Processing</b></td>
      <td>Frame-by-frame processing with custom callbacks</td>
      <td align="center"><code>on_video_data</code></td>
    </tr>
    <tr>
      <td><b>🎯 RTP Extension Data</b></td>
      <td>Access to ONVIF RTP extension data and timing information (enabled by default)</td>
      <td align="center"><code>rtp_ext=True</code></td>
    </tr>
    <tr>
      <td><b>🛠️ Axis URL Builder</b></td>
      <td>Utility for constructing Axis-compatible RTSP URLs</td>
      <td align="center"><code>build_axis_rtsp_url</code></td>
    </tr>
  </tbody>
</table>

---

## 📦 Installation

```bash
pip install ax-devil-rtsp
```

### System Dependencies

On Linux, this library requires system packages for PyGObject and GStreamer. If they're missing, you'll see clear error messages with installation instructions.

**Quick setup (Ubuntu/Debian):**
```bash
# Check what's missing
python tools/dep.py --check

# Get installation commands
python tools/dep.py --install
```

---

## 🚀 Quick Start

### Python API

```python
from ax_devil_rtsp import RtspDataRetriever, build_axis_rtsp_url
from multiprocessing import freeze_support
import time

# Define callback functions
def on_video_data(payload):
    frame = payload["data"]
    diagnostics = payload["diagnostics"]
    print(f"Video frame: {frame.shape}, {diagnostics}")

def on_application_data(payload):
    xml_data = payload["data"]
    diagnostics = payload["diagnostics"]
    print(f"Application data: {len(xml_data)} bytes, {diagnostics}")

def on_error(payload):
    print(f"Error: {payload['message']}")

def main():
    # Build the RTSP URL or supply one directly
    # rtsp_url = "rtsp://username:password@192.168.1.90/axis-media/media.amp?analytics=polygon"
    rtsp_url = build_axis_rtsp_url(
        ip="192.168.1.90",
        username="username",
        password="password",
        video_source=1,
        get_video_data=True,
        get_application_data=True,
        rtp_ext=True,  # Enable RTP extension data
        resolution="640x480",
    )

    retriever = RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_application_data=on_application_data,
        on_error=on_error,
        latency=100,
    )

    # Use context manager for automatic cleanup
    with retriever:
        print("Streaming... Press Ctrl+C to stop")
        while True:
            time.sleep(0.1)

if __name__ == "__main__":
    freeze_support()  # Needed on Windows when multiprocessing start method is 'spawn'
    main()
```
> **Note**
>
> Because `ax-devil-rtsp` forces the multiprocessing start method to `'spawn'`,
> your script's entry point must be guarded with
> `if __name__ == "__main__":` (as shown above). On Windows also call
> `multiprocessing.freeze_support()` before starting the retriever.

#### Video-only and application-data-only

```python
from ax_devil_rtsp import (
    RtspVideoDataRetriever,
    RtspApplicationDataRetriever,
    build_axis_rtsp_url,
)

# Video-only
video_url = build_axis_rtsp_url(
    ip="192.168.1.90",
    username="username",
    password="password",
    video_source=1,
    get_video_data=True,
    get_application_data=False,
    rtp_ext=True,
)
with RtspVideoDataRetriever(
    rtsp_url=video_url,
    on_video_data=lambda p: print(p["diagnostics"]),
):
    ...

# Application data only
app_url = build_axis_rtsp_url(
    ip="192.168.1.90",
    username="username",
    password="password",
    video_source=1,
    get_video_data=False,
    get_application_data=True,
    rtp_ext=True,
)
with RtspApplicationDataRetriever(
    rtsp_url=app_url,
    on_application_data=lambda p: print(len(p["data"]))
):
    ...

### CLI Usage

The CLI offers two subcommands:

- `device` builds the RTSP URL from device details like IP address and
  credentials.
- `url` is for when you already have a complete RTSP URL. Options that modify
  the URL (for example `--resolution` or `--rtp-ext`) are only valid with the
  `device` command.

**Basic Usage (streams both video and application data):**
```bash
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret
```

**Using a complete RTSP URL:**
```bash
ax-devil-rtsp url "rtsp://admin:secret@192.168.1.90/axis-media/media.amp?analytics=polygon"
```

**Common Options:**
```bash
# Custom resolution
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret \
  --resolution 1280x720

# Different camera source
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret --source 2
```

**Specialized Modes:**
```bash
# Video only (no application data overlay)
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret --only-video

# Application data only (no video window)
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret --only-application-data

# Disable RTP extension data
ax-devil-rtsp device --ip 192.168.1.90 --username admin --password secret --no-rtp-ext
```

For demo processing and lifecycle control, see: `--enable-video-processing`, `--brightness-adjustment`, and `--manual-lifecycle` (run `ax-devil-rtsp device --help`).

### Environment Variables (Optional)

```bash
export AX_DEVIL_TARGET_ADDR=192.168.1.90
export AX_DEVIL_TARGET_USER=admin
export AX_DEVIL_TARGET_PASS=secret
export AX_DEVIL_USAGE_CLI=safe  # Set to "unsafe" to skip SSL verification
```
Set these variables to avoid passing `--ip`, `--username`, or `--password` each
time you invoke the `device` command.
`AX_DEVIL_USAGE_CLI` is shared with related `ax-devil-*` tools and kept here for consistency.

---

## 🧪 Testing

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (local test servers)
pytest tests/integration/ -v

# Integration tests (real camera)
USE_REAL_CAMERA=true AX_DEVIL_TARGET_ADDR=192.168.1.90 pytest tests/integration/ -v
```

---

> Note on GI/GStreamer
>
> On Linux, `PyGObject` and GStreamer are system packages. Install them with your distro package manager before using this library (see Development Setup below). If they are missing, the library will show an error with install instructions.
 

### Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Helper Scripts

- `tools/dep.py`: Unified dependency management tool
  - Check dependencies: `python tools/dep.py --check`
  - Get install commands (Ubuntu/Debian): `python tools/dep.py --install`

---

## 📄 License

MIT License - See LICENSE file for details.

---

## ⚠️ Disclaimer

This project is independent and not affiliated with Axis Communications AB. For official resources, visit [Axis developer documentation](https://developer.axis.com/).
