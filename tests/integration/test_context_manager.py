"""
Integration test for context manager resource management.
"""

import pytest
import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever


def test_context_manager_resource_management(rtsp_url):
    """
    Test that retrievers work correctly as context managers and clean up resources.
    """
    received_frames = []
    
    def on_video_data(payload):
        received_frames.append(payload)
    
    retriever = RtspVideoDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        connection_timeout=10
    )
    
    # Initially not running
    assert not retriever.is_running
    
    # Use as context manager
    with retriever:
        # Should be running inside the context
        assert retriever.is_running
        
        # Wait for some data
        time.sleep(3)
    
    # Should be stopped after exiting context
    assert not retriever.is_running
    
    # Should have received some frames
    assert len(received_frames) > 0, "Should have received frames while in context"


# Moved test_context_manager_exception_handling to unit/test_context_manager.py 