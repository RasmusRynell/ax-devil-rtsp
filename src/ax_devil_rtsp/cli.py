"""The `ax-devil-rtsp` command: stream from a camera or check the installation."""

from __future__ import annotations

import logging
import platform
import time
from collections import deque
from statistics import median
from typing import Any

import click

from . import __version__
from .rtsp import StreamError
from .session import SceneMetadata, StreamConfig, StreamSession, VideoOutput, VideoSample
from .url import build_axis_rtsp_url

_DISPLAY_FORMATS = ("bgr24", "bgra", "gray")


class _Stats:
    """Per-second counters for the status line. Written by the receive thread, read by the main thread."""

    def __init__(self, print_xml: bool) -> None:
        self.print_xml = print_xml
        self.frames = 0
        self.frames_with_capture_time = 0
        self.documents = 0
        self.sync_ms: list[float] = []
        self.capture_times: deque[int] = deque(maxlen=90)
        self.latest_image: Any = None

    def on_video(self, sample: VideoSample[Any]) -> None:
        self.frames += 1
        self.latest_image = sample.data
        if sample.capture_time_ns is not None:
            self.frames_with_capture_time += 1
            self.capture_times.append(sample.capture_time_ns)

    def on_metadata(self, document: SceneMetadata) -> None:
        self.documents += 1
        if self.print_xml:
            click.echo(document.xml)
        utc_time_ns = document.utc_time_ns
        capture_times = list(self.capture_times)
        if utc_time_ns is not None and capture_times:
            self.sync_ms.append(min(abs(utc_time_ns - t) for t in capture_times) / 1e6)

    def report(self, seconds: float) -> str:
        parts = []
        if self.frames:
            coverage = 100 * self.frames_with_capture_time / self.frames
            parts.append(f"video {self.frames / seconds:5.1f} fps, capture time {coverage:3.0f}%")
        if self.documents:
            parts.append(f"metadata {self.documents / seconds:5.1f} docs/s")
        if self.sync_ms:
            parts.append(f"metadata to nearest frame {median(self.sync_ms):.1f} ms")
        self.frames = self.frames_with_capture_time = self.documents = 0
        self.sync_ms = []
        return " | ".join(parts) or "no data"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__)
def cli() -> None:
    """Receive RTSP video and Axis scene metadata from Axis cameras."""


