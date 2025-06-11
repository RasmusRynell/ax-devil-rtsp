import pytest
pytest.importorskip("gi")
pytest.importorskip("numpy")
from ax_devil_rtsp.examples.metadata_gstreamer import SceneMetadataClient
import threading
import queue

# test_metadata_client_creation moved to tests/unit/test_client_creation.py

@pytest.mark.requires_gstreamer
def test_metadata_client_connection_attempt(test_rtsp_url):
    """Test that metadata client attempts connection (may fail since basic server has no metadata)."""
    import time
    
    client = SceneMetadataClient(test_rtsp_url, latency=100, timeout=3.0)
    
    try:
        client.start()
        time.sleep(2.0)  # Allow connection attempt
        # Basic test server only provides video, no metadata streams
        # SceneMetadataClient is expected to fail with "not-linked" error
        # We're testing that it handles this gracefully without hanging
        assert client.error_count > 0, f"Expected connection error since basic server has no metadata streams"
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_metadata_client_timeout_behavior():
    """Test that metadata client has proper timeout behavior (no hanging)."""
    import time
    
    start_time = time.time()
    client = SceneMetadataClient(
        'rtsp://192.0.2.1:554/fake',  # Non-existent server
        latency=100,
        timeout=2.0  # 2 second timeout
    )
    
    try:
        client.start()
        # Wait for timeout
        time.sleep(3)  # Wait longer than timeout
        elapsed = time.time() - start_time
        # Should complete within reasonable time due to timeout
        assert elapsed < 5, f"Client should have timed out but took {elapsed:.1f}s"
        # Should have error count > 0 from timeout
        assert client.error_count > 0, "Client should have recorded timeout as error"
    finally:
        client.stop()
        assert client.error_count > 0, "Client should have recorded timeout as error"
