"""
Integration test for metadata (scene metadata) data flow with RtspApplicationDataRetriever.
"""

import pytest
import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspApplicationDataRetriever


def test_metadata_data_flow(rtsp_url):
    """
    Test that RtspApplicationDataRetriever receives scene metadata and manages resources.
    """
    received_metadata = []
    errors = []
    
    def on_application_data(payload):
        received_metadata.append(payload)
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspApplicationDataRetriever(
        rtsp_url=rtsp_url,
        on_application_data=on_application_data,
        on_error=on_error,
        connection_timeout=10
    )
    
    # Test basic lifecycle
    assert not retriever.is_running
    
    retriever.start()
    assert retriever.is_running
    
    # Wait for metadata (give enough time for connection and initial metadata)
    time.sleep(5)
    
    retriever.stop()
    assert not retriever.is_running
    
    # Verify we received at least one metadata frame
    assert len(received_metadata) > 0, "Should have received at least one metadata frame"
    
    # Verify metadata structure
    metadata = received_metadata[0]
    assert "kind" in metadata
    assert metadata["kind"] == "metadata"
    
    # Should not have errors in normal operation
    assert len(errors) == 0, f"Unexpected errors: {errors}"


 