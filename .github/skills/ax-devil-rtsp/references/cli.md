# ax-devil-rtsp CLI Reference

Entry point: `ax-devil-rtsp`.

**Install** (if `which ax-devil-rtsp` returns nothing):
```bash
uv tool install ax-devil-rtsp
```

**Check system dependencies**:
```bash
ax-devil-rtsp doctor
```

## Environment Variables

The CLI reads these when the corresponding flag is not supplied:

| Variable | CLI flag fallback |
|----------|-------------------|
| `AX_DEVIL_TARGET_ADDR` | `--device-ip` / `-a` |
| `AX_DEVIL_TARGET_USER` | `--device-username` / `-u` |
| `AX_DEVIL_TARGET_PASS` | `--device-password` / `-p` |

## Usage

The main command opens a video window and/or prints application data. The `doctor` subcommand checks system dependencies.

### Connect via device credentials

```bash
ax-devil-rtsp \
  --device-ip <ip> --device-username <user> --device-password <pass>
```

### Connect via existing RTSP URL

```bash
ax-devil-rtsp --url "rtsp://<user>:<pass>@<ip>/axis-media/media.amp?analytics=polygon"
```

When using `--url`, device-specific options like `--resolution` and `--source` are ignored.

## Options

### Connection options

| Flag | Short | Env var | Description |
|------|-------|---------|-------------|
| `--device-ip` | `-a` | `AX_DEVIL_TARGET_ADDR` | Device IP or hostname |
| `--device-username` | `-u` | `AX_DEVIL_TARGET_USER` | Device username (default: empty) |
| `--device-password` | `-p` | `AX_DEVIL_TARGET_PASS` | Device password (default: empty) |
| `--url` | — | — | Full RTSP URL (skips URL construction) |

### Stream options (only with `--device-ip`, not `--url`)

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `1` | Camera head / video source index |
| `--resolution` | device default | e.g. `1280x720`, `640x480` |
| `--rtp-ext / --no-rtp-ext` | enabled | RTP extension data (NTP timestamps) |

### Mode options

| Flag | Description |
|------|-------------|
| `--only-video` | Disable application data, video only |
| `--only-application-data` | Disable video, metadata only (no display window) |

### Tuning options

| Flag | Default | Description |
|------|---------|-------------|
| `--latency` | `100` | GStreamer pipeline latency in ms (Python API default is `200`) |
| `--connection-timeout` | `30` | Connection timeout in seconds |
| `--enable-video-processing` | off | Enable timestamp overlay + brightness |
| `--brightness-adjustment` | `0` | Brightness value (-100 to 100) |
| `--manual-lifecycle` | off | Use `start()`/`stop()` instead of context manager |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `--log-file` | auto | Path to rotating log file |
| `--logs-dir` | auto | Directory for log files |

### Subcommands

#### `doctor` — Check system dependencies

```bash
ax-devil-rtsp doctor
```

Verifies GStreamer, GI bindings, and other host dependencies. Run this first if streaming fails.

## Typical CLI Workflows

### Stream video + metadata from a camera

```bash
ax-devil-rtsp --device-ip <ip> -u <user> -p <pass>
```

Press `q` in the video window or Ctrl-C to stop.

### Stream only application data (no video window)

```bash
ax-devil-rtsp --device-ip <ip> -u <user> -p <pass> --only-application-data
```

Prints ONVIF XML metadata to stdout.

### Stream with specific resolution

```bash
ax-devil-rtsp --device-ip <ip> -u <user> -p <pass> --resolution 1280x720
```

### Diagnose GStreamer issues

```bash
ax-devil-rtsp doctor
```
