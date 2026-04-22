---
name: ax-devil-rtsp
description: 'Use the ax-devil-rtsp package (CLI and Python API) to stream RTSP video and AXIS Scene Metadata from Axis cameras. Use when asked to "stream video", "RTSP stream", "get video frames", "application data", "scene metadata over RTSP", "build RTSP URL", "video callback", write code using RtspDataRetriever or build_axis_rtsp_url, or display a live camera feed.'
---

# ax-devil-rtsp

Python package for streaming RTSP video and AXIS Scene Metadata (application data) from Axis devices. Runs GStreamer in a subprocess and delivers frames/metadata via callbacks.

**Package**: `ax-devil-rtsp` (PyPI)
**Depends on**: `numpy`, `opencv-python`, `click`, `rich`, `urllib3`, `PyGObject`, GStreamer (system)

## Prerequisites — MUST do before any command

1. **Ensure system dependencies are installed.** GStreamer and GI bindings are required (Linux):
   ```bash
   sudo apt-get install -y \
     gcc cmake pkg-config python3-dev libcairo2-dev libffi-dev libglib2.0-dev \
     libgirepository-2.0-dev gobject-introspection \
     python3-gi python3-gst-1.0 \
     gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
     gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
     gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
   ```
   Run `ax-devil-rtsp doctor` to verify.

2. **Ensure the CLI is installed.** Run `which ax-devil-rtsp`. If not found:
   ```bash
   uv tool install ax-devil-rtsp
   ```

3. **Resolve credentials.** Before running any command or writing code, you MUST have concrete values:
   - Check env vars: `echo $AX_DEVIL_TARGET_ADDR $AX_DEVIL_TARGET_USER $AX_DEVIL_TARGET_PASS`
   - If any required value is missing or empty, **ASK the user** — do NOT guess or use placeholder IPs.
   - If the user provides a full `--url`, no device credentials are needed.

## Environment Variables

The CLI reads these when the corresponding flag is not supplied:

| Variable | CLI flag fallback |
|----------|-------------------|
| `AX_DEVIL_TARGET_ADDR` | `--device-ip` / `-a` |
| `AX_DEVIL_TARGET_USER` | `--device-username` / `-u` |
| `AX_DEVIL_TARGET_PASS` | `--device-password` / `-p` |

## References

Load only the reference you need:

- **[CLI Reference](./references/cli.md)** — CLI options, modes, and workflows
- **[Python API Reference](./references/python-api.md)** — `RtspDataRetriever`, `build_axis_rtsp_url`, callbacks, and Python workflows

## Quick Decision Guide

| Task | Tool | Reference |
|------|------|-----------|
| View live video + metadata (demo) | `ax-devil-rtsp` CLI | [CLI](./references/cli.md) |
| Stream only application data | `--only-application-data` or `RtspApplicationDataRetriever` | [CLI](./references/cli.md) / [Python](./references/python-api.md) |
| Stream only video | `--only-video` or `RtspVideoDataRetriever` | [CLI](./references/cli.md) / [Python](./references/python-api.md) |
| Stream both video + metadata in Python | `RtspDataRetriever` | [Python](./references/python-api.md) |
| Build an Axis RTSP URL from parameters | `build_axis_rtsp_url()` | [Python](./references/python-api.md) |
| Check GStreamer dependencies | `ax-devil-rtsp doctor` | [CLI](./references/cli.md) |

## Key Concepts

- **GStreamer subprocess**: All retrievers run GStreamer in a spawned subprocess. Data flows through a multiprocessing queue to your callbacks in the main process.
- **`spawn` start method**: The package forces `mp.set_start_method('spawn')`. Always use `if __name__ == "__main__":` guard. Call `freeze_support()` for Windows compatibility.
- **Context manager**: Use `with retriever:` for automatic cleanup. Alternatively call `start()`/`stop()` manually.
- **Callbacks**: `on_video_data(payload)` receives `{"data": np.ndarray, ...}`. `on_application_data(payload)` receives `{"data": bytes, "diagnostics": ...}`. `on_session_start(payload)` fires once per RTP pad.
- **Application data** = AXIS Scene Metadata (ONVIF XML) carried in the RTSP stream alongside video.
