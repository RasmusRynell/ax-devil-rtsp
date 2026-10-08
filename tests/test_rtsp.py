"""RTSP URLs, authentication and SDP parsing."""

from __future__ import annotations

import pytest

from ax_devil_rtsp import SceneMetadata, StreamConfig, VideoOutput, build_axis_rtsp_url
from ax_devil_rtsp.rtsp import Media, RtspConnection, digest_response, parse_sdp


def test_digest_response_matches_rfc_2617_example() -> None:
    response = digest_response(
        "Mufasa",
        "Circle Of Life",
        "testrealm@host.com",
        "dcd98b7102dd2f0e8b11d0f600bfb0c093",
        "GET",
        "/dir/index.html",
        qop="auth",
        nc="00000001",
        cnonce="0a4f113b",
    )
    assert response == "6629fae49393a05397450978507c4ef1"


def test_parse_sdp_resolves_controls_against_the_base_url() -> None:
    sdp = "\r\n".join(
        [
            "v=0",
            "a=control:*",
            "m=video 0 RTP/AVP 96",
            "a=rtpmap:96 h264/90000",
            "a=fmtp:96 packetization-mode=1; sprop-parameter-sets=Z0IA,aM4=",
            "a=control:trackID=1",
            "m=application 0 RTP/AVP 98",
            "a=rtpmap:98 vnd.onvif.metadata/90000",
            "a=control:rtsp://camera/other/track",
        ]
    )
    aggregate, medias = parse_sdp(sdp, "rtsp://camera/media.amp/")

    assert aggregate == "rtsp://camera/media.amp/"
    assert medias == [
        Media(
            "video",
            "H264",
            {"packetization-mode": "1", "sprop-parameter-sets": "Z0IA,aM4="},
            "rtsp://camera/media.amp/trackID=1",
        ),
        Media("application", "VND.ONVIF.METADATA", {}, "rtsp://camera/other/track"),
    ]


def test_requests_use_the_supplied_url_without_credentials() -> None:
    connection = RtspConnection("rtsp://root:p%40ss@[::1]:8554/axis-media/media.amp?camera=2", timeout=1)
    assert connection.url == "rtsp://[::1]:8554/axis-media/media.amp?camera=2"
    with pytest.raises(ValueError):
        RtspConnection("http://camera/", timeout=1)


def test_axis_url_requests_exactly_the_configured_streams() -> None:
    both = StreamConfig(video=VideoOutput.RGBA, metadata=True)
    url = build_axis_rtsp_url("192.168.0.90", both, username="root", password="p@ss:word", resolution="640x360")
    assert url == (
        "rtsp://root:p%40ss%3Aword@192.168.0.90/axis-media/media.amp"
        "?camera=1&audio=0&resolution=640x360&onvifreplayext=1&analytics=polygon"
    )

    metadata_only = StreamConfig(video=None, metadata=True)
    assert build_axis_rtsp_url("fe80::1", metadata_only, port=8554, camera=2) == (
        "rtsp://[fe80::1]:8554/axis-media/media.amp?camera=2&audio=0&video=0&analytics=polygon"
    )

    video_only = StreamConfig(video=VideoOutput.ENCODED)
    assert build_axis_rtsp_url("cam", video_only, capture_time=False).endswith("media.amp?camera=1&audio=0")


def test_scene_metadata_utc_time() -> None:
    xml = '<tt:Frame UtcTime="2027-01-15T08:30:00.123456Z" Source="1">'
    assert SceneMetadata(xml, 0, None).utc_time_ns == 1_800_001_800_123_456_000
    assert SceneMetadata('<tt:Frame UtcTime="1970-01-01T00:00:01Z">', 0, None).utc_time_ns == 1_000_000_000
    assert SceneMetadata("<empty/>", 0, None).utc_time_ns is None
