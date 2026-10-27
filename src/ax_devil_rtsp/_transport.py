"""TCP and HTTP(S) transport setup and resource ownership.

HTTP tunnelling uses a GET response body and a base64 POST request body.
Chunked responses and redirects are unsupported. The POST advertises a fixed
Content-Length of 32767 bytes and is not renewed when that budget is exhausted.
"""

from __future__ import annotations

import base64
import http.client
import io
import secrets
import socket
import ssl
from typing import cast
from urllib.parse import unquote, urlsplit

from ._auth import _authorization, _pick_challenge
from ._errors import StreamError

USER_AGENT = "ax-devil-rtsp"
_DEFAULT_PORTS = {"rtsp": 554, "http": 80, "https": 443}


class Transport:
    """One-shot TCP or HTTP(S) byte transport for an RTSP connection.

    connect() lends a buffered input stream to the protocol parser; this object
    owns that reader and every socket, including partially opened connections.
    sendall() accepts a whole RTSP message. Only shutdown() may race with connect()
    or I/O; close() belongs to the owner after all I/O threads have stopped.
    DNS/TCP establishment cannot be interrupted here (TCP uses the configured
    timeout). Once registered, sockets can be interrupted by shutdown(), including
    during TLS negotiation.
    """

    def __init__(self, url: str, timeout: float, *, verify_tls: bool = True) -> None:
        parts = urlsplit(url)
        if parts.scheme not in _DEFAULT_PORTS:
            raise ValueError("only rtsp://, http:// and https:// URLs are supported")
        if not parts.hostname:
            raise ValueError("the RTSP URL has no host")
        self._host = parts.hostname
        self._port = parts.port or _DEFAULT_PORTS[parts.scheme]
        self._netloc = parts.netloc.rpartition("@")[2]
        self._target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        self._scheme = parts.scheme
        self._verify_tls = verify_tls
        self._ssl_context: ssl.SSLContext | None = None
        self._timeout = timeout
        self._username = unquote(parts.username or "")
        self._password = unquote(parts.password or "")
        self._cookie = secrets.token_hex(8)
        self._stopped = False
        self._sockets: list[socket.socket] = []
        self._readers: list[io.BufferedReader] = []
        self._writer: socket.socket | None = None

    def connect(self) -> io.BufferedReader:
        """Open the transport; release all acquired resources if setup fails."""
        try:
            self._check()
            if self._scheme == "https":
                self._ssl_context = ssl.create_default_context()
                if not self._verify_tls:
                    self._ssl_context.check_hostname = False
                    self._ssl_context.verify_mode = ssl.CERT_NONE
            if self._scheme != "rtsp":
                return self._connect_tunnel()
            self._writer = self._open()
            reader = self._reader(self._writer)
            self._check()
            return reader
        except BaseException:
            self.close()
            raise

    def _reader(self, sock: socket.socket) -> io.BufferedReader:
        reader = cast(io.BufferedReader, sock.makefile("rb", buffering=1 << 16))
        self._readers.append(reader)
        return reader

    def _connect_tunnel(self) -> io.BufferedReader:
        """Open both HTTP connections and return the GET reader positioned at the start of the RTSP stream."""
        challenge: tuple[str, dict[str, str]] | None = None
        nc = 0
        while True:
            authorization = None
            if challenge is not None:
                nc += 1
                authorization = _authorization(self._username, self._password, challenge, "GET", self._target, nc)
            get = self._open()
            lines = [
                f"GET {self._target} HTTP/1.0",
                f"Host: {self._netloc}",
                f"User-Agent: {USER_AGENT}",
                f"x-sessioncookie: {self._cookie}",
                "Accept: application/x-rtsp-tunnelled",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ]
            if authorization is not None:
                lines.append(f"Authorization: {authorization}")
            get.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            self._check()
            reader = self._reader(get)
            status, reason, headers = self._read_head(reader)
            self._check()
            if status != 401 or challenge is not None or not (self._username or self._password):
                break
            challenge = _pick_challenge(headers.get_all("WWW-Authenticate") or [])
            if challenge is None:
                break
            reader.close()
            get.close()
        if status == 401:
            hint = "check the username and password" if self._username else "the URL has no credentials"
            raise StreamError(f"HTTP tunnel was refused with 401 {reason}: {hint}")
        if status != 200:
            raise StreamError(f"HTTP tunnel failed with {status} {reason}")
        if "chunked" in headers.get("Transfer-Encoding", "").lower():
            raise StreamError("HTTP tunnel uses chunked transfer encoding, which is not supported")
        lines = [
            f"POST {self._target} HTTP/1.0",
            f"Host: {self._netloc}",
            f"User-Agent: {USER_AGENT}",
            f"x-sessioncookie: {self._cookie}",
            "Content-Type: application/x-rtsp-tunnelled",
            "Pragma: no-cache",
            "Cache-Control: no-cache",
            "Content-Length: 32767",
            "Expires: Sun, 9 Jan 1972 00:00:00 GMT",
        ]
        if challenge is not None:
            nc += 1
            lines.append(
                "Authorization: " + _authorization(self._username, self._password, challenge, "POST", self._target, nc)
            )
        post = self._open()
        post.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        self._writer = post
        self._check()
        return reader

    def sendall(self, data: bytes) -> None:
        """Send one whole RTSP message."""
        assert self._writer is not None
        self._writer.sendall(data if self._scheme == "rtsp" else base64.b64encode(data))

    def shutdown(self) -> None:
        """Unblock any thread waiting on the connections, also one that is still connecting; never raises."""
        self._stopped = True
        for sock in tuple(self._sockets):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        """Release owned readers and sockets, also after partial setup; idempotent."""
        for reader in tuple(self._readers):
            reader.close()
        for sock in tuple(self._sockets):
            sock.close()
        self._readers.clear()
        self._sockets.clear()
        self._writer = None

    def _check(self) -> None:
        if self._stopped:
            raise StreamError("the connection was stopped")

    def _open(self) -> socket.socket:
        raw = socket.create_connection((self._host, self._port), timeout=self._timeout)
        sock = raw
        try:
            self._check()
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
            raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if self._ssl_context is not None:
                sock = self._ssl_context.wrap_socket(raw, server_hostname=self._host, do_handshake_on_connect=False)
            self._sockets.append(sock)
            self._check()
            if isinstance(sock, ssl.SSLSocket):
                sock.do_handshake()
        except ssl.SSLCertVerificationError:
            sock.close()
            raise StreamError(
                f"TLS certificate of {self._host} was not accepted: fix the certificate or set verify_tls=False"
            ) from None
        except BaseException:
            sock.close()
            raise
        return sock

    def _read_head(self, reader: io.BufferedReader) -> tuple[int, str, http.client.HTTPMessage]:
        try:
            line = reader.readline(1 << 16)
            if not line.endswith(b"\n"):
                raise StreamError("the camera closed the connection")
            version, _, status = line.decode("latin-1").strip().partition(" ")
            code, _, reason = status.partition(" ")
            if not version.startswith("HTTP/") or not code.isdigit():
                raise StreamError("invalid HTTP tunnel response")
            return int(code), reason, http.client.parse_headers(reader)
        except TimeoutError:
            raise StreamError(f"no data received for {self._timeout:g} s") from None
