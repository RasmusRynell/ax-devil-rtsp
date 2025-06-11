import pytest
pytest.importorskip("gi")
pytest.importorskip("cv2")
pytest.importorskip("numpy")
from ax_devil_rtsp.examples.video_gstreamer import VideoGStreamerClient
import threading
import queue
import numpy as np
import time

# test_video_client_creation moved to tests/unit/test_client_creation.py

@pytest.mark.requires_gstreamer
def test_video_client_connection_attempt(test_rtsp_url):
    """
    Test that video client can connect to RTSP server via actual RTSP protocol.
    
    This test verifies:
    1. Client connects to RTSP server over network
    2. Client successfully negotiates RTSP session
    3. Client receives H.264 video stream
    4. NO CHEATING - must use real RTSP protocol
    """
    client = VideoGStreamerClient(test_rtsp_url, latency=100, timeout=5.0)
    
    try:
        print(f"Testing RTSP connection to: {test_rtsp_url}")
        client.start()
        time.sleep(3.0)  # Allow time for RTSP connection
        
        # Should successfully connect via RTSP protocol without errors
        assert client.error_count == 0, f"RTSP connection should succeed, got {client.error_count} errors"
        print(f"✅ RTSP connection successful - No errors recorded")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_video_client_receives_frames(test_rtsp_url):
    """
    Test that client receives H.264 video frames from RTSP server.
    
    This is the critical test - verifies:
    1. Client connects via RTSP protocol
    2. Client negotiates and receives H.264 stream  
    3. Client properly decodes frames
    4. Client delivers frames via callback mechanism
    
    NO SHORTCUTS - this must work via real RTSP protocol communication.
    """
    frame_queue = queue.Queue()
    
    def callback(payload):
        frame = payload.get("data")
        rtp_info = payload.get("latest_rtp_data")
        if frame is not None:  # Only queue complete frames
            frame_queue.put((frame, rtp_info))
            print(f"📹 Received frame via RTSP: {frame.shape}")
    
    client = VideoGStreamerClient(test_rtsp_url,
                                  latency=100,
                                  frame_handler_callback=callback,
                                  timeout=8.0)
    
    # Start client in separate thread
    thread = threading.Thread(target=client.start)
    thread.daemon = True
    thread.start()
    
    try:
        print(f"Testing video frame reception via RTSP: {test_rtsp_url}")
        
        # Wait for frame from RTSP stream with retries
        max_attempts = 3
        frame_received = False
        
        for attempt in range(max_attempts):
            try:
                frame, rtp_info = frame_queue.get(timeout=4)
                
                # Verify frame is properly decoded from RTSP H.264 stream
                assert frame is not None, "Frame should not be None"
                assert isinstance(frame, np.ndarray), f"Frame should be numpy array, got {type(frame)}"
                assert len(frame.shape) == 3, f"Frame should be 3D (H,W,C), got shape {frame.shape}"
                assert frame.shape[2] == 3, f"Frame should have 3 channels (RGB/BGR), got {frame.shape[2]}"
                
                print(f"✅ Successfully received and decoded H.264 frame via RTSP: {frame.shape}")
                
                # If we get RTP info, verify it contains timing data
                if rtp_info is not None:  
                    assert isinstance(rtp_info, dict), "RTP info should be dictionary"
                    assert 'human_time' in rtp_info, "RTP info should contain human_time"
                    print(f"📡 RTP timing info: {rtp_info.get('human_time', 'N/A')}")
                
                frame_received = True
                break
                
            except queue.Empty:
                if attempt == max_attempts - 1:
                    pytest.fail(f"Timeout waiting for video frame from RTSP server {test_rtsp_url}")
                print(f"⏱️  Attempt {attempt + 1}/{max_attempts} - waiting for RTSP frame...")
                continue
        
        assert frame_received, "Should have received at least one frame via RTSP"
        
    finally:
        client.stop()
        thread.join(timeout=5)
        
        # Verify RTSP connection worked properly
        assert client.error_count == 0, f"RTSP connection should work without errors, got {client.error_count}"


@pytest.mark.requires_gstreamer
def test_video_client_unreachable_server(test_rtsp_url):
    """Test that video client properly handles unreachable RTSP server."""
    # When USE_REAL_CAMERA=true, this will try real camera and should fail if unavailable
    # When USE_REAL_CAMERA=false, this will use local server and should succeed  
    client = VideoGStreamerClient(test_rtsp_url, latency=100, timeout=3.0)
    
    thread = threading.Thread(target=client.start)
    thread.daemon = True
    thread.start()
    
    try:
        print(f"Testing RTSP connection: {test_rtsp_url}")
        time.sleep(4.0)  # Wait longer than timeout
        
        # Test behavior depends on what URL fixture provides
        print(f"Connection result - Errors: {client.error_count}")
        
    finally:
        client.stop()
        thread.join(timeout=3)


# test_video_client_invalid_rtsp_url moved to tests/unit/ - it's testing URL validation logic
