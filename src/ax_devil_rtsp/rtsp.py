"""RTSP 1.0 control connection with RTP and RTCP interleaved on the same TCP socket."""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import logging
import re
import secrets
import socket
import ssl
import threading
from typing import NamedTuple, Protocol, cast
from urllib.parse import unquote, urljoin, urlsplit

logger = logging.getLogger(__name__)

USER_AGENT = "ax-devil-rtsp"
_DEFAULT_PORTS = {"rtsp": 554, "http": 80, "https": 443}


class StreamError(Exception):
    """A connection, protocol or decoding failure of a stream session.

    The message never contains credentials, and the third-party exception that caused it is not chained.
    """


class Media(NamedTuple):
    """One media section of an SDP description."""

    kind: str
    encoding: str
    fmtp: dict[str, str]
    control: str


def _resolve_control(base: str, control: str) -> str:
    if control in ("", "*"):
        return base
    return urljoin(base, control)


def parse_sdp(sdp: str, base: str) -> tuple[str, list[Media]]:
    """Return the aggregate control URL and the media sections of an SDP description."""
    aggregate = ""
    sections: list[dict[str, str]] = []
    fmtps: list[dict[str, str]] = []
    for line in sdp.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "m":
            sections.append({"kind": value.split(" ", 1)[0], "encoding": "", "control": ""})
            fmtps.append({})
        elif key != "a":
            continue
        name, _, attribute = value.partition(":")
        if name == "control":
            if sections:
                sections[-1]["control"] = attribute.strip()
            else:
                aggregate = attribute.strip()
        elif not sections:
            continue
        elif name == "rtpmap" and not sections[-1]["encoding"]:
            sections[-1]["encoding"] = attribute.partition(" ")[2].split("/")[0].upper()
        elif name == "fmtp":
            for param in attribute.partition(" ")[2].split(";"):
                param_name, _, param_value = param.strip().partition("=")
                fmtps[-1][param_name] = param_value
    medias = [
        Media(section["kind"], section["encoding"], fmtp, _resolve_control(base, section["control"]))
        for section, fmtp in zip(sections, fmtps, strict=True)
    ]
    return _resolve_control(base, aggregate), medias


