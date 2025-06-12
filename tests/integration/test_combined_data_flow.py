"""
Integration test for combined video and metadata data flow.
"""

import pytest
import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspDataRetriever


def test_combined_data_flow(rtsp_url):
    """
    Test that RtspDataRetriever can receive both video and metadata simultaneously.
    """
    received_video = []
    received_metadata = []
    errors = []
    
    def on_video_data(payload):
        received_video.append(payload)
    
    def on_application_data(payload):
        received_metadata.append(payload)
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_application_data=on_application_data,
        on_error=on_error,
        connection_timeout=10
    )
    
    # Test basic lifecycle
    assert not retriever.is_running
    
    retriever.start()
    assert retriever.is_running
    
    # Wait for both types of data
    time.sleep(6)
    
    retriever.stop()
    assert not retriever.is_running
    
    # Verify we received both video and metadata
    assert len(received_video) > 0, "Should have received at least one video frame"
    assert len(received_metadata) > 0, "Should have received at least one metadata frame"
    
    # Verify structures
    video_frame = received_video[0]
    assert "kind" in video_frame
    assert video_frame["kind"] == "video"
    
    metadata_frame = received_metadata[0]
    assert "kind" in metadata_frame
    assert metadata_frame["kind"] == "metadata"
    
    # Should not have errors in normal operation
    assert len(errors) == 0, f"Unexpected errors: {errors}" 