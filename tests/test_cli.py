"""Local installation diagnostics without a GPU or camera."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any, Literal

import av
import pytest
from av.codec.hwaccel import HWAccel
from click.testing import CliRunner

from ax_devil_rtsp.cli import cli

from fake_camera import FakeCamera, sdp


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (True, "READY"),
        (False, "UNSUPPORTED"),
        (av.error.PermissionError(13, "GPU permission denied"), "UNAVAILABLE"),
    ],
)
def test_doctor_probes_each_decoder_without_software_fallback(
    outcome: bool | av.error.FFmpegError, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def create(codec: str, mode: str, *, hwaccel: HWAccel) -> SimpleNamespace:
        assert mode == "r" and not getattr(hwaccel, "allow_software_fallback", True)
        calls.append(codec)
        if not isinstance(outcome, bool):
            raise outcome
        return SimpleNamespace(is_hwaccel=outcome)

    monkeypatch.setattr("av.codec.hwaccel.hwdevices_available", lambda: ["cuda"])
    monkeypatch.setattr(av, "CodecContext", SimpleNamespace(create=create))

    result = CliRunner().invoke(cli, ["doctor"])

    assert result.exit_code == 0, result.output
    assert calls == ["h264", "hevc"]
    assert f"{expected:11} h264 --hwaccel cuda:" in result.output
    assert f"{expected:11} hevc --hwaccel cuda:" in result.output
    assert "device initialization only" in result.output
    if expected == "UNAVAILABLE":
        assert "GPU permission denied" in result.output


def test_doctor_without_hardware_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("av.codec.hwaccel.hwdevices_available", lambda: [])

    result = CliRunner().invoke(cli, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Compiled hardware backends: none" in result.output
    assert "READY" not in result.output


def test_doctor_missing_decoder_remains_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = av.Codec
    calls: list[str] = []

    def codec(name: str, mode: Literal["r", "w"]) -> av.Codec:
        if name == "h264":
            raise av.codec.codec.UnknownCodecError(name)
        return original(name, mode)

    def create(name: str, mode: str, *, hwaccel: HWAccel) -> SimpleNamespace:
        calls.append(name)
        return SimpleNamespace(is_hwaccel=False)

    monkeypatch.setattr(av, "Codec", codec)
    monkeypatch.setattr(av, "CodecContext", SimpleNamespace(create=create))
    monkeypatch.setattr("av.codec.hwaccel.hwdevices_available", lambda: ["cuda"])

    result = CliRunner().invoke(cli, ["doctor"])

    assert result.exit_code == 1
    assert "MISSING  h264 decoder" in result.output
    assert "reinstall PyAV" in result.output
    assert calls == ["hevc"]


def test_stream_rejects_tunnel_with_a_supplied_url() -> None:
    result = CliRunner().invoke(cli, ["stream", "--url", "rtsp://camera/", "--tunnel", "https"])

    assert result.exit_code == 2
    assert "put the scheme in --url" in result.output


@pytest.mark.parametrize(("transport", "port"), [("rtsp", 554), ("http", 80), ("https", 443)])
def test_stream_generated_url_reaches_camera(
    transport: Literal["rtsp", "http", "https"], port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = FakeCamera(sdp(None, metadata=True), [], username="root", password="p@ss", transport=transport)
    connect = socket.create_connection
    addresses: list[tuple[str, int]] = []

    def connect_locally(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        addresses.append(address)
        return connect(("127.0.0.1", camera.port), *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", connect_locally)
    options = [
        "stream",
        "-a",
        "camera.invalid",
        "-u",
        "root",
        "-p",
        "p@ss",
        "--video",
        "none",
        "--duration",
        "0",
        "--timeout",
        "2",
    ]
    if transport != "rtsp":
        options += ["--tunnel", transport]
    if transport == "https":
        options += ["--no-verify-tls"]
    try:
        result = CliRunner().invoke(cli, options)
    finally:
        camera.join()

    assert result.exit_code == 0, result.output
    assert addresses == [("camera.invalid", port)] * (1 if transport == "rtsp" else 2)
    assert "PLAY" in camera.requests
    assert (
        camera.request_uris[0]
        == "rtsp://camera.invalid/axis-media/media.amp?camera=1&audio=0&video=0&analytics=polygon"
    )
    assert "p@ss" not in result.output
    if transport != "rtsp":
        assert [method for method, _, _ in camera.http_requests] == ["GET", "POST"]
