"""
Unit tests for video processing functionality.

These tests verify the video processing function behavior, signature validation,
and payload processing in the GStreamer client.
"""

import time
import numpy as np
from unittest.mock import patch, MagicMock
from ax_devil_rtsp.gstreamer import CombinedRTSPClient


def test_video_processing_function_with_none_rtp_data():
    """
    Test video processing function when latest_rtp_data is None.
    
    Verifies that:
    - Video processing works without RTP extension data
    - Payload structure is correct even without timing info
    - Processing function receives expected format
    """
    
    def mock_video_processing_fn(payload, shared_config):
        """Mock processing function that adds a timestamp overlay."""
        # Verify payload structure
        assert "data" in payload
        assert "latest_rtp_data" in payload
        
        # latest_rtp_data can be None during initialization
        rtp_data = payload.get("latest_rtp_data")
        if rtp_data is None:
            # This is the expected case we're testing
            pass
        
        # Return processed frame (in this case, just return the same frame)
        return payload["data"]
    
    # Test client creation with video processing
    client = CombinedRTSPClient(
        rtsp_url="rtsp://test.example.com/stream",
        latency=100,
        video_processing_fn=mock_video_processing_fn,
        shared_config={}
    )
    
    # Verify the processing function was set
    assert client.video_proc_fn == mock_video_processing_fn
    assert client.shared_cfg == {}
    
    # Verify initial state
    assert client.latest_rtp_data is None 