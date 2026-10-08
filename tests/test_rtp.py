"""RTP parsing, capture times and reassembly of access units and metadata documents."""

from __future__ import annotations

import struct

from ax_devil_rtsp.rtp import (
    START_CODE,
    AccessUnitAssembler,
    MetadataAssembler,
    ntp_to_unix_ns,
    parse_rtp,
    sdp_parameter_sets,
)

from fake_camera import rtp_packet

SPS = bytes((0x67, 1, 2))
PPS = bytes((0x68, 3))
IDR = bytes((0x65,)) + bytes(range(10))
SLICE = bytes((0x41, 9, 9))


def stap_a(*nals: bytes) -> bytes:
    return bytes((0x18,)) + b"".join(struct.pack("!H", len(nal)) + nal for nal in nals)


def fu_a(nal: bytes, *cuts: int) -> list[bytes]:
    edges = [1, *cuts, len(nal)]
    payloads = []
    for index in range(len(edges) - 1):
        flags = (0x80 if index == 0 else 0) | (0x40 if index == len(edges) - 2 else 0)
        payloads.append(bytes(((nal[0] & 0xE0) | 28, flags | (nal[0] & 0x1F))) + nal[edges[index] : edges[index + 1]])
    return payloads


def collect_units(
    codec: str, packets: list[bytes], parameter_sets: bytes = b""
) -> list[tuple[bytes, int, int | None, bool]]:
    units: list[tuple[bytes, int, int | None, bool]] = []
    assembler = AccessUnitAssembler(codec, parameter_sets, lambda *unit: units.append(unit))
    for packet in packets:
        assembler.push(packet)
    return units


def test_ntp_to_unix_ns() -> None:
    assert ntp_to_unix_ns(2_208_988_800, 0) == 0
    assert ntp_to_unix_ns(2_208_988_801, 0x8000_0000) == 1_500_000_000
    assert ntp_to_unix_ns(0, 0) == ((1 << 32) - 2_208_988_800) * 1_000_000_000  # 2036-02-07, NTP era 1


def test_parse_rtp_skips_csrcs_extension_and_padding() -> None:
    header = struct.pack("!BBHII", 0x80 | 0x20 | 0x10 | 1, 0x80 | 96, 7, 1234, 1) + b"CSRC"
    extension = struct.pack("!HHIII", 0xABAC, 3, 2_208_988_810, 0, 0)
    packet = parse_rtp(header + extension + b"payload" + b"\x00\x00\x03")
    assert packet.marker and packet.sequence == 7 and packet.timestamp == 1234
    assert packet.capture_time_ns == 10_000_000_000
    assert bytes(packet.payload) == b"payload"


def test_h264_access_units_from_stap_a_fu_a_and_single_nal_packets() -> None:
    first = [stap_a(SPS, PPS), *fu_a(IDR, 4, 8)]
    packets = [
        rtp_packet(payload, i, 3000, i == len(first) - 1, 50 if i == 0 else None) for i, payload in enumerate(first)
    ]
    packets.append(rtp_packet(SLICE, 3, 6000, False))  # marker lost: the next timestamp ends this unit
    packets.append(rtp_packet(SLICE, 4, 9000, True))

    units = collect_units("h264", packets)

    assert units[0] == (START_CODE + SPS + START_CODE + PPS + START_CODE + IDR, 3000, 50_000_000_000, True)
    assert units[1:] == [(START_CODE + SLICE, 6000, None, False), (START_CODE + SLICE, 9000, None, False)]


def test_sdp_parameter_sets_are_prepended_to_the_first_access_unit_only() -> None:
    parameter_sets = sdp_parameter_sets("h264", {"sprop-parameter-sets": "ZwEC,aAM="})
    assert parameter_sets == START_CODE + SPS + START_CODE + PPS

    units = collect_units("h264", [rtp_packet(SLICE, 0, 0, True), rtp_packet(SLICE, 1, 3000, True)], parameter_sets)

    assert [unit[0] for unit in units] == [parameter_sets + START_CODE + SLICE, START_CODE + SLICE]


def test_h265_access_units_from_aggregation_and_fragmentation_packets() -> None:
    vps, sps, pps = bytes((0x40, 1, 7)), bytes((0x42, 1, 8)), bytes((0x44, 1, 9))
    idr = bytes((0x26, 0x01)) + bytes(range(12))  # IDR_W_RADL, type 19
    aggregation = bytes((0x60, 0x01)) + b"".join(struct.pack("!H", len(nal)) + nal for nal in (vps, sps, pps))
    fragments = [
        bytes((0x62, 0x01, 0x80 | 19)) + idr[2:8],
        bytes((0x62, 0x01, 0x40 | 19)) + idr[8:],
    ]
    packets = [rtp_packet(payload, i, 0, i == 2) for i, payload in enumerate([aggregation, *fragments])]

    units = collect_units("hevc", packets)

    assert units == [(b"".join(START_CODE + nal for nal in (vps, sps, pps, idr)), 0, None, True)]


def test_metadata_documents_are_reassembled_and_broken_ones_dropped() -> None:
    documents: list[tuple[str, int, int | None]] = []
    assembler = MetadataAssembler(lambda *document: documents.append(document))
    packets = [
        rtp_packet(b"<a>", 10, 900, False, 5),
        rtp_packet(b"</a>", 11, 900, True),
        rtp_packet(b"<lost", 12, 1800, False),
        rtp_packet(b"/>", 14, 1800, True),  # sequence 13 is missing
        rtp_packet(b"\xff", 15, 2700, True),  # not UTF-8
        rtp_packet("<b>å</b>".encode(), 16, 3600, True),
    ]
    for packet in packets:
        assembler.push(packet)

    assert documents == [("<a></a>", 900, 5_000_000_000), ("<b>å</b>", 3600, None)]
