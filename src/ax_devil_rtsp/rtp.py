"""RTP parsing and reassembly of H.264/H.265 access units and Axis scene metadata documents."""

from __future__ import annotations

import base64
import logging
import struct
from typing import Callable, NamedTuple

logger = logging.getLogger(__name__)

START_CODE = b"\x00\x00\x00\x01"
AXIS_TIMESTAMP_EXTENSION = 0xABAC
_NTP_UNIX_OFFSET = 2_208_988_800
_unpack_header = struct.Struct("!BBHI").unpack_from
_unpack_extension = struct.Struct("!HH").unpack_from
_unpack_ntp = struct.Struct("!II").unpack_from

AccessUnitCallback = Callable[[bytes, int, "int | None", bool], None]
MetadataCallback = Callable[[str, int, "int | None"], None]


def ntp_to_unix_ns(seconds: int, fraction: int) -> int:
    """Convert a 64-bit NTP timestamp to Unix nanoseconds."""
    if seconds < 0x8000_0000:  # NTP era 1 starts 2036-02-07 (RFC 4330 section 3)
        seconds += 1 << 32
    return (seconds - _NTP_UNIX_OFFSET) * 1_000_000_000 + ((fraction * 1_000_000_000) >> 32)


class RtpPacket(NamedTuple):
    """The RTP fields the depacketizers use."""

    marker: bool
    sequence: int
    timestamp: int
    capture_time_ns: int | None
    payload: memoryview


def parse_rtp(packet: bytes) -> RtpPacket:
    """Parse one RTP packet, reading the Axis capture time from its header extension."""
    b0, b1, sequence, timestamp = _unpack_header(packet)
    offset = 12 + ((b0 & 0x0F) << 2)
    capture_time_ns = None
    if b0 & 0x10:
        profile, words = _unpack_extension(packet, offset)
        if profile == AXIS_TIMESTAMP_EXTENSION and words >= 3:
            capture_time_ns = ntp_to_unix_ns(*_unpack_ntp(packet, offset + 4))
        offset += 4 + (words << 2)
    end = len(packet) - (packet[-1] if b0 & 0x20 else 0)
    if end < offset:
        raise ValueError("malformed RTP packet")
    return RtpPacket(bool(b1 & 0x80), sequence, timestamp, capture_time_ns, memoryview(packet)[offset:end])


def sdp_parameter_sets(codec: str, fmtp: dict[str, str]) -> bytes:
    """Return the Annex-B parameter sets announced in an SDP fmtp line."""
    keys = ("sprop-parameter-sets",) if codec == "h264" else ("sprop-vps", "sprop-sps", "sprop-pps")
    encoded = [item for key in keys for item in fmtp.get(key, "").split(",") if item]
    return b"".join(START_CODE + base64.b64decode(item + "==") for item in encoded)


def _aggregated(payload: memoryview, offset: int) -> list[memoryview]:
    nals = []
    while offset + 2 <= len(payload):
        size = (payload[offset] << 8) | payload[offset + 1]
        nals.append(payload[offset + 2 : offset + 2 + size])
        offset += 2 + size
    return [nal for nal in nals if nal]


def _depay_h264(payload: memoryview, out: list[bytes | memoryview]) -> bool:
    """Append Annex-B data from one RFC 6184 payload; return True when an IDR NAL starts."""
    nal_type = payload[0] & 0x1F
    if nal_type < 24:
        out += (START_CODE, payload)
        return nal_type == 5
    if nal_type == 24:  # STAP-A
        nals = _aggregated(payload, 1)
        for nal in nals:
            out += (START_CODE, nal)
        return any(nal[0] & 0x1F == 5 for nal in nals)
    if nal_type == 28:  # FU-A
        fu = payload[1]
        if fu & 0x80:
            out += (START_CODE, bytes(((payload[0] & 0xE0) | (fu & 0x1F),)))
        out.append(payload[2:])
        return bool(fu & 0x80) and fu & 0x1F == 5
    return False


