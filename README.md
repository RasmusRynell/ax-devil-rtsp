# ax-devil-rtsp

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Type Hints](https://img.shields.io/badge/Type%20Hints-Strict-brightgreen.svg)](https://www.python.org/dev/peps/pep-0484/)

A Python library for RTSP streaming from Axis cameras with video and metadata support.

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
      <th align="center">CLI Usage</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>🔄 Combined Streaming</b></td>
      <td>Simultaneous video and metadata streaming (default)</td>
      <td align="center"><code>RtspDataRetriever</code></td>
      <td align="center">Default behavior</td>
    </tr>
    <tr>
      <td><b>📹 Video Only</b></td>
      <td>Stream video frames without metadata</td>
      <td align="center"><code>RtspVideoDataRetriever</code></td>
      <td align="center"><code>--no-metadata</code></td>
    </tr>
    <tr>
      <td><b>📊 Metadata Only</b></td>
      <td>Stream scene metadata without video</td>
      <td align="center"><code>RtspApplicationDataRetriever</code></td>
      <td align="center"><code>--no-video</code></td>
    </tr>
    <tr>
      <td><b>⚡ Real-time Processing</b></td>
      <td>Frame-by-frame processing with custom callbacks</td>
      <td align="center"><code>on_video_data</code></td>
      <td align="center">N/A</td>
    </tr>
    <tr>
      <td><b>🎯 RTP Extension Data</b></td>
      <td>Access to ONVIF RTP extension data and timing information (enabled by default)</td>
      <td align="center"><code>rtp_ext=True</code></td>
      <td align="center">Default enabled</td>
    </tr>
    <tr>
      <td><b>🛠️ Axis URL Builder</b></td>
      <td>Utility for constructing Axis-compatible RTSP URLs</td>
      <td align="center"><code>build_axis_rtsp_url</code></td>
      <td align="center">N/A</td>
    </tr>
  </tbody>
</table>

---

## 📦 Installation

```bash
pip install ax-devil-rtsp
```

---

## 🚀 Quick Start

### Python API

```python
from ax_devil_rtsp import RtspDataRetriever, build_axis_rtsp_url

# Define callback functions
def on_video_data(payload):
    frame = payload["data"]
    diagnostics = payload["diagnostics"]
    print(f"Video frame: {frame.shape}, {diagnostics}")

def on_metadata(payload):
    xml_data = payload["data"]
    diagnostics = payload["diagnostics"]
    print(f"Metadata: {len(xml_data)} bytes, {diagnostics}")

def on_error(payload):
    print(f"Error: {payload['message']}")

# Option 1: Direct RTSP URL
rtsp_url = "rtsp://username:password@192.168.1.90/axis-media/media.amp?analytics=1"
retriever = RtspDataRetriever(
    rtsp_url=rtsp_url,
    on_video_data=on_video_data,
    on_application_data=on_metadata,
    on_error=on_error,
    latency=100
)

# Use context manager for automatic cleanup
with retriever:
    print("Streaming... Press Ctrl+C to stop")
    # Keep running until interrupted

# Option 2: Build Axis-style URL
axis_url = build_axis_rtsp_url(
    ip="192.168.1.90",
    username="username", 
    password="password",
    video_source=1,
    get_video_data=True,
    get_application_data=True,
    rtp_ext=True,  # Enable RTP extension (default: True)
    resolution="640x480"
)

# Video-only retriever
from ax_devil_rtsp import RtspVideoDataRetriever
video_retriever = RtspVideoDataRetriever(axis_url, on_video_data=on_video_data)
```

### CLI Usage

**Basic Usage (streams both video and metadata):**
```bash
ax-devil-rtsp --ip 192.168.1.90 --username admin --password secret
```

**Common Options:**
```bash
# Custom resolution and quality
ax-devil-rtsp --ip 192.168.1.90 --username admin --password secret \
  --resolution 1280x720 --latency 50

# Different camera source
ax-devil-rtsp --ip 192.168.1.90 --username admin --password secret --source 2

# Use a complete RTSP URL
ax-devil-rtsp --rtsp-url "rtsp://admin:secret@192.168.1.90/axis-media/media.amp?analytics=1"
```

**Specialized Modes:**
```bash
# Video only (no metadata overlay)
ax-devil-rtsp --ip 192.168.1.90 --username admin --password secret --no-metadata

# Metadata only (no video window)  
ax-devil-rtsp --ip 192.168.1.90 --username admin --password secret --no-video
```

### Environment Variables (Optional)

```bash
export AX_DEVIL_TARGET_ADDR=192.168.1.90
export AX_DEVIL_TARGET_USER=admin
export AX_DEVIL_TARGET_PASS=secret
```

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

## 🛠️ Development Setup

### System Requirements

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update && sudo apt-get install -y \
  libgirepository-2.0-dev gobject-introspection libcairo2-dev libffi-dev pkg-config gcc libglib2.0-dev \
  gstreamer1.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-tools \
  gstreamer1.0-rtsp libgstrtspserver-1.0-0 \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gir1.2-gst-rtsp-server-1.0
```

### Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Helper Scripts

- `tools/install_dependencies.sh`: Automated system and Python dependency installation (Ubuntu/Debian)
- `tools/check_dependencies.py`: Verify all dependencies are properly installed

---

## 📄 License

MIT License - See LICENSE file for details.

---

## ⚠️ Disclaimer

This project is independent and not affiliated with Axis Communications AB. For official resources, visit [Axis developer documentation](https://developer.axis.com/).