@cli.command()
@click.option("--url", help="Complete RTSP URL, used as given instead of the device options.")
@click.option("-a", "--device-ip", envvar="AX_DEVIL_TARGET_ADDR", show_envvar=True, help="Camera address.")
@click.option("-u", "--device-username", envvar="AX_DEVIL_TARGET_USER", show_envvar=True, default="")
@click.option("-p", "--device-password", envvar="AX_DEVIL_TARGET_PASS", show_envvar=True, default="")
@click.option("--camera", default="1", show_default=True, help="Video source on the camera.")
@click.option("--resolution", help="Video resolution such as 1280x720; the camera default when omitted.")
@click.option(
    "--capture-time/--no-capture-time",
    default=True,
    show_default=True,
    help="Ask the camera for per-frame capture times (onvifreplayext=1).",
)
@click.option(
    "--video",
    type=click.Choice([output.value for output in VideoOutput] + ["none"]),
    default="bgr24",
    show_default=True,
    help="What each video frame is delivered as.",
)
@click.option("--metadata/--no-metadata", default=True, show_default=True, help="Receive scene metadata.")
@click.option("--hwaccel", help="Hardware decoding device type, see `ax-devil-rtsp doctor`.")
@click.option("--timeout", default=15.0, show_default=True, help="Seconds to become ready and without data.")
@click.option("--display", is_flag=True, help="Show the video in a window; needs opencv-python.")
@click.option("--print-xml", is_flag=True, help="Print every scene metadata document.")
@click.option("--duration", type=float, help="Stop after this many seconds.")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
def stream(
    url: str | None,
    device_ip: str | None,
    device_username: str,
    device_password: str,
    camera: str,
    resolution: str | None,
    capture_time: bool,
    video: str,
    metadata: bool,
    hwaccel: str | None,
    timeout: float,
    display: bool,
    print_xml: bool,
    duration: float | None,
    log_level: str,
) -> None:
    """Stream video and scene metadata and print rates and metadata-to-video sync once per second."""
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if display and video not in _DISPLAY_FORMATS:
        raise click.UsageError(f"--display needs --video {', '.join(_DISPLAY_FORMATS)}")
    try:
        config = StreamConfig(
            video=None if video == "none" else VideoOutput(video),
            metadata=metadata,
            hwaccel=hwaccel,
            timeout=timeout,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    if url is None:
        if not device_ip:
            raise click.UsageError("give --url or --device-ip (or set AX_DEVIL_TARGET_ADDR)")
        url = build_axis_rtsp_url(
            device_ip,
            config,
            username=device_username,
            password=device_password,
            camera=camera,
            resolution=resolution,
            capture_time=capture_time,
        )
    cv2 = _import_cv2() if display else None

    stats = _Stats(print_xml)
    session = StreamSession(
        url,
        config,
        on_video=stats.on_video if config.video else None,
        on_metadata=stats.on_metadata if metadata else None,
    )
    click.echo(f"Connecting to {session.name}")
    try:
        session.start()
    except StreamError as exc:
        raise click.ClickException(str(exc)) from None
    started = last_report = time.monotonic()
    try:
        while session.is_running and (duration is None or time.monotonic() - started < duration):
            if cv2 is not None and stats.latest_image is not None:
                cv2.imshow("ax-devil-rtsp", stats.latest_image)
                if cv2.waitKey(10) & 0xFF == ord("q"):
                    break
            else:
                time.sleep(0.05)
            now = time.monotonic()
            if now - last_report >= 1:
                click.echo(stats.report(now - last_report))
                last_report = now
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
        session.join()
        if cv2 is not None:
            cv2.destroyAllWindows()
    if session.failure is not None:
        raise click.ClickException(str(session.failure))


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError:
        raise click.UsageError("--display needs OpenCV: pip install 'ax-devil-rtsp[display]'") from None
    return cv2


@cli.command()
def doctor() -> None:
    """Check video decoders and initialize hardware decoding devices without connecting to a camera."""
    import av
    from av.codec.hwaccel import HWAccel, hwdevices_available

    click.echo(f"ax-devil-rtsp {__version__}, Python {platform.python_version()}, {platform.platform()}")
    click.echo(f"PyAV {av.__version__}, FFmpeg {av.ffmpeg_version_info}")
    missing = []
    for codec in ("h264", "hevc"):
        try:
            av.Codec(codec, "r")
        except av.codec.codec.UnknownCodecError:
            missing.append(codec)
        click.echo(f"{'MISSING' if codec in missing else 'OK':8} {codec} decoder")
    devices = hwdevices_available()
    click.echo(f"Compiled hardware backends: {', '.join(devices) or 'none'}")
    for codec in ("h264", "hevc"):
        if codec in missing:
            continue
        for device in devices:
            try:
                decoder = av.CodecContext.create(codec, "r", hwaccel=HWAccel(device, allow_software_fallback=False))
            except (av.error.FFmpegError, RuntimeError, ValueError, NotImplementedError) as exc:
                click.echo(f"UNAVAILABLE {codec:4} --hwaccel {device}: {exc}")
                continue
            if decoder.is_hwaccel:
                click.echo(f"READY       {codec:4} --hwaccel {device}: default device initialized")
            else:
                click.echo(f"UNSUPPORTED {codec:4} --hwaccel {device}: no hardware configuration for this decoder")
    if devices:
        click.echo(
            "READY checks device initialization only; stream profile, resolution and actual decoding still matter."
        )
    if missing:
        raise click.ClickException("reinstall PyAV: pip install --force-reinstall av")


if __name__ == "__main__":
    cli()
