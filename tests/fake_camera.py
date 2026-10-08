"""A local fake Axis camera: an RTSP server that streams prepared RTP packets interleaved over TCP."""

from __future__ import annotations

import http.client
import re
import socket
import struct
import threading
import time
from fractions import Fraction

import av
import numpy as np

from ax_devil_rtsp.rtsp import digest_response

BASE_UNIX_SECONDS = 1_800_000_000
FRAME_RGB = (200, 50, 100)
NONCE = "fake-nonce"
REALM = "fake-camera"


def encode_video(codec: str, count: int, size: int = 64) -> list[bytes]:
    """Encode `count` solid-colour frames as Annex-B access units without B-frames."""
    encoder = av.CodecContext.create("libx264" if codec == "h264" else "libx265", "w")
    assert isinstance(encoder, av.VideoCodecContext)
    encoder.width = encoder.height = size
    encoder.pix_fmt = "yuv420p"
    encoder.time_base = Fraction(1, 30)
    encoder.options = {"tune": "zerolatency"} | ({} if codec == "h264" else {"x265-params": "log-level=none"})
    image = np.full((size, size, 3), FRAME_RGB, np.uint8)
    units: list[bytes] = []
    for index in range(count):
        frame = av.VideoFrame.from_ndarray(image, format="rgb24").reformat(format="yuv420p")
        frame.pts = index
        units += [bytes(packet) for packet in encoder.encode(frame)]
    units += [bytes(packet) for packet in encoder.encode(None)]
    return units


def split_nals(access_unit: bytes) -> list[bytes]:
    """Split Annex-B data into NAL units."""
    return [nal.rstrip(b"\x00") for nal in re.split(b"\x00\x00\x01", access_unit) if nal.rstrip(b"\x00")]


def rtp_packet(
    payload: bytes, sequence: int, timestamp: int, marker: bool, capture_seconds: int | None = None
) -> bytes:
    """Build an RTP packet, with the Axis capture time extension when `capture_seconds` is given."""
    extension = b""
    if capture_seconds is not None:
        extension = struct.pack("!HHIII", 0xABAC, 3, capture_seconds + 2_208_988_800, 0, 0)
    first = 0x80 | (0x10 if extension else 0)
    header = struct.pack("!BBHII", first, (0x80 if marker else 0) | 96, sequence & 0xFFFF, timestamp, 0x1234)
    return header + extension + payload


def video_payloads(codec: str, access_unit: bytes, mtu: int = 60) -> list[bytes]:
    """Packetize one access unit: parameter sets in one aggregation packet, large NAL units fragmented."""
    header_size = 1 if codec == "h264" else 2
    parameter_types = {7, 8} if codec == "h264" else {32, 33, 34}
    payloads: list[bytes] = []
    parameter_sets: list[bytes] = []
    for nal in split_nals(access_unit):
        nal_type = nal[0] & 0x1F if codec == "h264" else (nal[0] >> 1) & 0x3F
        if nal_type in parameter_types:
            parameter_sets.append(nal)
            continue
        if len(nal) <= mtu:
            payloads.append(nal)
            continue
        chunks = [nal[i : i + mtu] for i in range(header_size, len(nal), mtu)]
        for index, chunk in enumerate(chunks):
            fu = nal_type | (0x80 if index == 0 else 0) | (0x40 if index == len(chunks) - 1 else 0)
            if codec == "h264":
                payloads.append(bytes(((nal[0] & 0xE0) | 28, fu)) + chunk)
            else:
                payloads.append(bytes(((nal[0] & 0x81) | (49 << 1), nal[1], fu)) + chunk)
    if parameter_sets:
        aggregate = bytes((0x18,)) if codec == "h264" else bytes((48 << 1, 1))
        aggregate += b"".join(struct.pack("!H", len(nal)) + nal for nal in parameter_sets)
        payloads.insert(0, aggregate)
    return payloads


def video_packets(codec: str, access_units: list[bytes]) -> list[tuple[int, bytes]]:
    """Interleaved channel 0 packets; frame i is captured at BASE_UNIX_SECONDS + i."""
    packets = []
    sequence = 0
    for index, access_unit in enumerate(access_units):
        payloads = video_payloads(codec, access_unit)
        for position, payload in enumerate(payloads):
            capture = BASE_UNIX_SECONDS + index if position == 0 else None
            packets.append((0, rtp_packet(payload, sequence, index * 3000, position == len(payloads) - 1, capture)))
            sequence += 1
    return packets


