"""
Unit tests for client creation and configuration.

These tests verify object creation, callback setup, and configuration
without requiring network connections or hardware.
"""

import pytest
import queue

pytest.importorskip("gi")
pytest.importorskip("numpy")

from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient
from ax_devil_rtsp.examples.video_gstreamer import VideoGStreamerClient  
from ax_devil_rtsp.examples.metadata_gstreamer import SceneMetadataClient


@pytest.mark.requires_gstreamer
def test_combined_client_creation():
    """Test that combined client can be created without errors."""
    dummy_url = "rtsp://dummy.example.com/test"
    client = CombinedRTSPClient(dummy_url, latency=100, timeout=5.0)
    assert client is not None
    assert client.pipeline is not None
    assert client.rtsp_url == dummy_url
    assert client.latency == 100
    assert client.timeout == 5.0


@pytest.mark.requires_gstreamer
def test_combined_client_with_callbacks():
    """Test creating combined client with all callback types."""
    dummy_url = "rtsp://dummy.example.com/test"
    video_queue = queue.Queue()
    metadata_queue = queue.Queue()
    session_queue = queue.Queue()
    error_queue = queue.Queue()
    
    def video_callback(payload):
        video_queue.put(payload)
    
    def metadata_callback(payload):
        metadata_queue.put(payload)
    
    def session_callback(payload):
        session_queue.put(payload)
    
    def error_callback(payload):
        error_queue.put(payload)
    
    client = CombinedRTSPClient(
        dummy_url,
        latency=100,
        video_frame_callback=video_callback,
        metadata_callback=metadata_callback,
        session_metadata_callback=session_callback,
        error_callback=error_callback,
        timeout=5.0
    )
    
    assert client is not None
    assert client.video_frame_cb == video_callback
    assert client.metadata_cb == metadata_callback
    assert client.session_md_cb == session_callback
    assert client.error_cb == error_callback


@pytest.mark.requires_gstreamer
def test_combined_client_diagnostics():
    """Test that combined client provides diagnostics."""
    dummy_url = "rtsp://dummy.example.com/test"
    client = CombinedRTSPClient(dummy_url, latency=100, timeout=5.0)
    
    # Check initial diagnostics
    video_diag = client._video_diag()
    assert isinstance(video_diag, dict)
    assert 'video_sample_count' in video_diag
    assert 'uptime' in video_diag
    
    meta_diag = client._meta_diag()
    assert isinstance(meta_diag, dict)
    assert 'metadata_sample_count' in meta_diag
    assert 'xml_message_count' in meta_diag


@pytest.mark.requires_gstreamer
def test_combined_client_with_shared_config():
    """Test combined client with shared configuration."""
    dummy_url = "rtsp://dummy.example.com/test"
    shared_config = {"test_key": "test_value"}
    
    client = CombinedRTSPClient(
        dummy_url,
        latency=100,
        shared_config=shared_config,
        timeout=5.0
    )
    
    assert client.shared_cfg == shared_config
    assert client.shared_cfg["test_key"] == "test_value"


@pytest.mark.requires_gstreamer 
def test_combined_client_error_handling():
    """Test combined client error handling setup."""
    dummy_url = "rtsp://dummy.example.com/test"
    error_queue = queue.Queue()
    
    def error_callback(payload):
        error_queue.put(payload)
    
    client = CombinedRTSPClient(
        dummy_url,
        latency=100,
        error_callback=error_callback,
        timeout=5.0
    )
    
    assert client.error_cb == error_callback
    assert client.err_cnt == 0  # Initial error count


@pytest.mark.requires_gstreamer
def test_video_client_creation():
    """Test that video client can be created without errors."""
    dummy_url = "rtsp://dummy.example.com/test"
    client = VideoGStreamerClient(dummy_url, latency=100)
    assert client is not None
    assert client.pipeline is not None


@pytest.mark.requires_gstreamer
def test_metadata_client_creation():
    """Test that metadata client can be created without errors."""
    dummy_url = "rtsp://dummy.example.com/test"
    client = SceneMetadataClient(dummy_url, latency=100, timeout=5.0)
    assert client is not None
    assert client.pipeline is not None


@pytest.mark.requires_gstreamer  
def test_video_client_invalid_rtsp_url():
    """Test video client with malformed RTSP URL (unit test - no network connection)."""
    import threading
    import time
    
    invalid_url = "not-an-rtsp-url"
    
    client = VideoGStreamerClient(invalid_url, latency=100, timeout=2.0)
    
    thread = threading.Thread(target=client.start)
    thread.daemon = True
    thread.start()
    
    try:
        print(f"Testing invalid RTSP URL: {invalid_url}")
        time.sleep(3.0)
        
        # Should have errors from invalid URL
        assert client.error_count > 0, f"Should have URL parsing errors, got {client.error_count}"
        print(f"✅ Properly rejected invalid URL - Errors: {client.error_count}")
        
    finally:
        client.stop() 
        thread.join(timeout=3)


@pytest.mark.requires_gstreamer
def test_combined_client_connection_to_unreachable_server():
    """Test that combined client properly handles unreachable RTSP server (unit test)."""
    import threading
    import time
    
    # Use reserved IP address that is guaranteed to be unreachable
    # 192.0.2.0/24 is reserved for documentation and testing (RFC 3330)
    unreachable_url = "rtsp://192.0.2.1:12345/nonexistent"
    
    client = CombinedRTSPClient(unreachable_url, latency=100, timeout=2.0)
    
    thread = threading.Thread(target=client.start)
    thread.daemon = True  
    thread.start()
    
    try:
        print(f"Testing unreachable RTSP server: {unreachable_url}")
        time.sleep(4.0)  # Wait longer than timeout to ensure failure
        
        # Should have connection errors from unreachable server
        assert client.err_cnt > 0, f"Should have connection errors to unreachable server, got {client.err_cnt}"
        
        # Should not have received any video frames
        assert client.video_cnt == 0, f"Should not receive video from unreachable server, got {client.video_cnt}"
        
        print(f"✅ Properly failed to connect to unreachable server - Errors: {client.err_cnt}, Video: {client.video_cnt}")
        
    finally:
        client.stop()
        thread.join(timeout=3) 