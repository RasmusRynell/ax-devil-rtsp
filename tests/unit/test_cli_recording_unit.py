from __future__ import annotations

from click.testing import CliRunner

from ax_devil_rtsp.cli import cli


def test_cli_record_raw_existing_file_exits_nonzero(tmp_path):
    output_path = tmp_path / "existing.mp4"
    output_path.write_bytes(b"existing")

    result = CliRunner().invoke(
        cli,
        [
            "--url",
            "rtsp://example.invalid/stream",
            "--only-video",
            "--record-raw",
            str(output_path),
            "--log-level",
            "ERROR",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_cli_record_raw_invalid_suffix_exits_nonzero(tmp_path):
    output_path = tmp_path / "recording.mkv"

    result = CliRunner().invoke(
        cli,
        [
            "--url",
            "rtsp://example.invalid/stream",
            "--only-video",
            "--record-raw",
            str(output_path),
            "--log-level",
            "ERROR",
        ],
    )

    assert result.exit_code != 0
    assert "MP4" in result.output
