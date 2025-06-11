"""
Integration tests for enhanced RTSP functionality.
Tests use fixtures to respect USE_REAL_CAMERA setting - will FAIL if real camera unavailable.
"""

import pytest
import time
import queue

pytest.importorskip("gi")
pytest.importorskip("numpy")
from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient


@pytest.mark.requires_gstreamer
def test_combined_client_multistream_capability(combined_test_rtsp_url):
    """Test CombinedRTSPClient with multi-stream capability via provided RTSP URL."""
    video_queue = queue.Queue()
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None:
            video_queue.put(frame)
    
    client = CombinedRTSPClient(
        combined_test_rtsp_url,
        latency=100,
        video_frame_callback=video_callback,
        timeout=8.0
    )
    
    try:
        client.start()
        
        # Wait for video frames - will fail if can't connect to provided URL
        print("Waiting for video frame...")
        video_frame = video_queue.get(timeout=6)
        assert video_frame is not None
        print(f"✅ Received video frame with shape: {video_frame.shape}")
        
        time.sleep(2)  # Let it run a bit more
        
        assert client.video_cnt > 0, f"No video frames received: {client.video_cnt}"
        print(f"📊 Client stats - Video: {client.video_cnt}, Meta: {client.meta_cnt}, XML: {client.xml_cnt}, Errors: {client.err_cnt}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer  
def test_combined_client_timeout_behavior_with_real_connection(combined_test_rtsp_url):
    """Test CombinedRTSPClient timeout behavior with the provided RTSP URL."""
    client = CombinedRTSPClient(combined_test_rtsp_url, latency=100, timeout=4.0)
    
    try:
        client.start()
        time.sleep(5.0)  # Wait longer than timeout
        
        # Should connect to provided URL or fail appropriately
        # If using real camera with USE_REAL_CAMERA=true, this will fail if camera unavailable
        assert client.video_cnt > 0, "Should have received video frames from provided URL"
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_multistream_functionality_via_fixtures(combined_test_rtsp_url):
    """Test multi-stream functionality using the provided RTSP URL from fixtures."""
    video_frames = []
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None and len(video_frames) < 5:  # Collect a few frames
            video_frames.append(frame)
    
    client = CombinedRTSPClient(
        combined_test_rtsp_url,
        latency=100,
        video_frame_callback=video_callback,
        timeout=6.0
    )
    
    try:
        client.start()
        
        # Wait to collect some frames - will fail if URL is unreachable
        timeout = time.time() + 5
        while len(video_frames) < 3 and time.time() < timeout:
            time.sleep(0.1)
            
        # Verify we got frames from provided URL
        assert len(video_frames) >= 1, f"Should have received at least one video frame from {combined_test_rtsp_url}"
        
        for i, frame in enumerate(video_frames):
            assert len(frame.shape) == 3, f"Frame {i} should be 3D array, got shape: {frame.shape}"
            print(f"✅ Frame {i}: {frame.shape}")
            
    finally:
        client.stop()


if __name__ == "__main__":
    # Manual test - would need proper fixture setup
    print("Integration tests require pytest fixture setup") 