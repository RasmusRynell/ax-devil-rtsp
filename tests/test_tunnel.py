"""RTSP tunnelled over HTTP and HTTPS against a local fake camera."""

from __future__ import annotations

import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Literal

import pytest
from test_session import DOCUMENTS, FRAMES, SECOND, Received, run

from ax_devil_rtsp import StartCancelledError, StreamConfig, StreamError, StreamSession, VideoOutput
from ax_devil_rtsp.rtsp import RtspConnection

from fake_camera import BASE_UNIX_SECONDS, FakeCamera, encode_video, metadata_packets, sdp, video_packets

Transport = Literal["http", "https"]
TRANSPORTS = ["http", "https"]
CONFIG = StreamConfig(video=VideoOutput.ENCODED, metadata=True, verify_tls=False)


@pytest.fixture(scope="module")
def packets() -> list[tuple[int, bytes]]:
    return video_packets("h264", encode_video("h264", FRAMES)) + metadata_packets(DOCUMENTS)


def stream_once(camera: FakeCamera, config: StreamConfig = CONFIG) -> tuple[StreamSession, Received]:
    received = Received(FRAMES, len(DOCUMENTS))
    return run(camera, config, received), received


def only(camera: FakeCamera, method: str) -> Any:
    (request,) = [request for request in camera.http_requests if request[0] == method]
    return request


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_video_and_metadata_with_capture_times(transport: Transport, packets: list[tuple[int, bytes]]) -> None:
    camera = FakeCamera(sdp("h264", metadata=True), packets, transport=transport)

    session, received = stream_once(camera)

    assert [sample.capture_time_ns for sample in received.video] == [(BASE_UNIX_SECONDS + i) * SECOND for i in range(5)]
    assert [document.xml for document in received.metadata] == DOCUMENTS
    assert received.metadata[1].capture_time_ns == (BASE_UNIX_SECONDS + 1) * SECOND
    assert camera.requests == ["DESCRIBE", "SETUP", "SETUP", "PLAY"]
    assert all(uri.startswith(f"rtsp://127.0.0.1:{camera.port}/axis-media/media.amp") for uri in camera.request_uris)
    assert received.failures == [] and session.failure is None


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_digest_authentication_survives_nonce_rotation(transport: Transport) -> None:
    camera = FakeCamera(
        sdp(None, metadata=True),
        [],
        username="root",
        password="secret",
        session_timeout=1,
        rotate_nonce=True,
        transport=transport,
    )
    received = Received(documents=1)
    session = StreamSession(
        camera.url(),
        StreamConfig(video=None, metadata=True, timeout=3, verify_tls=False),
        on_metadata=received.on_metadata,
        on_failure=received.on_failure,
    )

    try:
        with session:
            assert camera.keepalive_received.wait(2)
            assert session.is_running
    finally:
        camera.join()

    assert "GET_PARAMETER" in camera.requests
    assert session.failure is None and received.failures == []


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_http_401_is_retried_with_authorization_on_both_connections(
    transport: Transport, packets: list[tuple[int, bytes]]
) -> None:
    camera = FakeCamera(
        sdp("h264", metadata=True), packets, username="root", password="secret", transport=transport, http_auth=True
    )

    session, received = stream_once(camera)

    assert [request[0] for request in camera.http_requests] == ["GET", "GET", "POST"]
    first, second, post = camera.http_requests
    assert "Authorization" not in first[2]
    assert second[2]["Authorization"] == post[2]["Authorization"] != ""
    assert session.failure is None and len(received.video) == FRAMES


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_http_authentication_is_refused_after_one_retry(transport: Transport) -> None:
    camera = FakeCamera(
        sdp("h264", metadata=False), [], username="root", password="secret", transport=transport, http_auth=True
    )
    url = camera.url(password="wrong-password")
    session = StreamSession(url, StreamConfig(verify_tls=False), on_video=print)

    with pytest.raises(StreamError, match="refused with 401") as raised:
        session.start()
    camera.join()

    assert [request[0] for request in camera.http_requests] == ["GET", "GET"]
    assert "wrong-password" not in f"{raised.value} {session.name} {session!r}"


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_wrong_rtsp_password_fails_without_leaking_it(transport: Transport) -> None:
    camera = FakeCamera(sdp("h264", metadata=False), [], username="root", password="secret", transport=transport)
    session = StreamSession(camera.url(password="wrong-password"), StreamConfig(verify_tls=False), on_video=print)

    with pytest.raises(StreamError, match="401") as raised:
        session.start()
    camera.join()

    assert "wrong-password" not in f"{raised.value} {session.name} {session!r}"
    assert all("wrong-password" not in target for _, target, _ in camera.http_requests)


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_non_200_tunnel_response_fails_with_the_status(transport: Transport) -> None:
    camera = FakeCamera(sdp("h264", metadata=False), [], transport=transport)
    send = camera._send_http

    def deny(connection: Any, status: str, headers: str = "") -> None:
        send(connection, "403 Forbidden" if status.startswith("200") else status, headers)

    camera._send_http = deny  # type: ignore[method-assign]
    session = StreamSession(camera.url(), StreamConfig(verify_tls=False), on_video=print)

    with pytest.raises(StreamError, match="HTTP tunnel failed with 403 Forbidden"):
        session.start()
    camera.join()
    assert [request[0] for request in camera.http_requests] == ["GET"]


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_close_after_the_last_packet_ends_the_session(transport: Transport) -> None:
    camera = FakeCamera(
        sdp(None, metadata=True), metadata_packets(DOCUMENTS), close_after_packets=True, transport=transport
    )
    received = Received(documents=99)

    run(camera, StreamConfig(video=None, metadata=True, verify_tls=False), received)

    assert len(received.metadata) == len(DOCUMENTS)
    assert isinstance(received.failures[0], StreamError)


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_rtcp_bye_ends_the_session(transport: Transport) -> None:
    bye = bytes([0x81, 203, 0, 1, 0, 0, 0, 1])
    units = video_packets("h264", encode_video("h264", FRAMES))
    camera = FakeCamera(
        sdp("h264", metadata=False), units + [(1, bytes([0x80, 200, 0, 6]) + bytes(24) + bye)], transport=transport
    )
    received = Received(frames=99)

    run(camera, StreamConfig(video=VideoOutput.ENCODED, verify_tls=False), received)

    assert len(received.video) == FRAMES
    assert [str(failure) for failure in received.failures] == ["the camera ended the video stream (RTCP BYE)"]


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_stop_while_streaming_unblocks_the_session(transport: Transport, packets: list[tuple[int, bytes]]) -> None:
    camera = FakeCamera(sdp("h264", metadata=True), packets * 20, packet_interval=0.02, transport=transport)
    received = Received(frames=1)
    session = StreamSession(
        camera.url(),
        CONFIG,
        on_video=received.on_video,
        on_metadata=received.on_metadata,
        on_failure=received.on_failure,
    )

    session.start()
    assert received.done.wait(10)
    started = time.monotonic()
    session.stop()
    session.join(5)
    camera.join()

    assert not session.is_running and session.failure is None
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_tunnel_requests(transport: Transport, packets: list[tuple[int, bytes]]) -> None:
    camera = FakeCamera(sdp("h264", metadata=True), packets, transport=transport)
    url = f"{camera.url(username='user', password='secret-password')}&token=secret-token"
    received = Received(FRAMES, len(DOCUMENTS))

    session = run(camera, CONFIG, received, url=url)

    assert [request[0] for request in camera.http_requests] == ["GET", "POST"]
    (_, get_target, get), (_, post_target, post) = camera.http_requests
    target = "/axis-media/media.amp?camera=1&token=secret-token"
    assert get_target == post_target == target
    assert re.fullmatch(r"[0-9a-f]{16}", get["x-sessioncookie"])
    assert post["x-sessioncookie"] == get["x-sessioncookie"]
    for headers in (get, post):
        assert headers["Host"] == f"127.0.0.1:{camera.port}"
        assert headers["User-Agent"] == "ax-devil-rtsp"
        assert headers["Pragma"] == headers["Cache-Control"] == "no-cache"
        assert "Authorization" not in headers
    assert get["Accept"] == "application/x-rtsp-tunnelled"
    assert post["Content-Type"] == "application/x-rtsp-tunnelled"
    assert post["Content-Length"] == "32767"
    assert "Expires" in post
    assert all(
        "user" not in target and "secret" not in target.replace("secret-token", "")
        for _, target, _ in camera.http_requests
    )
    assert session.name == f"{transport}://127.0.0.1:{camera.port}/axis-media/media.amp"
    assert "secret" not in f"{session!r} {received.failures}"


