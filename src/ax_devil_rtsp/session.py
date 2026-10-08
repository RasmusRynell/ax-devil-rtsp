"""Stream sessions: receive video and Axis scene metadata from one RTSP endpoint."""

from __future__ import annotations

import calendar
import logging
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, cast
from urllib.parse import urlsplit

import av
from av.codec.hwaccel import HWAccel

from .rtp import AccessUnitAssembler, MetadataAssembler, sdp_parameter_sets
from .rtsp import RtspConnection, StreamError

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

_CODECS = {"H264": "h264", "H265": "hevc"}
_MAX_PENDING_CAPTURE_TIMES = 64
_UTC_TIME = re.compile(r'UtcTime="(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z?"')

VideoData = TypeVar("VideoData", bound="bytes | av.VideoFrame | NDArray[np.uint8]")


class VideoOutput(Enum):
    """What a session delivers as `VideoSample.data`, fixed for the whole session."""

    ENCODED = "encoded"
    """Annex-B H.264/H.265 access unit `bytes`; no decoding."""
    DECODED = "decoded"
    """Decoded `av.VideoFrame` in the decoder's native pixel format."""
    RGB24 = "rgb24"
    """`uint8` NumPy array, shape (height, width, 3)."""
    BGR24 = "bgr24"
    """`uint8` NumPy array, shape (height, width, 3)."""
    RGBA = "rgba"
    """`uint8` NumPy array, shape (height, width, 4); alpha is 255."""
    BGRA = "bgra"
    """`uint8` NumPy array, shape (height, width, 4); alpha is 255."""
    GRAY = "gray"
    """`uint8` NumPy array, shape (height, width)."""


@dataclass(frozen=True)
class StreamConfig:
    """The fixed configuration of a stream session.

    Attributes:
        video: What to deliver per video frame, or None for no video.
        metadata: Whether to receive the Axis scene metadata stream.
        hwaccel: FFmpeg hardware device type for decoding, such as "vaapi" or "cuda"; see `ax-devil-rtsp doctor`.
        timeout: Seconds allowed to become ready, and without any data from the camera before the session fails.
    """

    video: VideoOutput | None = VideoOutput.RGB24
    metadata: bool = False
    hwaccel: str | None = None
    timeout: float = 15.0

    def __post_init__(self) -> None:
        if self.video is None and not self.metadata:
            raise ValueError("request video, metadata or both")


@dataclass(frozen=True, slots=True)
class VideoSample(Generic[VideoData]):
    """One video frame or access unit.

    Annotate callbacks with the data type the session's `VideoOutput` gives, for example
    `VideoSample[bytes]`, `VideoSample[av.VideoFrame]` or `VideoSample[NDArray[np.uint8]]`.

    Attributes:
        data: Annex-B `bytes`, an `av.VideoFrame` or a NumPy array; see `VideoOutput`. The receiver owns it.
        rtp_timestamp: The RTP timestamp (90 kHz clock) of the frame.
        capture_time_ns: Axis capture time in Unix nanoseconds, or None when the camera did not send one.
        keyframe: Whether the frame can be decoded without earlier frames.
    """

    data: VideoData
    rtp_timestamp: int
    capture_time_ns: int | None
    keyframe: bool


