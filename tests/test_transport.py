"""Transport wire contract and ownership, including partially opened connections."""

from __future__ import annotations

import base64
import io
import socket
from unittest.mock import Mock

import pytest

from ax_devil_rtsp import StreamError
from ax_devil_rtsp._auth import _parse_challenge, digest_response
from ax_devil_rtsp._transport import Transport


@pytest.mark.parametrize(
    ("url", "port"), [("rtsp://c/", 554), ("http://c/", 80), ("https://c/", 443), ("http://c:81/", 81)]
)
def test_default_ports(url: str, port: int, monkeypatch: pytest.MonkeyPatch) -> None:
    connect = Mock(side_effect=OSError("not connected"))
    monkeypatch.setattr(socket, "create_connection", connect)
    with pytest.raises(OSError):
        Transport(url, 2).connect()
    connect.assert_called_once_with(("c", port), timeout=2)


def connection(response: bytes = b"") -> Mock:
    sock = Mock(spec=socket.socket)
    sock.makefile.return_value = io.BytesIO(response)
    return sock


@pytest.mark.parametrize("scheme", ["rtsp", "http"])
def test_stream_and_message_contract_and_cleanup(scheme: str, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"RTSP/1.0 200 OK\r\n\r\n$\x00\x00\x04data"
    incoming = connection((b"HTTP/1.0 200 OK\r\n\r\n" if scheme == "http" else b"") + payload)
    outgoing = connection() if scheme == "http" else incoming
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=[incoming, outgoing]))
    transport = Transport(f"{scheme}://camera/live", 1)
    reader = transport.connect()
    assert reader.read() == payload
    message = b"OPTIONS rtsp://camera/live RTSP/1.0\r\n\r\n"
    transport.sendall(message)
    outgoing.sendall.assert_called_with(base64.b64encode(message) if scheme == "http" else message)
    transport.shutdown()
    transport.close()
    transport.shutdown()
    transport.close()
    assert reader.closed
    for sock in {incoming, outgoing}:
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        sock.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (b"HTTP/1.0 302 Found\r\nLocation: http://other/\r\n\r\n", "302 Found"),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", "chunked"),
        (b"invalid\r\n\r\n", "invalid HTTP"),
        (b"", "closed"),
        (b"HTTP/1.0 401 Unauthorized\r\n\r\n", "401"),
    ],
)
def test_rejected_http_setup_closes_every_resource(
    response: bytes, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sock = connection(response)
    connect = Mock(return_value=sock)
    monkeypatch.setattr(socket, "create_connection", connect)
    transport = Transport("http://camera/live", 1)
    with pytest.raises(StreamError, match=error):
        transport.connect()
    connect.assert_called_once()
    assert sock.makefile.return_value.closed
    sock.close.assert_called_once()
    transport.close()
    sock.close.assert_called_once()


def test_post_connect_failure_closes_get(monkeypatch: pytest.MonkeyPatch) -> None:
    get = connection(b"HTTP/1.0 200 OK\r\n\r\n")
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=[get, OSError("POST failed")]))
    with pytest.raises(OSError, match="POST failed"):
        Transport("http://camera/live", 1).connect()
    assert get.makefile.return_value.closed
    get.close.assert_called_once()


@pytest.mark.parametrize("scheme", ["rtsp", "http", "https"])
def test_shutdown_during_tcp_connect_closes_late_socket(scheme: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sock = connection()
    transport = Transport(f"{scheme}://camera/live", 1)

    def connect(address: tuple[str, int], timeout: float) -> Mock:
        transport.shutdown()
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    # Check cancellation before TLS wraps the late socket as well.
    with pytest.raises(StreamError, match="stopped"):
        transport.connect()
    sock.close.assert_called()
    sock.makefile.assert_not_called()


def test_tcp_reader_setup_failure_closes_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = connection()
    sock.makefile.side_effect = OSError("reader failed")
    monkeypatch.setattr(socket, "create_connection", Mock(return_value=sock))
    with pytest.raises(OSError, match="reader failed"):
        Transport("rtsp://camera/live", 1).connect()
    sock.close.assert_called_once()


def test_http_digest_uses_get_and_post_targets_and_nonce_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = connection(
        b'HTTP/1.0 401 Unauthorized\r\nWWW-Authenticate: Basic realm="camera"\r\n'
        b'WWW-Authenticate: Digest realm="camera", nonce="nonce", qop="auth"\r\n\r\n'
    )
    get = connection(b"HTTP/1.0 200 OK\r\n\r\n")
    post = connection()
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=[refused, get, post]))
    transport = Transport("http://user:p%40ss@camera/live?camera=2", 1)
    try:
        transport.connect()
        assert refused.makefile.return_value.closed
        for sock, method, nc in [(get, "GET", "00000001"), (post, "POST", "00000002")]:
            wire = sock.sendall.call_args.args[0].decode()
            authorization = next(
                line.removeprefix("Authorization: ") for line in wire.splitlines() if line.startswith("Authorization: ")
            )
            scheme, fields = _parse_challenge(authorization)
            assert scheme == "digest"
            assert fields["uri"] == "/live?camera=2"
            assert fields["nc"] == nc
            assert fields["response"] == digest_response(
                "user",
                "p@ss",
                "camera",
                "nonce",
                method,
                fields["uri"],
                qop="auth",
                nc=nc,
                cnonce=fields["cnonce"],
            )
            assert "p@ss" not in wire and "p%40ss" not in wire
    finally:
        transport.close()
    for sock in (refused, get, post):
        assert sock.makefile.return_value.closed or sock is post
        sock.close.assert_called()