def metadata_packets(documents: list[str], channel: int = 2) -> list[tuple[int, bytes]]:
    """Interleaved packets with each document split in three; document i is captured at BASE_UNIX_SECONDS + i."""
    packets = []
    sequence = 100
    for index, document in enumerate(documents):
        data = document.encode()
        cuts = [0, len(data) // 3, 2 * len(data) // 3, len(data)]
        for part in range(3):
            capture = BASE_UNIX_SECONDS + index if part == 0 else None
            payload = data[cuts[part] : cuts[part + 1]]
            packets.append((channel, rtp_packet(payload, sequence, index * 9000, part == 2, capture)))
            sequence += 1
    return packets


def sdp(codec: str | None, metadata: bool) -> str:
    """An Axis-like SDP description with relative track controls."""
    lines = ["v=0", "o=- 0 0 IN IP4 127.0.0.1", "s=fake", "t=0 0", "a=control:*"]
    if codec is not None:
        encoding = "H264" if codec == "h264" else "H265"
        lines += ["m=video 0 RTP/AVP 96", f"a=rtpmap:96 {encoding}/90000", "a=control:trackID=1"]
    if metadata:
        lines += ["m=application 0 RTP/AVP 98", "a=rtpmap:98 vnd.onvif.metadata/90000", "a=control:trackID=2"]
    return "\r\n".join(lines) + "\r\n"


class FakeCamera:
    """Serves one RTSP connection on localhost and records the requests it receives."""

    def __init__(
        self,
        sdp: str,
        packets: list[tuple[int, bytes]],
        *,
        username: str = "",
        password: str = "",
        session_timeout: int = 60,
        packet_interval: float = 0.0,
        close_after_packets: bool = False,
        rotate_nonce: bool = False,
    ) -> None:
        self.sdp = sdp
        self.packets = packets
        self.username = username
        self.password = password
        self.nonce = NONCE
        self._rotate_nonce = rotate_nonce
        self.session_timeout = session_timeout
        self.packet_interval = packet_interval
        self.close_after_packets = close_after_packets
        self.requests: list[str] = []
        self.request_uris: list[str] = []
        self.keepalive_received = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(10)
        self.port = self._listener.getsockname()[1]
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def url(self, username: str | None = None, password: str | None = None) -> str:
        """The stream URL, with this camera's credentials unless others are given."""
        username = self.username if username is None else username
        password = self.password if password is None else password
        credentials = f"{username}:{password}@" if username or password else ""
        return f"rtsp://{credentials}127.0.0.1:{self.port}/axis-media/media.amp?camera=1"

    def join(self) -> None:
        """Wait until the client has disconnected."""
        self._thread.join(10)
        self._listener.close()

    def _serve(self) -> None:
        try:
            connection, _ = self._listener.accept()
        except OSError:
            return
        with connection, connection.makefile("rb") as reader:
            try:
                while line := reader.readline():
                    method, uri, _ = line.decode().split(" ", 2)
                    headers = http.client.parse_headers(reader)
                    self.requests.append(method)
                    self.request_uris.append(uri)
                    self._answer(connection, method, uri, headers)
            except OSError:
                pass

    def _answer(self, connection: socket.socket, method: str, uri: str, headers: http.client.HTTPMessage) -> None:
        cseq = headers.get("CSeq", "0")
        if method == "GET_PARAMETER" and self._rotate_nonce:
            self.nonce = "fresh-nonce"
            self._rotate_nonce = False
        if self.username and not self._authorized(method, uri, headers.get("Authorization", "")):
            challenge = f'Digest realm="{REALM}", nonce="{self.nonce}", qop="auth"'
            self._send(
                connection, f"RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\nWWW-Authenticate: {challenge}\r\n\r\n"
            )
            return
        extra = ""
        body = ""
        if method == "DESCRIBE":
            body = self.sdp
            extra = (
                f"Content-Base: rtsp://127.0.0.1:{self.port}/axis-media/media.amp/\r\nContent-Type: application/sdp\r\n"
            )
        elif method == "SETUP":
            extra = f"Session: 12345678;timeout={self.session_timeout}\r\nTransport: {headers['Transport']}\r\n"
        reply = f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\n{extra}Content-Length: {len(body)}\r\n\r\n{body}"
        self._send(connection, reply)
        if method == "GET_PARAMETER":
            self.keepalive_received.set()
        if method == "PLAY":
            threading.Thread(target=self._stream, args=(connection,), daemon=True).start()

    def _authorized(self, method: str, uri: str, header: str) -> bool:
        fields = {key: value.strip('"') for key, value in re.findall(r'(\w+)=("[^"]*"|[^\s,]*)', header)}
        expected = digest_response(
            self.username,
            self.password,
            REALM,
            self.nonce,
            method,
            uri,
            qop="auth",
            nc=fields.get("nc", ""),
            cnonce=fields.get("cnonce", ""),
        )
        return header.startswith("Digest ") and fields.get("response") == expected and fields.get("uri") == uri

    def _send(self, connection: socket.socket, data: bytes | str) -> None:
        with self._send_lock:
            connection.sendall(data.encode() if isinstance(data, str) else data)

    def _stream(self, connection: socket.socket) -> None:
        try:
            for channel, packet in self.packets:
                self._send(connection, struct.pack("!BBH", 0x24, channel, len(packet)) + packet)
                time.sleep(self.packet_interval)
            if self.close_after_packets:
                connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