@dataclass(frozen=True, slots=True)
class SceneMetadata:
    """One complete Axis scene metadata XML document.

    Attributes:
        xml: The document text.
        rtp_timestamp: The RTP timestamp of the document.
        capture_time_ns: Axis capture time in Unix nanoseconds, or None when the camera did not send one.
    """

    xml: str
    rtp_timestamp: int
    capture_time_ns: int | None

    @property
    def utc_time_ns(self) -> int | None:
        """The first `UtcTime` in the document as Unix nanoseconds, to match against video capture times."""
        match = _UTC_TIME.search(self.xml)
        if match is None:
            return None
        seconds = calendar.timegm(time.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S"))
        return seconds * 1_000_000_000 + int((match.group(2) or "").ljust(9, "0"))


class StartCancelledError(Exception):
    """`stop()` was called before the session became ready."""


class _CallbackError(Exception):
    def __init__(self, cause: Exception) -> None:
        super().__init__(cause)
        self.cause = cause


class StreamSession:
    """A one-shot RTSP session that delivers video and scene metadata through callbacks.

    All callbacks run on the session's own receive thread, one at a time, in stream order. A slow callback slows only
    this session: the camera's TCP stream is pushed back instead of data piling up in memory.

    If a callback raises, the session stops and reports that exception through `failure` and `on_failure`. If the
    connection, the camera or decoding fails, it reports a `StreamError` instead.

    Args:
        url: Complete RTSP URL, used as given. Credentials in it are used for authentication and never logged.
            `name`, which logs and errors use, also leaves out the query, since it can carry access tokens.
        config: What to receive and how.
        on_video: Called with each `VideoSample`; required exactly when `config.video` is set.
        on_metadata: Called with each `SceneMetadata`; required exactly when `config.metadata` is set.
        on_failure: Called once on the receive thread if the session fails after it became ready.
    """

    def __init__(
        self,
        url: str,
        config: StreamConfig,
        *,
        on_video: Callable[[VideoSample[Any]], None] | None = None,
        on_metadata: Callable[[SceneMetadata], None] | None = None,
        on_failure: Callable[[BaseException], None] | None = None,
    ) -> None:
        if (config.video is None) != (on_video is None):
            raise ValueError("pass on_video exactly when config.video is set")
        if config.metadata != (on_metadata is not None):
            raise ValueError("pass on_metadata exactly when config.metadata is set")
        self.config = config
        self.video_codec: str | None = None
        self.failure: BaseException | None = None
        self._connection = RtspConnection(url, config.timeout)
        self.name = urlsplit(self._connection.url)._replace(query="", fragment="").geturl()
        self._on_video = on_video
        self._on_metadata = on_metadata
        self._on_failure = on_failure
        self._array_format = None if config.video in (None, VideoOutput.ENCODED, VideoOutput.DECODED) else config.video
        self._decoder: av.VideoCodecContext | None = None
        self._capture_times: dict[int, int | None] = {}
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._playing = False
        self._thread = threading.Thread(target=self._run, name=f"rtsp {self.name}", daemon=True)

    def __repr__(self) -> str:
        return f"StreamSession({self.name!r})"

    def __enter__(self) -> StreamSession:
        self.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.stop()
        self.join()

    @property
    def is_running(self) -> bool:
        """Whether the receive thread is still running."""
        return self._thread.is_alive()

    def start(self) -> None:
        """Connect and start streaming; returns once the camera accepted PLAY for every requested stream.

        Raises:
            StreamError: The session could not become ready within `config.timeout`.
            StartCancelledError: `stop()` was called first.
            RuntimeError: The session was already started; sessions are one-shot.
        """
        if self._stopping.is_set():
            raise StartCancelledError(f"{self.name} was stopped before it started")
        self._thread.start()
        if not self._ready.wait(self.config.timeout):
            self.stop()
            self.failure = StreamError(f"not ready within {self.config.timeout:g} s")
            raise self.failure
        if self._playing:
            return
        if self.failure is not None:
            raise self.failure
        raise StartCancelledError(f"{self.name} was stopped while starting")

    def stop(self) -> None:
        """Ask the session to stop. Never blocks, may be called from callbacks and more than once."""
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._ready.set()
        self._connection.shutdown()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the receive thread to end. Must not be called from a callback."""
        if self._thread.ident is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            handlers = self._open()
            if not self._stopping.is_set():
                self._playing = True
                self._ready.set()
                video = f"{self.video_codec} video" if self.video_codec else "no video"
                logger.info("%s: streaming %s, metadata %s", self.name, video, "on" if self.config.metadata else "off")
                self._receive(handlers)
        except _CallbackError as exc:
            self._fail(exc.cause)
        except StreamError as exc:
            self._fail(exc)
        except Exception as exc:
            self._fail(StreamError(f"{type(exc).__name__}: {exc}"))
        finally:
            self._connection.close()
            self._ready.set()
        if self._playing and self.failure is not None and self._on_failure is not None:
            try:
                self._on_failure(self.failure)
            except Exception:
                logger.exception("%s: on_failure raised", self.name)

    def _fail(self, failure: BaseException) -> None:
        if self._stopping.is_set():
            return
        self.failure = failure
        self._stopping.set()
        if self._playing:  # before that, start() raises it to the caller
            logger.error("%s: %s", self.name, failure)

    def _open(self) -> dict[int, Callable[[bytes], None]]:
        connection = self._connection
        connection.connect()
        if self._stopping.is_set():
            return {}
        aggregate_url, medias = connection.describe()
        handlers: dict[int, Callable[[bytes], None]] = {}
        if self.config.video is not None:
            video = next((media for media in medias if media.kind == "video" and media.encoding in _CODECS), None)
            if video is None:
                raise StreamError("the stream has no H.264 or H.265 video")
            codec = _CODECS[video.encoding]
            if self.config.video is not VideoOutput.ENCODED:
                hwaccel = HWAccel(self.config.hwaccel) if self.config.hwaccel else None
                decoder = cast(av.VideoCodecContext, av.CodecContext.create(codec, "r", hwaccel=hwaccel))
                decoder.thread_type = "SLICE"  # frame threading adds a frame of latency per thread
                self._decoder = decoder
            assembler = AccessUnitAssembler(codec, sdp_parameter_sets(codec, video.fmtp), self._on_access_unit)
            handlers[connection.setup(video.control, 0)] = assembler.push
            self.video_codec = codec
        if self.config.metadata:
            metadata = next((media for media in medias if media.kind == "application"), None)
            if metadata is None:
                raise StreamError("the stream has no scene metadata; Axis URLs need analytics=polygon")
            handlers[connection.setup(metadata.control, 2)] = MetadataAssembler(self._on_document).push
        connection.play(aggregate_url)
        return handlers

    def _receive(self, handlers: dict[int, Callable[[bytes], None]]) -> None:
        connection = self._connection
        finished = threading.Event()
        keepalive = threading.Thread(
            target=self._keepalive, args=(finished,), name=f"keepalive {self.name}", daemon=True
        )
        keepalive.start()
        try:
            while not self._stopping.is_set():
                channel, packet = connection.read_packet()
                handler = handlers.get(channel)
                if handler is not None:
                    handler(packet)
        finally:
            finished.set()
            connection.shutdown()
            keepalive.join()

    def _keepalive(self, finished: threading.Event) -> None:
        interval = max(self._connection.session_timeout / 2, 0.5)
        while not finished.wait(interval) and not self._stopping.is_set():
            try:
                self._connection.keepalive()
            except OSError:
                self._fail(StreamError("could not send RTSP keepalive"))
                self._connection.shutdown()
                return

    def _on_access_unit(self, data: bytes, rtp_timestamp: int, capture_time_ns: int | None, keyframe: bool) -> None:
        if self._decoder is None:
            self._deliver_video(VideoSample(data, rtp_timestamp, capture_time_ns, keyframe))
            return
        self._capture_times[rtp_timestamp] = capture_time_ns
        if len(self._capture_times) > _MAX_PENDING_CAPTURE_TIMES:
            del self._capture_times[next(iter(self._capture_times))]
        packet = av.Packet(data)
        packet.pts = rtp_timestamp
        try:
            frames = self._decoder.decode(packet)
        except av.error.InvalidDataError as exc:
            logger.warning("%s: skipped undecodable video: %s", self.name, exc)
            return
        for frame in frames:
            pts = rtp_timestamp if frame.pts is None else frame.pts
            output: Any = frame
            if self._array_format is not None:
                output = frame.to_ndarray(format=self._array_format.value, threads=1)
            self._deliver_video(VideoSample(output, pts, self._capture_times.pop(pts, None), frame.key_frame))

    def _deliver_video(self, sample: VideoSample[Any]) -> None:
        assert self._on_video is not None
        try:
            self._on_video(sample)
        except Exception as exc:
            raise _CallbackError(exc) from exc

    def _on_document(self, xml: str, rtp_timestamp: int, capture_time_ns: int | None) -> None:
        assert self._on_metadata is not None
        try:
            self._on_metadata(SceneMetadata(xml, rtp_timestamp, capture_time_ns))
        except Exception as exc:
            raise _CallbackError(exc) from exc
