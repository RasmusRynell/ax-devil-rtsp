# ax-devil-rtsp

<div align="center">

[![Python 3.8+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Type Hints](https://img.shields.io/badge/Type%20Hints-Strict-brightgreen.svg)](https://www.python.org/dev/peps/pep-0484/)

A Python library for handling RTSP streams from Axis cameras. Provides robust video streaming and metadata handling capabilities with both GStreamer and raw socket implementations.

See also: [ax-devil-device-api](https://github.com/rasmusrynell/ax-devil-device-api) and [ax-devil-mqtt](https://github.com/rasmusrynell/ax-devil-mqtt) for other Axis device management tools.

</div>

---

## 📋 Contents

- [Feature Overview](#-feature-overview)
- [Quick Start](#-quick-start)
- [Usage Examples](#-usage-examples)
- [Disclaimer](#-disclaimer)
- [License](#-license)

---

## 🔍 Feature Overview

<table>
  <thead>
    <tr>
      <th>Feature</th>
      <th>Description</th>
      <th align="center">Python API</th>
      <th align="center">CLI Tool</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>📹 Video Streaming</b></td>
      <td>High-performance RTSP video streaming with GStreamer</td>
      <td align="center"><code>VideoGStreamerClient</code></td>
      <td align="center"><a href="#video-cli">ax-devil-rtsp video</a></td>
    </tr>
    <tr>
      <td><b>📊 Scene Metadata (GStreamer)</b></td>
      <td>GStreamer-based metadata streaming with RTP packet handling</td>
      <td align="center"><code>SceneMetadataClient</code></td>
      <td align="center"><a href="#metadata-gst-cli">ax-devil-rtsp metadata-gst</a></td>
    </tr>
    <tr>
      <td><b>🔄 Scene Metadata (Raw)</b></td>
      <td>Raw socket implementation for metadata streaming</td>
      <td align="center"><code>SceneMetadataRawClient</code></td>
      <td align="center"><a href="#metadata-raw-cli">ax-devil-rtsp metadata-raw</a></td>
    </tr>
    <tr>
      <td><b>⚡ Real-time Processing</b></td>
      <td>Frame-by-frame processing with custom callbacks</td>
      <td align="center"><code>frame_handler_callback</code></td>
      <td align="center">N/A</td>
    </tr>
    <tr>
      <td><b>🎯 RTP Extension Data</b></td>
      <td>Access to ONVIF RTP extension data and timing information</td>
      <td align="center"><code>latest_rtp_data</code></td>
      <td align="center">N/A</td>
    </tr>
  </tbody>
</table>

---

## 🚀 Quick Start

### Installation

```bash
pip install ax-devil-rtsp
```

### Environment Variables
For an easier experience, you can set the following environment variables:
```bash
export AX_DEVIL_TARGET_ADDR=<device-ip>
export AX_DEVIL_TARGET_USER=<username>
export AX_DEVIL_TARGET_PASS=<password>
export AX_DEVIL_USAGE_CLI="safe" # Set to "unsafe" to skip SSL certificate verification for CLI calls
```

---

## 💻 Usage Examples

### Python API Usage

```python
import json
from ax_devil_rtsp import VideoGStreamerClient, SceneMetadataClient

# Video Streaming Example
def frame_callback(frame, rtp_info):
    if rtp_info:
        print(f"Frame timestamp: {rtp_info['human_time']}")
    # Process frame using OpenCV/NumPy as needed

# Initialize video client with context manager
rtsp_url = "rtsp://username:password@192.168.1.90/axis-media/media.amp"
client = VideoGStreamerClient(rtsp_url, latency=100, frame_handler_callback=frame_callback)
client.start()  # Starts streaming in current thread

# Metadata Streaming Example
def metadata_callback(xml_text):
    print(f"Received metadata: {xml_text[:100]}...")  # Print first 100 chars

# Initialize metadata client
metadata_url = "rtsp://username:password@192.168.1.90/axis-media/media.amp?analytics=1"
metadata_client = SceneMetadataClient(metadata_url, 
                                    latency=100,
                                    raw_data_callback=metadata_callback)
metadata_client.start()  # Starts streaming in current thread
```

### CLI Usage Examples

<details open>
<summary><a name="video-cli"></a><b>📹 Video Streaming</b></summary>
<p>

```bash
# Display video stream in window
ax-devil-rtsp video --ip 192.168.1.90 --username admin --password secret
```
</p>
</details>

<details>
<summary><a name="metadata-gst-cli"></a><b>📊 Scene Metadata (GStreamer)</b></summary>
<p>

```bash
ax-devil-rtsp metadata --ip 192.168.1.90 --username admin --password secret
```
</p>
</details>

---

## 🧪 Running Tests

#### Unit Tests
```bash
# Run all unit tests - no network dependencies
pytest tests/unit/ -v

# Run specific unit test file
pytest tests/unit/test_cli.py -v
```

#### Integration Tests  
```bash
# Local development mode (uses GStreamer test servers)
pytest tests/integration/ -v

# Real camera mode (uses actual hardware)
USE_REAL_CAMERA=true \
AX_DEVIL_TARGET_ADDR=192.168.1.81 \
AX_DEVIL_TARGET_USER=root \
AX_DEVIL_TARGET_PASS=fusion \
pytest tests/integration/ -v

# Run specific integration test file
pytest tests/integration/test_video_gstreamer.py -v
```

#### All Tests
```bash
# Local mode (unit + integration with test servers)
pytest tests/ -v

# Real camera mode (unit + integration with real camera)
USE_REAL_CAMERA=true pytest tests/ -v

# GStreamer tests only
pytest -m "requires_gstreamer" -v
```

### Test Environment Variables

- **`USE_REAL_CAMERA`**: `true` to use real cameras, `false` for test servers
- **`AX_DEVIL_TARGET_ADDR`**: Real camera IP address
- **`AX_DEVIL_TARGET_USER`**: Camera username  
- **`AX_DEVIL_TARGET_PASS`**: Camera password

> **Note:** Integration tests fail naturally if they cannot connect to the provided RTSP URL, regardless of whether it's a test server or real camera.


> **Note:** For more CLI examples and detailed API documentation, check the [examples directory](src/ax_devil_rtsp/examples) in the source code.

---

## ⚠️ Disclaimer

This project is an independent, community-driven implementation and is **not** affiliated with or endorsed by Axis Communications AB. For official APIs and development resources, please refer to [Axis Developer Community](https://www.axis.com/en-us/developer).

## 📄 License

MIT License - See LICENSE file for details.
