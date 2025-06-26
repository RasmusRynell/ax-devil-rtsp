"""
Unit test for video processing function edge case.

Tests the video processing function behavior when latest_rtp_data is None.
This edge case is difficult to trigger reliably in integration tests.
"""

import numpy as np
from unittest.mock import patch, MagicMock
from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient


def test_video_processing_function_with_none_rtp_data():
    """
    Test that video processing function works correctly when latest_rtp_data is None.
    
    This edge case is hard to trigger reliably in integration tests since RTP data
    is usually available once the stream starts.
    """
    processing_calls = []
    
    def mock_processing_fn(payload, shared_config):
        processing_calls.append(payload)
        return payload['data']
    
    with patch('gi.repository.Gst') as mock_gst, \
         patch('gi.repository.GLib') as mock_glib:
        
        mock_gst.init.return_value = None
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_glib.MainLoop.return_value = MagicMock()
        
        client = CombinedRTSPClient(
            rtsp_url="rtsp://test.example.com/stream",
            video_processing_fn=mock_processing_fn,
            shared_config={}
        )
        
        # Simulate state where no RTP extension data has been received yet
        client.latest_rtp_data = None
        
        test_frame = np.ones((240, 320, 3), dtype=np.uint8)
        payload = {
            'data': test_frame,
            'latest_rtp_data': None,
        }
        
        # Call processing function
        processed_frame = client.video_proc_fn(payload, client.shared_cfg)
        
        assert len(processing_calls) == 1, "Processing function should be called"
        call_payload = processing_calls[0]
        assert call_payload['latest_rtp_data'] is None, "RTP data should be None when not available"
        assert np.array_equal(call_payload['data'], test_frame), "Frame data should be preserved" 