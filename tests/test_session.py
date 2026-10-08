"""Stream sessions against a local fake camera."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from typing import Any

import av
import numpy as np
import pytest
from numpy.typing import NDArray

from ax_devil_rtsp import (
    SceneMetadata,
    StartCancelledError,
    StreamConfig,
    StreamError,
    StreamSession,
    VideoOutput,
    VideoSample,
)
from ax_devil_rtsp.rtsp import RtspConnection

from fake_camera import (
    BASE_UNIX_SECONDS,
    FRAME_RGB,
    FakeCamera,
    encode_video,
    metadata_packets,
    sdp,
    video_packets,
)

FRAMES = 5
DOCUMENTS = [f'<tt:MetadataStream><tt:Frame UtcTime="2027-01-15T08:30:0{i}Z"/></tt:MetadataStream>' for i in range(3)]
SECOND = 1_000_000_000


class Received:
    """Collects callback values and signals when the expected number arrived."""

    def __init__(self, frames: int = 0, documents: int = 0) -> None:
        self.video: list[VideoSample[Any]] = []
        self.metadata: list[SceneMetadata] = []
        self.failures: list[BaseException] = []
        self._expected = (frames, documents)
        self.done = threading.Event()

    def on_video(self, sample: VideoSample[Any]) -> None:
        self.video.append(sample)
        self._check()

    def on_metadata(self, document: SceneMetadata) -> None:
        self.metadata.append(document)
        self._check()

    def on_failure(self, failure: BaseException) -> None:
        self.failures.append(failure)
        self.done.set()

    def _check(self) -> None:
        if (len(self.video), len(self.metadata)) >= self._expected:
            self.done.set()


def run(camera: FakeCamera, config: StreamConfig, received: Received, url: str | None = None) -> StreamSession:
    """Stream until `received` is done, then stop and wait for both ends to finish."""
    session = StreamSession(
        url or camera.url(),
        config,
        on_video=received.on_video if config.video else None,
        on_metadata=received.on_metadata if config.metadata else None,
        on_failure=received.on_failure,
    )
    with session:
        assert received.done.wait(10)
    camera.join()
    return session


@pytest.fixture(scope="module")
def h264_units() -> list[bytes]:
    return encode_video("h264", FRAMES)


@pytest.fixture
def interleaved_camera(h264_units: list[bytes]) -> Iterator[FakeCamera]:
    packets = video_packets("h264", h264_units)
    metadata = metadata_packets(DOCUMENTS)
    # Put each document after the first video frame so both streams interleave on the socket.
    camera = FakeCamera(sdp("h264", metadata=True), packets[:10] + metadata + [(1, b"rtcp")] + packets[10:])
    yield camera
    camera.join()


@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_numpy_video_and_metadata_with_digest_auth(codec: str) -> None:
    packets = video_packets(codec, encode_video(codec, FRAMES)) + metadata_packets(DOCUMENTS)
    camera = FakeCamera(sdp(codec, metadata=True), packets, username="root", password="secret")
    received = Received(FRAMES, len(DOCUMENTS))

    session = run(camera, StreamConfig(video=VideoOutput.RGBA, metadata=True), received)

    assert session.video_codec == codec
    assert [sample.capture_time_ns for sample in received.video] == [(BASE_UNIX_SECONDS + i) * SECOND for i in range(5)]
    first = received.video[0]
    assert isinstance(first.data, np.ndarray) and first.data.shape == (64, 64, 4) and first.keyframe
    assert np.allclose(first.data[32, 32, :3], FRAME_RGB, atol=8)
    assert [document.xml for document in received.metadata] == DOCUMENTS
    assert received.metadata[1].capture_time_ns == (BASE_UNIX_SECONDS + 1) * SECOND
    assert camera.requests == ["DESCRIBE", "DESCRIBE", "SETUP", "SETUP", "PLAY"]
    assert received.failures == [] and session.failure is None


@pytest.mark.parametrize(
    ("output", "check"),
    [
        (VideoOutput.ENCODED, lambda data: isinstance(data, bytes) and data.startswith(b"\x00\x00\x00\x01")),
        (VideoOutput.DECODED, lambda data: isinstance(data, av.VideoFrame) and data.width == 64),
        (VideoOutput.BGR24, lambda data: data.shape == (64, 64, 3) and abs(int(data[0, 0, 0]) - FRAME_RGB[2]) < 8),
        (VideoOutput.GRAY, lambda data: data.shape == (64, 64)),
    ],
)
def test_video_outputs(interleaved_camera: FakeCamera, output: VideoOutput, check: Any) -> None:
    received = Received(FRAMES)

    run(interleaved_camera, StreamConfig(video=output), received)

    assert all(check(sample.data) for sample in received.video)
    assert [sample.keyframe for sample in received.video] == [True] + [False] * (FRAMES - 1)
    assert received.video[-1].rtp_timestamp == (FRAMES - 1) * 3000
    assert interleaved_camera.requests == ["DESCRIBE", "SETUP", "PLAY"]


def test_encoded_access_units_decode_to_every_frame(h264_units: list[bytes]) -> None:
    camera = FakeCamera(sdp("h264", metadata=False), video_packets("h264", h264_units))
    received = Received(FRAMES)

    run(camera, StreamConfig(video=VideoOutput.ENCODED), received)

    decoder = av.CodecContext.create("h264", "r")
    assert isinstance(decoder, av.VideoCodecContext)
    frames = [frame for sample in received.video for frame in decoder.decode(av.Packet(sample.data))]
    assert len(frames) == FRAMES


def test_callback_exception_stops_the_session_and_is_reported_once(interleaved_camera: FakeCamera) -> None:
    error = RuntimeError("boom")
    received = Received(FRAMES)

    def on_video(sample: VideoSample[NDArray[np.uint8]]) -> None:
        received.on_video(sample)
        raise error

    session = StreamSession(interleaved_camera.url(), StreamConfig(), on_video=on_video, on_failure=received.on_failure)
    session.start()
    session.join(10)

    assert not session.is_running
    assert len(received.video) == 1
    assert received.failures == [error] and session.failure is error


def test_stop_from_a_callback(interleaved_camera: FakeCamera) -> None:
    received = Received()
    holder: list[StreamSession] = []

    def on_metadata(document: SceneMetadata) -> None:
        received.on_metadata(document)
        holder[0].stop()

    session = StreamSession(interleaved_camera.url(), StreamConfig(video=None, metadata=True), on_metadata=on_metadata)
    holder.append(session)
    session.start()
    session.join(10)
    interleaved_camera.join()

    assert not session.is_running and session.failure is None
    assert len(received.metadata) == 1
    assert interleaved_camera.requests[-1] == "PLAY"


def test_camera_closing_the_connection_is_a_failure() -> None:
    camera = FakeCamera(sdp(None, metadata=True), metadata_packets(DOCUMENTS), close_after_packets=True)
    received = Received(documents=99)

    run(camera, StreamConfig(video=None, metadata=True), received)

    assert len(received.metadata) == len(DOCUMENTS)
    assert isinstance(received.failures[0], StreamError)
    assert "closed" in str(received.failures[0])


def test_silent_camera_times_out() -> None:
    camera = FakeCamera(sdp(None, metadata=True), [])
    received = Received(documents=1)

    run(camera, StreamConfig(video=None, metadata=True, timeout=0.3), received)

    assert [str(failure) for failure in received.failures] == ["no data received for 0.3 s"]


def test_keepalive_is_sent_within_the_session_timeout() -> None:
    documents = [DOCUMENTS[0]] * 12
    camera = FakeCamera(sdp(None, metadata=True), metadata_packets(documents), session_timeout=1, packet_interval=0.03)
    received = Received(documents=len(documents))

    run(camera, StreamConfig(video=None, metadata=True), received)

    assert "GET_PARAMETER" in camera.requests
    assert received.failures == []


@pytest.mark.parametrize("rotate_nonce", [False, True])
def test_keepalive_is_sent_while_waiting_for_media(rotate_nonce: bool) -> None:
    camera = FakeCamera(
        sdp(None, metadata=True), [], username="root", password="secret", session_timeout=1, rotate_nonce=rotate_nonce
    )
    received = Received(documents=1)
    session = StreamSession(
        camera.url(),
        StreamConfig(video=None, metadata=True, timeout=3),
        on_metadata=received.on_metadata,
        on_failure=received.on_failure,
    )

    try:
        with session:
            assert camera.keepalive_received.wait(0.9)
            assert session.is_running
    finally:
        camera.join()

    assert session.failure is None and received.failures == []


def test_keepalive_authentication_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = FakeCamera(sdp(None, metadata=True), [], username="root", password="secret", session_timeout=1)
    authorized = camera._authorized
    monkeypatch.setattr(
        camera, "_authorized", lambda method, uri, header: method != "GET_PARAMETER" and authorized(method, uri, header)
    )
    received = Received(documents=1)

    session = run(camera, StreamConfig(video=None, metadata=True, timeout=3), received)

    assert camera.requests.count("GET_PARAMETER") == 2
    assert isinstance(session.failure, StreamError)
    assert received.failures == [session.failure]
    assert str(session.failure) == "RTSP keepalive authentication was refused"


def test_keepalive_send_failure_ends_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(connection: RtspConnection) -> None:
        raise OSError("unsafe third-party error")

    monkeypatch.setattr(RtspConnection, "keepalive", fail)
    camera = FakeCamera(sdp(None, metadata=True), [], session_timeout=1)
    received = Received(documents=1)

    session = run(camera, StreamConfig(video=None, metadata=True, timeout=3), received)

    assert not session.is_running
    assert isinstance(session.failure, StreamError)
    assert received.failures == [session.failure]
    assert str(session.failure) == "could not send RTSP keepalive"
    assert session.failure.__context__ is None


def test_stop_does_not_wait_for_a_blocked_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    sending = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def blocked_keepalive(connection: RtspConnection) -> None:
        with connection._send_lock:
            sending.set()
            assert release.wait(5)

    monkeypatch.setattr(RtspConnection, "keepalive", blocked_keepalive)
    camera = FakeCamera(sdp(None, metadata=True), [], session_timeout=1)
    session = StreamSession(camera.url(), StreamConfig(video=None, metadata=True), on_metadata=lambda document: None)

    def stop() -> None:
        session.stop()
        stopped.set()

    stopper = threading.Thread(target=stop)
    try:
        session.start()
        assert sending.wait(2)
        stopper.start()
        assert stopped.wait(0.5)
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(5)
        session.stop()
        session.join(5)
        camera.join()

    assert not session.is_running and session.failure is None


def test_start_fails_without_the_requested_stream() -> None:
    camera = FakeCamera(sdp("h264", metadata=False), [])
    session = StreamSession(camera.url(), StreamConfig(metadata=True), on_video=print, on_metadata=print)

    with pytest.raises(StreamError, match="no scene metadata"):
        session.start()
    camera.join()
    assert camera.requests == ["DESCRIBE", "SETUP"]


def test_start_fails_with_a_wrong_password_without_leaking_it() -> None:
    camera = FakeCamera(sdp("h264", metadata=False), [], username="root", password="secret")
    url = camera.url(password="wrong-password")
    session = StreamSession(url, StreamConfig(), on_video=print)

    with pytest.raises(StreamError, match="401") as raised:
        session.start()
    camera.join()

    assert "wrong-password" not in f"{raised.value} {session.name} {session!r}"


def test_start_fails_when_nothing_listens() -> None:
    with socket.create_server(("127.0.0.1", 0)) as unused:
        port = unused.getsockname()[1]
    session = StreamSession(f"rtsp://127.0.0.1:{port}/", StreamConfig(timeout=2), on_video=print)

    with pytest.raises(StreamError, match="ConnectionRefusedError|not ready within 2 s"):
        session.start()
    session.join(5)
    assert not session.is_running


def test_start_reports_a_connection_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(address: object, *, timeout: float) -> socket.socket:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(socket, "create_connection", refuse)
    session = StreamSession("rtsp://127.0.0.1/", StreamConfig(timeout=2), on_video=lambda sample: None)

    with pytest.raises(StreamError, match="ConnectionRefusedError"):
        session.start()
    session.join(5)
    assert not session.is_running


def test_stop_before_start_cancels() -> None:
    session = StreamSession("rtsp://192.0.2.1/", StreamConfig(), on_video=print)
    session.stop()

    with pytest.raises(StartCancelledError):
        session.start()
    assert not session.is_running


def test_callbacks_must_match_the_config() -> None:
    with pytest.raises(ValueError, match="on_metadata"):
        StreamSession("rtsp://camera/", StreamConfig(metadata=True), on_video=print)
    with pytest.raises(ValueError, match="video, metadata or both"):
        StreamConfig(video=None)
