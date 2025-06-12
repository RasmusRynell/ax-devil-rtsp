"""
Unit tests for retriever lifecycle and robustness.

These tests verify that retrievers can be started and stopped cleanly without 
data callbacks, even when connections fail. They are robustness/lifecycle tests,
not integration tests, as they do not verify actual data flow.
"""

import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever, RtspApplicationDataRetriever


def test_video_retriever_lifecycle_no_callback():
    """
    Test that video retriever works without callbacks (robustness test).
    
    Verifies that the retriever can be started and stopped cleanly even when:
    - No data callbacks are provided
    - The RTSP URL is invalid/unreachable
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://invalid.url.test/stream",
        connection_timeout=5
    )
    
    # Should be able to start and stop without callback
    retriever.start()
    time.sleep(2)
    retriever.stop()
    
    assert not retriever.is_running


def test_metadata_retriever_lifecycle_no_callback():
    """
    Test that metadata retriever works without callbacks (robustness test).
    
    Verifies that the retriever can be started and stopped cleanly even when:
    - No data callbacks are provided  
    - The RTSP URL is invalid/unreachable
    """
    retriever = RtspApplicationDataRetriever(
        rtsp_url="rtsp://invalid.url.test/stream",
        connection_timeout=5
    )
    
    # Should be able to start and stop without callback
    retriever.start()
    time.sleep(2)
    retriever.stop()
    
    assert not retriever.is_running 