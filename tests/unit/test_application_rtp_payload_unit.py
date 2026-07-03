"""Unit tests for application-data RTP payload extraction and reassembly.

These exercise the real GStreamer RTP parser (``GstRtp.RTPBuffer``) by wrapping
hand-built RTP packets in ``Gst.Buffer`` objects and pushing them through
``_on_new_application_data_sample``. This mirrors how the package extracts the
ONVIF metadata XML on a live stream.
"""

from __future__ import annotations

import gi

from ax_devil_rtsp.gstreamer.callbacks import CallbackHandlerMixin
from ax_devil_rtsp.gstreamer.diagnostics import DiagnosticMixin

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)


def _rtp_packet(
    payload: bytes,
    *,
    marker: bool = True,
    extension: bytes | None = None,
    padding_bytes: int = 0,
    sequence_number: int = 7,
    timestamp: int = 1234,
) -> bytes:
    first_byte = 0x80
    if extension is not None:
        first_byte |= 0x10
    if padding_bytes:
        first_byte |= 0x20

    second_byte = 96 | (0x80 if marker else 0)
    header = bytes([first_byte, second_byte])
    header += sequence_number.to_bytes(2, "big")
    header += timestamp.to_bytes(4, "big")
    header += (5678).to_bytes(4, "big")

    if extension is None:
        extension_header = b""
    else:
        assert len(extension) % 4 == 0
        extension_header = (0xABAC).to_bytes(2, "big")
        extension_header += (len(extension) // 4).to_bytes(2, "big")
        extension_header += extension

    padding = b""
    if padding_bytes:
        padding = b"\x00" * (padding_bytes - 1) + bytes([padding_bytes])

    return header + extension_header + payload + padding


class _CallbackHarness(CallbackHandlerMixin, DiagnosticMixin):
    def __init__(self) -> None:
        CallbackHandlerMixin.__init__(self)
        DiagnosticMixin.__init__(self)


class _FakeSink:
    def __init__(self, packet: bytes) -> None:
        self._sample = Gst.Sample.new(Gst.Buffer.new_wrapped(packet), None, None, None)

    def emit(self, signal_name: str) -> Gst.Sample:
        assert signal_name == "pull-sample"
        return self._sample


def _push_application_packet(client: _CallbackHarness, packet: bytes) -> None:
    client._on_new_application_data_sample(_FakeSink(packet))


def test_application_payload_skips_rtp_header_extension() -> None:
    received = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    xml = b"<tt:MetadataStream></tt:MetadataStream>"

    # Extension data contains '<' bytes that must never leak into the XML.
    _push_application_packet(client, _rtp_packet(xml, extension=b"<<<<"))

    assert [payload["data"] for payload in received] == [xml.decode()]
    assert received[0]["diagnostics"]["xml_prefix_bytes_discarded"] == 0


def test_application_payload_removes_padding() -> None:
    received = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    xml = b"<tt:MetadataStream></tt:MetadataStream>"

    _push_application_packet(client, _rtp_packet(xml, padding_bytes=4))

    assert [payload["data"] for payload in received] == [xml.decode()]


def test_application_payload_buffers_until_marker() -> None:
    received = []
    client = _CallbackHarness()
    client.application_data_cb = received.append

    _push_application_packet(
        client, _rtp_packet(b"<tt:Metadata", marker=False, sequence_number=10)
    )
    assert received == []

    _push_application_packet(
        client, _rtp_packet(b"Stream />", marker=True, sequence_number=11)
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]


def test_application_payload_reports_rtp_sequence_gap_drop_diagnostics() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client, _rtp_packet(b"<tt:Metadata", marker=False, sequence_number=10)
    )
    _push_application_packet(
        client, _rtp_packet(b"Stream />", marker=True, sequence_number=12)
    )

    assert received == []
    assert errors
    diagnostics = errors[0]["diagnostics"]
    drop = diagnostics["application_rtp_last_drop"]
    assert diagnostics["application_rtp_sequence_gap_count"] == 1
    assert drop["reason"] == "same_timestamp_sequence_gap"
    assert drop["expected_sequence"] == 11
    assert drop["received_sequence"] == 12
    assert drop["missing_packets"] == 1


