import pytest
pytest.importorskip("gi")
pytest.importorskip("cv2")
pytest.importorskip("numpy")
from ax_devil_rtsp.examples.video_gstreamer import VideoGStreamerClient
import threading
import queue
import numpy as np
import time

@pytest.mark.requires_gstreamer
def test_video_client_creation(rtsp_url):
    """Test that video client can be created without errors."""
    client = VideoGStreamerClient(rtsp_url, latency=100)
    assert client is not None
    assert client.pipeline is not None

@pytest.mark.requires_gstreamer
def test_video_client_receives_frames(gst_rtsp_server):
    """Test that client can receive video frames from camera."""
    frame_queue = queue.Queue()
    
    def callback(frame, rtp_info):
        if frame is not None:  # Only queue complete frames
            frame_queue.put((frame, rtp_info))
    
    client = VideoGStreamerClient(gst_rtsp_server,
                                  latency=100,
                                  frame_handler_callback=callback)
    
    # Start client in separate thread
    thread = threading.Thread(target=client.start)
    thread.daemon = True
    thread.start()
    
    try:
        # Wait for frame with timeout and retries
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                frame, rtp_info = frame_queue.get(timeout=5)
                assert frame is not None
                assert isinstance(frame, np.ndarray)
                if rtp_info is not None:  # If we get RTP info, test passes
                    assert 'human_time' in rtp_info
                    break
            except queue.Empty:
                if attempt == max_attempts - 1:
                    pytest.fail("Timeout waiting for video frame")
                continue
    finally:
        client.stop()
        thread.join(timeout=5)