def _md5(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def digest_response(
    username: str,
    password: str,
    realm: str,
    nonce: str,
    method: str,
    uri: str,
    *,
    qop: str = "",
    nc: str = "",
    cnonce: str = "",
) -> str:
    """Return the RFC 2617 MD5 digest response."""
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    if qop:
        return _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    return _md5(f"{ha1}:{nonce}:{ha2}")


def _parse_challenge(header: str) -> tuple[str, dict[str, str]]:
    scheme, _, rest = header.strip().partition(" ")
    params = {key.lower(): value.strip('"') for key, value in re.findall(r'(\w+)=("[^"]*"|[^\s,]*)', rest)}
    return scheme.lower(), params


def _pick_challenge(headers: list[str]) -> tuple[str, dict[str, str]] | None:
    challenges = [_parse_challenge(header) for header in headers]
    for scheme, params in challenges:
        if scheme == "digest" and params.get("algorithm", "MD5").upper() == "MD5":
            return scheme, params
    return next((challenge for challenge in challenges if challenge[0] == "basic"), None)


def _authorization(
    username: str, password: str, challenge: tuple[str, dict[str, str]], method: str, uri: str, nc: int
) -> str:
    """Return the Authorization header value answering `challenge`; `nc` counts the uses of its nonce."""
    scheme, params = challenge
    if scheme == "basic":
        return f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
    realm, nonce = params.get("realm", ""), params.get("nonce", "")
    fields = [f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
    if "auth" in (qop.strip() for qop in params.get("qop", "").split(",")):
        nc_value, cnonce = f"{nc:08x}", secrets.token_hex(8)
        response = digest_response(
            username, password, realm, nonce, method, uri, qop="auth", nc=nc_value, cnonce=cnonce
        )
        fields += [f'response="{response}"', "qop=auth", f"nc={nc_value}", f'cnonce="{cnonce}"']
    else:
        fields.append(f'response="{digest_response(username, password, realm, nonce, method, uri)}"')
    if "opaque" in params:
        fields.append(f'opaque="{params["opaque"]}"')
    if "algorithm" in params:
        fields.append(f"algorithm={params['algorithm']}")
    return f"Digest {', '.join(fields)}"


class _Transport(Protocol):
    def sendall(self, data: bytes, /) -> object: ...

    def shutdown(self, how: int, /) -> object: ...

    def close(self) -> object: ...


class _HttpTunnel:
    """RTSP over HTTP: replies arrive on the body of a GET response, requests leave base64-encoded in a POST body.

    `shutdown()` may be called from another thread, also while `connect()` is still running.
    """

    def __init__(
        self,
        host: str,
        port: int,
        netloc: str,
        target: str,
        ssl_context: ssl.SSLContext | None,
        timeout: float,
        username: str,
        password: str,
    ) -> None:
        self._host = host
        self._port = port
        self._netloc = netloc
        self._target = target
        self._ssl_context = ssl_context
        self._timeout = timeout
        self._username = username
        self._password = password
        self._cookie = secrets.token_hex(8)
        self._stopped = False
        self._sockets: list[socket.socket] = []
        self._readers: list[io.BufferedReader] = []
        self._post: socket.socket | None = None

    def connect(self) -> io.BufferedReader:
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
            reader = cast(io.BufferedReader, get.makefile("rb", buffering=1 << 16))
            self._readers.append(reader)
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
        self._post = post
        self._check()
        return reader

    def sendall(self, data: bytes) -> None:
        """Send one whole RTSP message."""
        assert self._post is not None
        self._post.sendall(base64.b64encode(data))

    def shutdown(self, how: int) -> None:
        """Unblock any thread waiting on the connections, also one that is still connecting; never raises."""
        self._stopped = True
        for sock in tuple(self._sockets):
            try:
                sock.shutdown(how)
            except OSError:
                pass

    def close(self) -> None:
        """Release both connections."""
        for reader in tuple(self._readers):
            reader.close()
        for sock in tuple(self._sockets):
            sock.close()

    def _check(self) -> None:
        if self._stopped:
            raise StreamError("the connection was stopped")

    def _open(self) -> socket.socket:
        raw = socket.create_connection((self._host, self._port), timeout=self._timeout)
        sock = raw
        try:
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


class RtspConnection:
    """One RTSP control connection that also carries the session's interleaved RTP and RTCP packets.

    Only `keepalive()` and `shutdown()` may be called from another thread than the one that drives the connection.
    """

    def __init__(self, url: str, timeout: float, *, verify_tls: bool = True) -> None:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS:
            raise ValueError("only rtsp://, http:// and https:// URLs are supported")
        if not parts.hostname:
            raise ValueError("the RTSP URL has no host")
        netloc = parts.netloc.rpartition("@")[2]
        self.url = parts._replace(scheme="rtsp", netloc=netloc).geturl()
        self.name = parts._replace(netloc=netloc, query="", fragment="").geturl()
        self.session_timeout = 60.0
        self._address = (parts.hostname, parts.port or _DEFAULT_PORTS[scheme])
        self._tunnel_netloc = netloc if scheme != "rtsp" else None
        self._tunnel_target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        self._tls = scheme == "https"
        self._verify_tls = verify_tls
        self._username = unquote(parts.username or "")
        self._password = unquote(parts.password or "")
        self._timeout = timeout
        self._sock: _Transport | None = None
        self._reader: io.BufferedReader | None = None
        self._send_lock = threading.Lock()
        self._cseq = 0
        self._nc = 0
        self._challenge: tuple[str, dict[str, str]] | None = None
        self._keepalive_retried = False
        self._session_id = ""
        self._aggregate_url = self.url

    def connect(self) -> None:
        """Open the TCP connection, or the HTTP tunnel for an http:// or https:// URL."""
        if self._tunnel_netloc is not None:
            context = None
            if self._tls:
                context = ssl.create_default_context()
                if not self._verify_tls:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
            tunnel = _HttpTunnel(
                *self._address,
                self._tunnel_netloc,
                self._tunnel_target,
                context,
                self._timeout,
                self._username,
                self._password,
            )
            self._sock = tunnel  # before connecting, so that shutdown() can interrupt a connect in progress
            self._reader = tunnel.connect()
            return
        sock = socket.create_connection(self._address, timeout=self._timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._reader = cast(io.BufferedReader, sock.makefile("rb", buffering=1 << 16))
        self._sock = sock

    def describe(self) -> tuple[str, list[Media]]:
        """Return the aggregate control URL and media sections of the stream."""
        headers, body = self.request("DESCRIBE", self.url, {"Accept": "application/sdp"})
        base = urljoin(self.url, headers.get("Content-Base") or headers.get("Content-Location") or self.url)
        return parse_sdp(body.decode("utf-8", "replace"), base)

    def setup(self, url: str, channel: int) -> int:
        """Set up one track interleaved on `channel` and return the RTP channel the server chose."""
        transport = f"RTP/AVP/TCP;unicast;interleaved={channel}-{channel + 1}"
        headers, _ = self.request("SETUP", url, {"Transport": transport})
        session_id, *params = (part.strip() for part in headers.get("Session", "").split(";"))
        if not session_id:
            raise StreamError("SETUP response has no session")
        self._session_id = session_id
        for param in params:
            if param.startswith("timeout="):
                self.session_timeout = float(param[len("timeout=") :])
        chosen = re.search(r"interleaved=(\d+)", headers.get("Transport", ""))
        return int(chosen.group(1)) if chosen else channel

    def play(self, url: str) -> None:
        """Start the set-up tracks."""
        self._aggregate_url = url
        self.request("PLAY", url, {"Range": "npt=0.000-"})

    def keepalive(self) -> None:
        """Keep the RTSP session alive; the reply is read and dropped by `read_packet()`."""
        self._send("GET_PARAMETER", self._aggregate_url, {})

    def shutdown(self) -> None:
        """Unblock any thread waiting on the socket; never raises."""
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        """Release the socket."""
        if self._reader is not None:
            self._reader.close()
        if self._sock is not None:
            self._sock.close()

    def request(self, method: str, url: str, headers: dict[str, str]) -> tuple[http.client.HTTPMessage, bytes]:
        """Send one request and return the headers and body of its 200 OK response."""
        status, reason, response_headers, body = self._exchange(method, url, headers)
        if status == 401 and (self._username or self._password):
            challenge = _pick_challenge(response_headers.get_all("WWW-Authenticate") or [])
            if challenge is not None:
                self._challenge = challenge
                status, reason, response_headers, body = self._exchange(method, url, headers)
        if status == 401:
            hint = "check the username and password" if self._username else "the URL has no credentials"
            raise StreamError(f"{method} was refused with 401 {reason}: {hint}")
        if status != 200:
            raise StreamError(f"{method} failed with {status} {reason}")
        return response_headers, body

    def read_packet(self) -> tuple[int, bytes]:
        """Return the next interleaved packet as (channel, packet), skipping RTSP responses."""
        assert self._reader is not None
        read = self._reader.read
        try:
            while True:
                head = read(4)
                if len(head) < 4:
                    raise StreamError("the camera closed the connection")
                if head[0] != 0x24:
                    self._read_reply(head)
                    continue
                size = (head[2] << 8) | head[3]
                packet = read(size)
                if len(packet) < size:
                    raise StreamError("the camera closed the connection")
                return head[1], packet
        except TimeoutError:
            raise StreamError(f"no data received for {self._timeout:g} s") from None

    def _exchange(
        self, method: str, url: str, headers: dict[str, str]
    ) -> tuple[int, str, http.client.HTTPMessage, bytes]:
        self._send(method, url, headers)
        return self._read_response(b"")

    def _read_reply(self, head: bytes) -> None:
        status, reason, headers, _ = self._read_response(head)
        if status == 401:
            challenge = _pick_challenge(headers.get_all("WWW-Authenticate") or [])
            if self._keepalive_retried or challenge is None:
                raise StreamError("RTSP keepalive authentication was refused")
            with self._send_lock:
                self._challenge = challenge
                self._nc = 0
            self._keepalive_retried = True
            self.keepalive()
        elif status == 454:
            raise StreamError("the camera ended the RTSP session (454 Session Not Found)")
        elif status != 200:
            logger.warning("RTSP keepalive answered %s %s", status, reason)
        else:
            self._keepalive_retried = False

    def _read_response(self, head: bytes) -> tuple[int, str, http.client.HTTPMessage, bytes]:
        assert self._reader is not None
        line = head + self._reader.readline(1 << 16)
        if not line.endswith(b"\n"):
            raise StreamError("the camera closed the connection")
        version, _, status = line.decode("latin-1").strip().partition(" ")
        code, _, reason = status.partition(" ")
        if not version.startswith("RTSP/") or not code.isdigit():
            raise StreamError("invalid RTSP response")
        headers = http.client.parse_headers(self._reader)
        length = int(headers.get("Content-Length", "0"))
        body = self._reader.read(length) if length else b""
        return int(code), reason, headers, body

    def _send(self, method: str, url: str, headers: dict[str, str]) -> None:
        with self._send_lock:
            assert self._sock is not None
            self._cseq += 1
            lines = [f"{method} {url} RTSP/1.0", f"CSeq: {self._cseq}", f"User-Agent: {USER_AGENT}"]
            if self._session_id:
                lines.append(f"Session: {self._session_id}")
            if self._challenge is not None:
                self._nc += 1
                lines.append(
                    "Authorization: "
                    + _authorization(self._username, self._password, self._challenge, method, url, self._nc)
                )
            lines += [f"{name}: {value}" for name, value in headers.items()]
            self._sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
