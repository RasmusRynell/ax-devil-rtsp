---
name: ax-devil-rtsp
description: 'Use the ax-devil-rtsp package (CLI and Python API) to stream RTSP video and AXIS Scene Metadata from Axis cameras. Use when asked to "stream video", "RTSP stream", "get video frames", "scene metadata over RTSP", "sync metadata with video", "build RTSP URL", "video callback", write code using StreamSession, StreamConfig or build_axis_rtsp_url, or display a live camera feed.'
---

# ax-devil-rtsp

Python package for receiving RTSP video and AXIS Scene Metadata from Axis cameras. Its own RTSP/RTP client runs over
TCP; PyAV (FFmpeg) decodes. Video and metadata arrive through callbacks on one receive thread per session, with
per-frame capture times for matching the two.

**Package**: `ax-devil-rtsp` (PyPI)
**Depends on**: `av` (PyAV, bundles FFmpeg), `numpy`, `click`. No system packages. Optional `[display]` adds OpenCV.

## Prerequisites — MUST do before any command

1. **Ensure the CLI is installed.** Run `which ax-devil-rtsp`. If not found:
   ```bash
   uv tool install ax-devil-rtsp
   ```
   `ax-devil-rtsp doctor` checks PyAV, the H.264/H.265 decoders and hardware decoding devices.

2. **Resolve credentials.** Before running any command or writing code, you MUST have concrete values:
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

- **[CLI Reference](./references/cli.md)** — `stream` and `doctor` options and workflows
- **[Python API Reference](./references/python-api.md)** — `StreamSession`, `StreamConfig`, `VideoOutput`, callbacks, URL building

## Quick Decision Guide

| Task | Tool | Reference |
|------|------|-----------|
| Check rates and metadata-to-video sync | `ax-devil-rtsp stream` | [CLI](./references/cli.md) |
| View live video | `ax-devil-rtsp stream --display` | [CLI](./references/cli.md) |
| Print scene metadata XML | `ax-devil-rtsp stream --video none --print-xml` | [CLI](./references/cli.md) |
| Receive frames and/or metadata in Python | `StreamSession` + `StreamConfig` | [Python](./references/python-api.md) |
| Build an Axis RTSP URL | `build_axis_rtsp_url(host, config, ...)` | [Python](./references/python-api.md) |
| Check the installation | `ax-devil-rtsp doctor` | [CLI](./references/cli.md) |

## Key Concepts

- **One session, one config**: `StreamSession(url, StreamConfig(video=..., metadata=...), on_video=..., on_metadata=...)`.
  Pass `on_video` exactly when `video` is set and `on_metadata` exactly when `metadata` is true.
- **`VideoOutput`** fixes what `VideoSample.data` is: `ENCODED` (Annex-B bytes), `DECODED` (`av.VideoFrame`), or a
  NumPy array in `RGB24`, `BGR24`, `RGBA`, `BGRA` or `GRAY`.
- **Threads**: callbacks run on the session's receive thread. Keep them fast; hand data off yourself.
- **Lifecycle**: `start()` blocks until PLAY succeeded and raises `StreamError` on failure; `stop()` never blocks;
  `with session:` does both. Sessions are one-shot.
- **Sync**: `VideoSample.capture_time_ns` vs `SceneMetadata.utc_time_ns`, both Unix nanoseconds, agree within ~1 ms.
- **Metadata 400 Bad Request** means the camera's `AnalyticsSceneDescription` producer is disabled for that channel.
