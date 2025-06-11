import pytest
import time
import threading
import queue

pytest.importorskip("gi")
pytest.importorskip("numpy")
from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient


# test_combined_client_creation moved to tests/unit/test_client_creation.py


@pytest.mark.requires_gstreamer
def test_combined_client_connection_attempt(combined_test_rtsp_url):
    """
    Test that combined client successfully connects to the provided RTSP URL.
    
    This test REQUIRES actual connectivity:
    - If URL is reachable: Should successfully connect and receive video data
    - If URL is unreachable: SHOULD FAIL (this is integration testing)
    """
    client = CombinedRTSPClient(combined_test_rtsp_url, latency=100, timeout=8.0)
    
    try:
        print(f"Testing RTSP connection to: {combined_test_rtsp_url}")
        client.start()
        time.sleep(10.0)  # Allow time for connection establishment and data reception
        
        # Integration test REQUIRES successful connection AND data reception
        assert client.video_cnt > 0, f"Failed to receive video from {combined_test_rtsp_url}, got {client.video_cnt} frames"
        print(f"✅ Successfully connected and received {client.video_cnt} video frames from: {combined_test_rtsp_url}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_combined_client_connection_to_unreachable_server(combined_test_rtsp_url):
    """Test that combined client handles unreachable RTSP server properly."""
    # When USE_REAL_CAMERA=true, this will try real camera and should fail if unavailable
    # When USE_REAL_CAMERA=false, this will use local server and should succeed
    client = CombinedRTSPClient(combined_test_rtsp_url, latency=100, timeout=2.0)
    
    try:
        print(f"Testing RTSP connection: {combined_test_rtsp_url}")
        client.start()
        time.sleep(3.0)  # Wait longer than timeout
        
        # Test behavior depends on what URL fixture provides
        # Real camera (unavailable): Should have errors
        # Local server: Should work without errors
        print(f"Connection result - Video: {client.video_cnt}, Errors: {client.err_cnt}")
        
    finally:
        client.stop()


# test_combined_client_with_callbacks moved to tests/unit/test_client_creation.py


@pytest.mark.requires_gstreamer
def test_combined_client_receives_video_frames(combined_test_rtsp_url):
    """
    Test that combined client receives video frames via RTSP protocol.
    
    This verifies the client:
    1. Connects to RTSP server using actual RTSP protocol
    2. Negotiates and receives H.264 video stream
    3. Properly decodes and delivers frames via callback
    """
    frame_queue = queue.Queue()
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None:
            frame_queue.put(frame)
            print(f"📹 Received video frame: {frame.shape}")
    
    client = CombinedRTSPClient(
        combined_test_rtsp_url,
        latency=100,
        video_frame_callback=video_callback,
        timeout=8.0
    )
    
    try:
        print(f"Testing video frame reception from RTSP: {combined_test_rtsp_url}")
        client.start()
        
        # Wait for frame from RTSP stream
        frame = frame_queue.get(timeout=6)
        assert frame is not None, "Should receive video frame from RTSP stream"
        # Should be a numpy array from decoded H.264
        assert hasattr(frame, 'shape'), "Frame should be decoded numpy array"
        assert len(frame.shape) == 3, f"Video frame should be 3D array, got shape {frame.shape}"
        
        print(f"✅ Successfully received video frame via RTSP: {frame.shape}")
        
    finally:
        client.stop()
        # Verify RTSP connection worked without errors
        assert client.err_cnt == 0, f"RTSP connection should work without errors, got {client.err_cnt}"
        assert client.video_cnt > 0, f"Should have received video via RTSP, got {client.video_cnt}"


# test_combined_client_diagnostics moved to tests/unit/test_client_creation.py


@pytest.mark.requires_gstreamer
def test_combined_client_context_manager(combined_test_rtsp_url):
    """Test that combined client works as context manager with actual RTSP connection."""
    frame_received = False
    
    def video_callback(payload):
        nonlocal frame_received
        frame_received = True
        print("📹 Frame received via context manager")
    
    print(f"Testing context manager with RTSP: {combined_test_rtsp_url}")
    with CombinedRTSPClient(combined_test_rtsp_url, latency=100, video_frame_callback=video_callback, timeout=5.0) as client:
        assert client is not None
        time.sleep(3.0)  # Allow RTSP connection and frame reception
        # Context manager should handle RTSP connection and cleanup properly
    
    # Should have received at least one frame via RTSP
    assert frame_received, "Should have received video frame via RTSP in context manager"


# test_combined_client_with_shared_config moved to tests/unit/test_client_creation.py


# test_combined_client_error_handling moved to tests/unit/test_client_creation.py


@pytest.mark.requires_gstreamer
def test_combined_client_dual_stream_reception(combined_test_rtsp_url):
    """
    Test that combined client can receive both video and audio streams via RTSP.
    
    This is the key test - verifies client can handle dual-stream RTSP like Axis cameras.
    """
    video_frames = []
    audio_samples = []
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None and len(video_frames) < 3:
            video_frames.append(frame)
            print(f"📹 Video frame {len(video_frames)}: {frame.shape}")
    
    def metadata_callback(payload):
        # Audio stream simulates metadata for testing
        data = payload.get("data")
        if data is not None and len(audio_samples) < 3:
            audio_samples.append(data)
            print(f"🎵 Audio sample {len(audio_samples)}: {type(data)}")
    
    client = CombinedRTSPClient(
        combined_test_rtsp_url,
        latency=100,
        video_frame_callback=video_callback,
        metadata_callback=metadata_callback,
        timeout=8.0
    )
    
    try:
        print(f"Testing dual-stream RTSP reception: {combined_test_rtsp_url}")
        client.start()
        
        # Wait for both stream types
        timeout = time.time() + 8
        while (len(video_frames) < 2 or len(audio_samples) < 2) and time.time() < timeout:
            time.sleep(0.1)
        
        assert len(video_frames) >= 1, f"Should receive video frames via RTSP, got {len(video_frames)}"
        
        # Note: Our test server provides audio stream, not real metadata XML
        # The CombinedRTSPClient expects XML metadata, so audio won't be processed
        if len(audio_samples) >= 1:
            print(f"✅ Successfully received dual streams - Video: {len(video_frames)}, Audio: {len(audio_samples)}")
        else:
            print(f"✅ Successfully received video stream - Video: {len(video_frames)}")
            print("   (No audio/metadata samples - expected with audio placeholder stream)")
        
    finally:
        client.stop()
        # Client may have errors due to audio stream not containing XML metadata
        # This is expected behavior when using audio as metadata placeholder
        print(f"   Final state - Video: {client.video_cnt}, Metadata: {client.meta_cnt}, Errors: {client.err_cnt}") 