def _is_h265_irap(nal_type: int) -> bool:
    return 16 <= nal_type <= 21


def _depay_h265(payload: memoryview, out: list[bytes | memoryview]) -> bool:
    """Append Annex-B data from one RFC 7798 payload; return True when an IRAP NAL starts."""
    nal_type = (payload[0] >> 1) & 0x3F
    if nal_type < 48:
        out += (START_CODE, payload)
        return _is_h265_irap(nal_type)
    if nal_type == 48:  # aggregation packet
        nals = _aggregated(payload, 2)
        for nal in nals:
            out += (START_CODE, nal)
        return any(_is_h265_irap((nal[0] >> 1) & 0x3F) for nal in nals)
    if nal_type == 49:  # fragmentation unit
        fu = payload[2]
        if fu & 0x80:
            out += (START_CODE, bytes(((payload[0] & 0x81) | ((fu & 0x3F) << 1), payload[1])))
        out.append(payload[3:])
        return bool(fu & 0x80) and _is_h265_irap(fu & 0x3F)
    return False


class AccessUnitAssembler:
    """Rebuild Annex-B access units from the RTP packets of one H.264 or H.265 stream.

    The RTP marker bit ends an access unit; a timestamp change also ends one in case a marker is lost.
    """

    def __init__(self, codec: str, parameter_sets: bytes, emit: AccessUnitCallback) -> None:
        self._depay = _depay_h264 if codec == "h264" else _depay_h265
        self._emit = emit
        self._parts: list[bytes | memoryview] = [parameter_sets] if parameter_sets else []
        self._timestamp: int | None = None
        self._capture_time_ns: int | None = None
        self._keyframe = False

    def push(self, packet: bytes) -> None:
        """Add one RTP packet; emits each completed access unit."""
        rtp = parse_rtp(packet)
        if self._timestamp is not None and rtp.timestamp != self._timestamp:
            self._flush()
        self._timestamp = rtp.timestamp
        if rtp.capture_time_ns is not None:
            self._capture_time_ns = rtp.capture_time_ns
        if rtp.payload:
            self._keyframe |= self._depay(rtp.payload, self._parts)
        if rtp.marker:
            self._flush()

    def _flush(self) -> None:
        data = b"".join(self._parts)
        timestamp, capture_time_ns, keyframe = self._timestamp, self._capture_time_ns, self._keyframe
        self._parts.clear()
        self._timestamp = self._capture_time_ns = None
        self._keyframe = False
        if data and timestamp is not None:
            self._emit(data, timestamp, capture_time_ns, keyframe)


class MetadataAssembler:
    """Rebuild scene metadata XML documents from metadata RTP packets.

    A document ends at the RTP marker bit. A sequence gap drops the document it falls in.
    """

    def __init__(self, emit: MetadataCallback) -> None:
        self._emit = emit
        self._parts: list[memoryview] = []
        self._next_sequence: int | None = None
        self._broken = False
        self._capture_time_ns: int | None = None

    def push(self, packet: bytes) -> None:
        """Add one RTP packet; emits each completed document."""
        rtp = parse_rtp(packet)
        if self._next_sequence is not None and rtp.sequence != self._next_sequence:
            self._broken = True
        self._next_sequence = (rtp.sequence + 1) & 0xFFFF
        if rtp.capture_time_ns is not None:
            self._capture_time_ns = rtp.capture_time_ns
        self._parts.append(rtp.payload)
        if not rtp.marker:
            return
        data, broken, capture_time_ns = b"".join(self._parts), self._broken, self._capture_time_ns
        self._parts.clear()
        self._broken = False
        self._capture_time_ns = None
        if broken:
            logger.warning("Dropped a scene metadata document after RTP packet loss")
            return
        try:
            xml = data.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Dropped a scene metadata document that is not valid UTF-8")
            return
        self._emit(xml, rtp.timestamp, capture_time_ns)