def test_each_session_has_its_own_cookie() -> None:
    cookies = []
    for _ in range(2):
        camera = FakeCamera(sdp(None, metadata=True), metadata_packets(DOCUMENTS), transport="http")
        run(camera, StreamConfig(video=None, metadata=True), Received(documents=len(DOCUMENTS)))
        cookies.append(only(camera, "GET")[2]["x-sessioncookie"])
    assert cookies[0] != cookies[1]


def test_https_verifies_the_certificate_by_default() -> None:
    camera = FakeCamera(sdp(None, metadata=True), [], transport="https")
    session = StreamSession(camera.url(), StreamConfig(video=None, metadata=True), on_metadata=print)

    with pytest.raises(StreamError, match="verify_tls"):
        session.start()
    camera.join()
    assert camera.http_requests == []


def test_https_without_verification_streams() -> None:
    camera = FakeCamera(sdp(None, metadata=True), metadata_packets(DOCUMENTS), transport="https")
    received = Received(documents=len(DOCUMENTS))

    session = run(camera, StreamConfig(video=None, metadata=True, verify_tls=False), received)

    assert session.failure is None and len(received.metadata) == len(DOCUMENTS)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://root:p%40ss@camera/live?camera=1", "rtsp://camera/live?camera=1"),
        ("HTTPS://camera:8443/live", "rtsp://camera:8443/live"),
        ("rtsp://camera/live", "rtsp://camera/live"),
    ],
)
def test_inner_rtsp_url(url: str, expected: str) -> None:
    assert RtspConnection(url, timeout=1).url == expected


