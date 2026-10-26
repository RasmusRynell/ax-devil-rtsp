"""RTSP 1.0 control connection with RTP and RTCP interleaved on the same TCP socket."""

from __future__ import annotations

import http.client
import io
import logging
import re
import threading
from typing import NamedTuple
from urllib.parse import unquote, urljoin, urlsplit

from ._auth import _authorization, _pick_challenge
from ._errors import StreamError
from ._transport import USER_AGENT, Transport

logger = logging.getLogger(__name__)


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


class RtspConnection:
    """One RTSP control connection that also carries the session's interleaved RTP and RTCP packets.

    Only `keepalive()` and `shutdown()` may be called from another thread than the one that drives the connection.
    """

    def __init__(self, url: str, timeout: float, *, verify_tls: bool = True) -> None:
        self._transport = Transport(url, timeout, verify_tls=verify_tls)
        parts = urlsplit(url)
        netloc = parts.netloc.rpartition("@")[2]
        self.url = parts._replace(scheme="rtsp", netloc=netloc).geturl()
        self.name = parts._replace(netloc=netloc, query="", fragment="").geturl()
        self.session_timeout = 60.0
        self._username = unquote(parts.username or "")
        self._password = unquote(parts.password or "")
        self._timeout = timeout
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
        self._reader = self._transport.connect()

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
        self._transport.shutdown()

    def close(self) -> None:
        """Release the transport after its I/O threads have stopped."""
        self._transport.close()

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
            self._transport.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
