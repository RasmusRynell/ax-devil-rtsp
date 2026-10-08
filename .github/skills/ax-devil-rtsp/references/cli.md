# CLI Reference

```bash
ax-devil-rtsp stream [OPTIONS]
ax-devil-rtsp doctor
```

## `stream`

Connects, streams, and prints one status line per second: video frame rate, share of frames with a capture time,
metadata documents per second and the median distance between each document's `UtcTime` and the nearest frame's
capture time. Ctrl+C (or `q` in the video window) stops. Exits with status 1 and the error if the stream fails.

| Option | Default | Meaning |
|--------|---------|---------|
| `--url TEXT` | | Complete RTSP URL, used as given; the device options are ignored |
| `-a, --device-ip TEXT` | `$AX_DEVIL_TARGET_ADDR` | Camera address |
| `-u, --device-username TEXT` | `$AX_DEVIL_TARGET_USER` | Camera user |
| `-p, --device-password TEXT` | `$AX_DEVIL_TARGET_PASS` | Camera password |
| `--camera TEXT` | `1` | Video source on the camera |
| `--resolution TEXT` | camera default | For example `1280x720` |
| `--capture-time / --no-capture-time` | on | Ask for per-frame capture times (`onvifreplayext=1`) |
| `--video [encoded\|decoded\|rgb24\|bgr24\|rgba\|bgra\|gray\|none]` | `bgr24` | What each frame is delivered as |
| `--metadata / --no-metadata` | on | Receive scene metadata |
| `--hwaccel TEXT` | | FFmpeg hardware device type, see `doctor` |
| `--timeout FLOAT` | `15` | Seconds to become ready, and without data before failing |
| `--display` | | Show video in a window; needs `ax-devil-rtsp[display]` and `--video bgr24`, `bgra` or `gray` |
| `--print-xml` | | Print every metadata document |
| `--duration FLOAT` | | Stop after this many seconds |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

Device options build an Axis URL; `--resolution`, `--camera` and `--capture-time` only apply then.

## `doctor`

Prints the package, Python, PyAV and FFmpeg versions, whether the `h264` and `hevc` decoders exist, and the hardware
decoding device types available to `--hwaccel`. Exits with status 1 if a decoder is missing.

## Workflows

```bash
# Video and metadata, with sync figures
ax-devil-rtsp stream -a 192.168.1.90 -u root -p secret

# Live window
ax-devil-rtsp stream --display

# Metadata only, print XML, stop after 10 s
ax-devil-rtsp stream --video none --print-xml --duration 10

# Existing URL, encoded video only (no decoding cost)
ax-devil-rtsp stream --url "rtsp://root:secret@192.168.1.90/axis-media/media.amp?videocodec=h265" \
  --video encoded --no-metadata
```

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| `DESCRIBE failed with 400 Bad Request` with metadata on | The camera's `AnalyticsSceneDescription` producer is disabled for that channel |
| `DESCRIBE was refused with 401` | Wrong or missing credentials |
| `the stream has no scene metadata` | A `--url` without `analytics=polygon`; add it or use `--no-metadata` |
| `capture time 0%` | The URL lacks `onvifreplayext=1`, or `--no-capture-time` was given |
