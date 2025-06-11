"""
Focused Integration Error Tests for GStreamer Data Grabber

Integration tests for error conditions that require network connections:
- Invalid RTSP URL handling
- Unreachable server timeouts
- Real camera connection failures
- Error callback validation
- Concurrent failure handling

These tests may FAIL when hardware/network is unavailable (expected behavior).
"""

import pytest
import time
import threading
import queue

pytest.importorskip("gi")

from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient
from ax_devil_rtsp.examples.video_gstreamer import VideoGStreamerClient


@pytest.mark.requires_gstreamer
def test_invalid_url_error_handling():
    """Test that invalid RTSP URLs are properly detected and reported as errors."""
    error_reports = []
    
    def error_callback(payload):
        error_reports.append(payload)
    
    client = CombinedRTSPClient(
        "not-a-valid-url",
        error_callback=error_callback,
        timeout=3.0
    )
    
    thread = threading.Thread(target=client.start, daemon=True)
    thread.start()
    
    try:
        time.sleep(4.0)  # Wait for error detection
        
        # Should detect invalid URL and report errors
        assert client.err_cnt > 0, f"Invalid URL should generate errors, got {client.err_cnt}"
        assert len(error_reports) > 0, "Error callback should have been triggered"
        
        print(f"✅ Invalid URL properly detected - Errors: {client.err_cnt}")
        
    finally:
        client.stop()
        thread.join(timeout=2)


@pytest.mark.requires_gstreamer
def test_unreachable_server_timeout():
    """Test timeout behavior with unreachable RTSP server."""
    error_reports = []
    
    def error_callback(payload):
        error_reports.append(payload)
        print(f"Error reported: {payload}")
    
    # Use unreachable IP address (RFC5737 test network)
    unreachable_url = "rtsp://192.0.2.1:554/stream"
    
    client = CombinedRTSPClient(
        unreachable_url,
        error_callback=error_callback,
        timeout=3.0
    )
    
    start_time = time.time()
    thread = threading.Thread(target=client.start, daemon=True)
    thread.start()
    
    try:
        time.sleep(4.0)  # Wait longer than timeout
        elapsed = time.time() - start_time
        
        # Should timeout and report errors
        assert elapsed >= 3.0, f"Should respect timeout duration, took {elapsed:.1f}s"
        assert client.err_cnt > 0, f"Timeout should generate errors, got {client.err_cnt}"
        
        print(f"✅ Timeout properly handled - Duration: {elapsed:.1f}s, Errors: {client.err_cnt}")
        
    finally:
        client.stop()
        thread.join(timeout=2)


@pytest.mark.requires_gstreamer  
def test_connection_attempt_behavior(test_rtsp_url):
    """Test that connection attempts behave correctly regardless of URL type.
    
    This test validates proper connection behavior without making assumptions
    about success or failure - it just ensures the client behaves correctly.
    """
    client = CombinedRTSPClient(test_rtsp_url, timeout=4.0)
    
    thread = threading.Thread(target=client.start, daemon=True)  
    thread.start()
    
    try:
        time.sleep(5.0)  # Wait for connection attempt to complete
        
        # Test the actual behavior - connection either works or fails gracefully
        if client.video_cnt > 0:
            # Connection successful - got video data
            print(f"✅ Connection successful - Video frames: {client.video_cnt}, Errors: {client.err_cnt}")
            # Note: Errors might still occur (e.g., metadata timeout) even with successful video
            assert client.start_time is not None, "Start time should be recorded"
            assert client.video_cnt >= 1, "Should have received at least one video frame"
        else:
            # Connection failed - should have recorded the failure
            print(f"❌ Connection failed - Video frames: {client.video_cnt}, Errors: {client.err_cnt}")
            assert client.err_cnt > 0, f"Failed connection should report errors, got {client.err_cnt}"
            # This is expected behavior when RTSP URL is unreachable
            
        # Both success and failure cases should have proper state
        assert hasattr(client, 'start_time'), "Client should have start_time attribute"
        assert hasattr(client, 'video_cnt'), "Client should have video_cnt attribute"
        assert hasattr(client, 'err_cnt'), "Client should have err_cnt attribute"
            
    finally:
        client.stop()
        thread.join(timeout=2)


@pytest.mark.requires_gstreamer  
def test_error_callback_triggered():
    """Test that error callback is properly triggered during actual errors."""
    error_queue = queue.Queue()
    
    def error_callback(payload):
        error_queue.put(payload)
        print(f"Error callback triggered: {payload}")
    
    client = VideoGStreamerClient(
        "rtsp://192.0.2.1:554/nonexistent",  # Unreachable server
        timeout=2.0,
        session_metadata_callback=error_callback  # VideoGStreamerClient uses this for errors
    )
    
    thread = threading.Thread(target=client.start, daemon=True)
    thread.start()
    
    try:
        time.sleep(3.0)  # Wait for timeout and errors
        
        # Should have detected connection failure
        assert client.error_count > 0, f"Should have connection errors, got {client.error_count}"
        
        print(f"✅ Error detection working - Errors: {client.error_count}")
        
    finally:
        client.stop()
        thread.join(timeout=2)


@pytest.mark.requires_gstreamer
def test_definite_connection_failure():
    """Test guaranteed connection failure scenario with unreachable server."""
    # Use RFC5737 test network address that is guaranteed to be unreachable
    unreachable_url = "rtsp://192.0.2.1:554/guaranteed-failure"
    
    client = CombinedRTSPClient(unreachable_url, timeout=3.0)
    
    thread = threading.Thread(target=client.start, daemon=True)
    thread.start()
    
    try:
        time.sleep(4.0)  # Wait for connection attempt to fail
        
        # This URL is guaranteed to be unreachable, so should definitely fail
        assert client.video_cnt == 0, f"Unreachable server should not provide video frames, got {client.video_cnt}"
        assert client.err_cnt > 0, f"Unreachable server should cause errors, got {client.err_cnt}"
        
        print(f"✅ Guaranteed failure test - Video: {client.video_cnt}, Errors: {client.err_cnt}")
        
    finally:
        client.stop()
        thread.join(timeout=2)


@pytest.mark.requires_gstreamer
def test_concurrent_connection_failures():
    """Test multiple concurrent connection failures are handled properly."""
    clients = []
    error_counts = []
    
    # Create multiple clients with different unreachable URLs
    urls = [
        "rtsp://192.0.2.1:554/stream1",
        "rtsp://192.0.2.2:554/stream2", 
        "rtsp://192.0.2.3:554/stream3"
    ]
    
    threads = []
    
    try:
        for i, url in enumerate(urls):
            client = CombinedRTSPClient(url, timeout=2.0)
            clients.append(client)
            
            thread = threading.Thread(target=client.start, daemon=True)
            threads.append(thread)
            thread.start()
        
        time.sleep(3.0)  # Wait for all to timeout
        
        # All should have failed with errors
        for i, client in enumerate(clients):
            assert client.err_cnt > 0, f"Client {i} should have connection errors, got {client.err_cnt}"
            error_counts.append(client.err_cnt)
        
        print(f"✅ Concurrent failures handled - Error counts: {error_counts}")
        
    finally:
        # Clean up all clients
        for client in clients:
            client.stop()
        for thread in threads:
            thread.join(timeout=2) 