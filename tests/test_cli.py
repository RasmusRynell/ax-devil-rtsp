"""Local installation diagnostics without a GPU or camera."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Literal

import av
import pytest
from av.codec.hwaccel import HWAccel
from click.testing import CliRunner

from ax_devil_rtsp.cli import cli


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