def test_https_with_trusted_certificate_streams(tls_certificate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_certificate))
    camera = FakeCamera(sdp(None, metadata=True), metadata_packets(DOCUMENTS), transport="https")
    received = Received(documents=len(DOCUMENTS))
    session = run(camera, StreamConfig(video=None, metadata=True), received)
    assert session.failure is None and len(received.metadata) == len(DOCUMENTS)


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_tunnel_decodes_video(transport: Transport, codec: str) -> None:
    camera = FakeCamera(
        sdp(codec, metadata=False), video_packets(codec, encode_video(codec, FRAMES)), transport=transport
    )
    received = Received(frames=FRAMES)
    session = run(camera, StreamConfig(video=VideoOutput.RGB24, verify_tls=False), received)
    assert session.failure is None and len(received.video) == FRAMES
    assert all(sample.data.shape == (64, 64, 3) for sample in received.video)
    assert [sample.capture_time_ns for sample in received.video] == [(BASE_UNIX_SECONDS + i) * SECOND for i in range(5)]


@pytest.mark.parametrize("scheme", ["rtsp", "http", "https"])
def test_stop_during_startup_unblocks_io_and_cleans_up(scheme: str) -> None:
    accepted = threading.Event()
    disconnected = threading.Event()
    failures: list[BaseException] = []
    with socket.create_server(("127.0.0.1", 0)) as listener:
        listener.settimeout(5)

        def server() -> None:
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(5)
                # Wait for DESCRIBE, HTTP GET, or the TLS ClientHello, then stall.
                peer.recv(65536)
                accepted.set()
                try:
                    while peer.recv(65536):
                        pass
                except ConnectionResetError:
                    pass
                disconnected.set()

        session = StreamSession(
            f"{scheme}://127.0.0.1:{listener.getsockname()[1]}/live",
            StreamConfig(video=None, metadata=True, timeout=5, verify_tls=False),
            on_metadata=print,
        )

        def start() -> None:
            try:
                session.start()
            except BaseException as error:
                failures.append(error)

        serving = threading.Thread(target=server, daemon=True)
        starting = threading.Thread(target=start, daemon=True)
        serving.start()
        starting.start()
        try:
            assert accepted.wait(3)
            session.stop()
            starting.join(2)
            session.join(2)
            assert not starting.is_alive() and not session.is_running
            assert len(failures) == 1 and isinstance(failures[0], StartCancelledError)
            assert session.failure is None
            assert disconnected.wait(2)
        finally:
            session.stop()
            starting.join(5)
            session.join(5)
            serving.join(5)
