import pytest
import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever

def test_connection_error_handling():
    """
    Test that error callback is invoked and resources are cleaned up on connection failure.
    """
    errors = []
    received_frames = []
    def on_video_data(payload):
        received_frames.append(payload)
    def on_error(payload):
        errors.append(payload)
    # Use an invalid RTSP URL to trigger connection error
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://invalid.nonexistent.server.test/stream",
        on_video_data=on_video_data,
        on_error=on_error,
        connection_timeout=5
    )
    # Test basic lifecycle
    assert not retriever.is_running
    retriever.start()
    assert retriever.is_running
    # Wait for connection timeout and error
    time.sleep(8)
    retriever.stop()
    assert not retriever.is_running
    # Should have received error(s), no video frames
    assert len(errors) > 0, "Should have received at least one error"
    assert len(received_frames) == 0, "Should not have received video frames from invalid URL"
    # Verify error structure
    error = errors[0]
    assert "kind" in error
    assert error["kind"] == "error"

def test_multiple_start_stop_cycles():
    """
    Test that retriever can handle multiple start/stop cycles gracefully.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://invalid.test.server/stream",
        connection_timeout=3
    )
    # Multiple start/stop cycles should not cause issues
    for i in range(3):
        assert not retriever.is_running
        retriever.start()
        assert retriever.is_running
        time.sleep(1)
        retriever.stop()
        assert not retriever.is_running 