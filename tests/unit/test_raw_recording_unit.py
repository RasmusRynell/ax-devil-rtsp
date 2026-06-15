from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from gi.repository import Gst

from ax_devil_rtsp.gstreamer import CombinedRTSPClient
from ax_devil_rtsp.recording import RawRecordingConfig
from ax_devil_rtsp.rtsp_data_retrievers import (
    RtspApplicationDataRetriever,
    RtspDataRetriever,
)


def test_raw_recording_config_prepares_parent_directory(tmp_path):
    output_path = tmp_path / "nested" / "recording.mp4"
    config = RawRecordingConfig.from_path(output_path)

    prepared_path = config.prepare_output_path()

    assert prepared_path == output_path
    assert output_path.parent.exists()


def test_raw_recording_config_rejects_existing_file_without_overwrite(tmp_path):
    output_path = tmp_path / "recording.mp4"
    output_path.write_bytes(b"existing")
    config = RawRecordingConfig.from_path(output_path)

    with pytest.raises(FileExistsError, match="already exists"):
        config.prepare_output_path()

    assert output_path.read_bytes() == b"existing"


def test_raw_recording_config_overwrites_existing_file(tmp_path):
    output_path = tmp_path / "recording.mp4"
    output_path.write_bytes(b"existing")
    config = RawRecordingConfig.from_path(output_path, overwrite=True)

    prepared_path = config.prepare_output_path()

    assert prepared_path == output_path
    assert not output_path.exists()


def test_raw_recording_config_requires_mp4_suffix(tmp_path):
    config = RawRecordingConfig.from_path(tmp_path / "recording.mkv")

    with pytest.raises(ValueError, match="MP4"):
        config.prepare_output_path()


def test_application_data_retriever_rejects_raw_recording(tmp_path):
    with pytest.raises(ValueError, match="requires a video stream"):
        RtspApplicationDataRetriever(
            rtsp_url="rtsp://test.url/stream",
            raw_recording=tmp_path / "recording.mp4",
        )


def test_raw_recording_enables_video_branch_without_frame_callback(tmp_path):
    output_path = tmp_path / "recording.mp4"
    retriever = RtspDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        raw_recording=RawRecordingConfig.from_path(output_path),
    )

    with patch("multiprocessing.Process") as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process.exitcode = None
        mock_process_class.return_value = mock_process

        with patch("multiprocessing.Queue"):
            retriever.start()

            process_args = mock_process_class.call_args.kwargs["args"]
            assert process_args[7] is True
            assert process_args[8] is False
            assert process_args[10] == RawRecordingConfig.from_path(output_path)

            mock_process.is_alive.return_value = False
            mock_process.exitcode = 0
            retriever.stop()


def test_recording_only_client_does_not_build_decoder_branch(tmp_path):
    client = CombinedRTSPClient(
        rtsp_url="rtsp://test.url/stream",
        raw_recording=RawRecordingConfig.from_path(tmp_path / "recording.mp4"),
    )

    try:
        assert client.video_branch_enabled is True
        assert client.decoded_video_branch_enabled is False
        assert client.pipeline.get_by_name("v_record_sink") is not None
        assert client.pipeline.get_by_name("v_dec") is None
        assert client.pipeline.get_by_name("v_sink") is None
    finally:
        client.pipeline.set_state(Gst.State.NULL)


def test_raw_recording_with_video_callback_builds_both_branches(tmp_path):
    client = CombinedRTSPClient(
        rtsp_url="rtsp://test.url/stream",
        video_frame_callback=lambda _frame: None,
        raw_recording=RawRecordingConfig.from_path(tmp_path / "recording.mp4"),
    )

    try:
        assert client.video_branch_enabled is True
        assert client.decoded_video_branch_enabled is True
        assert client.pipeline.get_by_name("v_record_sink") is not None
        assert client.pipeline.get_by_name("v_dec") is not None
        assert client.pipeline.get_by_name("v_sink") is not None
    finally:
        client.pipeline.set_state(Gst.State.NULL)
