"""
Integration test for video data flow with RtspVideoDataRetriever.
"""

import pytest
import time
import threading
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever


def test_video_data_flow(rtsp_url):
    """
    Test that RtspVideoDataRetriever receives video frames and manages resources.
    """
    received_frames = []
    errors = []
    
    def on_video_data(payload):
        received_frames.append(payload)
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspVideoDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_error=on_error,
        connection_timeout=10
    )
    
    # Test basic lifecycle
    assert not retriever.is_running
    
    retriever.start()
    assert retriever.is_running
    
    # Wait for frames (give enough time for connection and initial frames)
    time.sleep(5)
    
    retriever.stop()
    assert not retriever.is_running
    
    # Verify we received at least one video frame
    assert len(received_frames) > 0, "Should have received at least one video frame"
    
    # Verify frame structure
    frame = received_frames[0]
    assert "kind" in frame
    assert frame["kind"] == "video"
    
    # Should not have errors in normal operation
    assert len(errors) == 0, f"Unexpected errors: {errors}"


 