def test_application_payload_drops_same_timestamp_sequence_gap() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(
            b'<tt:MetadataStream><tt:Frame><tt:BoundingBox left="0" top',
            marker=False,
            sequence_number=20,
            timestamp=555,
        ),
    )
    _push_application_packet(
        client,
        _rtp_packet(
            b"bd:Bottoms /></tt:Frame></tt:MetadataStream>",
            marker=True,
            sequence_number=22,
            timestamp=555,
        ),
    )

    assert received == []
    assert errors
    assert errors[0]["error_type"] == "Application RTP Loss"
    assert errors[0]["diagnostics"]["application_rtp_sequence_gap_count"] == 1


def test_application_payload_drops_mid_document_start_after_sequence_gap() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream />",
            marker=True,
            sequence_number=100,
            timestamp=1000,
        ),
    )
    _push_application_packet(
        client,
        _rtp_packet(
            b"<bd:Bottoms />",
            marker=True,
            sequence_number=103,
            timestamp=2000,
        ),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "Application RTP Loss"
    drop = errors[0]["diagnostics"]["application_rtp_last_drop"]
    assert drop["reason"] == "sequence_gap_before_document_start"
    assert drop["expected_sequence"] == 101
    assert drop["received_sequence"] == 103


def test_application_payload_drops_metadata_stream_close_after_sequence_gap() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream />",
            marker=True,
            sequence_number=200,
            timestamp=1000,
        ),
    )
    _push_application_packet(
        client,
        _rtp_packet(
            b"</tt:MetadataStream>",
            marker=True,
            sequence_number=203,
            timestamp=2000,
        ),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "Application RTP Loss"
    drop = errors[0]["diagnostics"]["application_rtp_last_drop"]
    assert drop["reason"] == "sequence_gap_before_document_start"
    assert drop["expected_sequence"] == 201
    assert drop["received_sequence"] == 203


def test_application_payload_resyncs_on_timestamp_change_before_marker() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream><tt:Frame>",
            marker=False,
            sequence_number=30,
            timestamp=1000,
        ),
    )
    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream />",
            marker=True,
            sequence_number=31,
            timestamp=2000,
        ),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert errors
    assert errors[0]["error_type"] == "Application RTP Loss"
    drop = errors[0]["diagnostics"]["application_rtp_last_drop"]
    assert drop["reason"] == "timestamp_changed_before_marker"
    assert drop["previous_timestamp"] == 1000
    assert drop["current_timestamp"] == 2000


def test_application_payload_resyncs_after_sequence_gap_timestamp_change() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream><tt:Frame>",
            marker=False,
            sequence_number=40,
            timestamp=3000,
        ),
    )
    _push_application_packet(
        client,
        _rtp_packet(
            b"<tt:MetadataStream />",
            marker=True,
            sequence_number=42,
            timestamp=4000,
        ),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert errors
    drop = errors[0]["diagnostics"]["application_rtp_last_drop"]
    assert drop["reason"] == "timestamp_changed_after_sequence_gap"
    assert drop["expected_sequence"] == 41
    assert drop["received_sequence"] == 42


def test_application_payload_accepts_sequence_wraparound() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(b"<tt:Metadata", marker=False, sequence_number=65535),
    )
    _push_application_packet(
        client,
        _rtp_packet(b"Stream />", marker=True, sequence_number=0),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert errors == []
    assert received[0]["diagnostics"]["application_rtp_sequence_gap_count"] == 0


def test_application_payload_recovers_after_corrupt_drop() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(
        client,
        _rtp_packet(b"<tt:Metadata", marker=False, sequence_number=50),
    )
    _push_application_packet(
        client,
        _rtp_packet(b"Stream />", marker=True, sequence_number=52),
    )
    _push_application_packet(
        client,
        _rtp_packet(b"<tt:MetadataStream />", marker=True, sequence_number=53),
    )

    assert [payload["data"] for payload in received] == ["<tt:MetadataStream />"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "Application RTP Loss"


def test_application_payload_reports_missing_xml_start() -> None:
    received = []
    errors = []
    client = _CallbackHarness()
    client.application_data_cb = received.append
    client.error_cb = errors.append

    _push_application_packet(client, _rtp_packet(b"no-angle-bracket-here"))

    assert received == []
    assert errors
    assert errors[0]["error_type"] == "XML Parse"
