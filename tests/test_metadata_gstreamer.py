import pytest
pytest.importorskip("gi")
pytest.importorskip("numpy")
from ax_devil_rtsp.examples.metadata_gstreamer import SceneMetadataClient
import threading
import queue
import time

@pytest.mark.requires_gstreamer
def test_metadata_client_creation(rtsp_url):
    """Test that client can be created without errors."""
    client = SceneMetadataClient(rtsp_url, latency=100)
    assert client is not None
    assert client.pipeline is not None

@pytest.mark.requires_gstreamer
def test_metadata_client_receives_data(gst_rtsp_server):
    """Test that client can receive metadata from camera."""
    metadata_queue = queue.Queue()
    
    def callback(xml_text):
        metadata_queue.put(xml_text)
    
    client = SceneMetadataClient(gst_rtsp_server + "?analytics=polygon",
                              latency=100,
                              raw_data_callback=callback)
    
    # Start client in separate thread
    thread = threading.Thread(target=client.start)
    thread.daemon = True
    thread.start()
    
    try:
        # Wait for metadata
        metadata = metadata_queue.get(timeout=10)
        assert metadata is not None
        assert '<tt:MetadataStream' in metadata
    finally:
        client.stop()
        thread.join(timeout=5)
