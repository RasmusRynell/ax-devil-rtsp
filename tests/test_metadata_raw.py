import pytest
import socket
from unittest.mock import Mock, patch
from ax_devil_rtsp.metadata_raw import RTSPProtocolClient, MetadataHandler

# Mock responses for RTSP commands
MOCK_401_RESPONSE = (
    "RTSP/1.0 401 Unauthorized\r\n"
    'WWW-Authenticate: Digest realm="axis", nonce="123456", algorithm="MD5"\r\n'
    "CSeq: 1\r\n\r\n"
)

MOCK_200_RESPONSE = (
    "RTSP/1.0 200 OK\r\n"
    "CSeq: 1\r\n"
    "Session: 12345678\r\n\r\n"
)

MOCK_SDP_RESPONSE = (
    "RTSP/1.0 200 OK\r\n"
    "CSeq: 1\r\n"
    "Content-Base: rtsp://192.168.1.81/\r\n"
    "Content-Type: application/sdp\r\n"
    "Content-Length: 400\r\n"
    "\r\n"  # Important: Double CRLF before SDP content
    "v=0\r\n"
    "o=- 123456 2 IN IP4 192.168.1.81\r\n"
    "s=Session\r\n"
    "m=application 0 RTP/AVP 96\r\n"
    "a=rtpmap:96 metadata/1000\r\n"
    "a=control:metadata\r\n"
)

@pytest.fixture
def mock_socket():
    with patch('socket.socket') as mock:
        mock_sock = Mock()
        mock.return_value = mock_sock
        yield mock_sock

def test_rtsp_client_creation(mock_socket):
    """Test client creation and basic setup"""
    client = RTSPProtocolClient("192.168.1.81", "root", "pass", "rtsp://192.168.1.81/test")
    assert client.ip == "192.168.1.81"
    assert client.username == "root"
    assert client.password == "pass"
    mock_socket.connect.assert_called_once_with(("192.168.1.81", 554))

def test_rtsp_auth_flow(mock_socket):
    """Test RTSP authentication flow"""
    mock_socket.recv.side_effect = [
        MOCK_401_RESPONSE.encode(),  # First response (401)
        MOCK_200_RESPONSE.encode(),  # Second response (200 OK)
    ]
    
    client = RTSPProtocolClient("192.168.1.81", "root", "pass", "rtsp://192.168.1.81/test")
    response = client.send_rtsp("DESCRIBE", "rtsp://192.168.1.81/test")
    
    assert "200 OK" in response
    assert mock_socket.send.call_count == 2  # Initial request + auth request

def test_rtsp_describe_sdp_parsing(mock_socket):
    """Test SDP parsing from DESCRIBE response"""
    mock_socket.recv.side_effect = [
        MOCK_401_RESPONSE.encode(),  # First response (401)
        MOCK_SDP_RESPONSE.encode(),  # Second response (SDP)
    ]
    
    client = RTSPProtocolClient("192.168.1.81", "root", "pass", "rtsp://192.168.1.81/test")
    sdp = client.describe()
    
    assert "m=application" in sdp
    assert "a=control:metadata" in sdp
    assert mock_socket.send.call_count == 2  # Initial + Auth request

@pytest.mark.camera_required
def test_rtsp_client_live_connection(rtsp_credentials):
    """Test actual connection to camera"""
    client = RTSPProtocolClient(
        rtsp_credentials['ip'],
        rtsp_credentials['username'],
        rtsp_credentials['password'],
        f"rtsp://{rtsp_credentials['ip']}/axis-media/media.amp?analytics=polygon"
    )
    
    try:
        sdp = client.describe()
        assert sdp is not None
        assert "v=0" in sdp
        
        # Look for metadata track
        metadata_track = None
        current_media = None
        for line in sdp.splitlines():
            if (line.startswith("m=")):
                current_media = line.split()[0][2:].lower()
            elif (line.startswith("a=control:") and current_media == "application"):
                metadata_track = line[len("a=control:"):].strip()
                break
        
        assert metadata_track is not None, "No metadata track found in SDP"
        
        # Test SETUP
        client.setup(metadata_track)
        assert client.session_id is not None
        
    finally:
        client.teardown()

@pytest.mark.camera_required
def test_metadata_handler_live_data(rtsp_credentials):
    """Test receiving actual metadata from camera"""
    import queue
    import threading
    
    metadata_queue = queue.Queue()
    stop_event = threading.Event()  # Add event for controlled shutdown
    
    class TestMetadataHandler(MetadataHandler):
        def process_xml(self, xml_data):
            try:
                text = xml_data.decode('utf-8')
                metadata_queue.put(text)
            except Exception as e:
                pytest.fail(f"Failed to process XML: {e}")
    
    base_url = f"rtsp://{rtsp_credentials['ip']}/axis-media/media.amp?analytics=polygon"
    client = RTSPProtocolClient(
        rtsp_credentials['ip'],
        rtsp_credentials['username'],
        rtsp_credentials['password'],
        base_url
    )
    
    thread = None
    try:
        # Get SDP and find metadata track
        sdp = client.describe()
        metadata_track = None
        current_media = None
        
        for line in sdp.splitlines():
            if line.startswith("m="):
                parts = line.split()
                current_media = parts[0][2:].lower() if parts else None
            elif line.startswith("a=control:") and current_media == "application":
                metadata_track = line[len("a=control:"):].strip()
                break
        
        assert metadata_track is not None, "No metadata track found in SDP"
        
        # Setup the found metadata track
        client.setup(metadata_track)
        assert client.session_id is not None
        
        # Start playback
        client.play()
        
        # Start receiving in a separate thread
        handler_map = {0: TestMetadataHandler()}
        thread = threading.Thread(
            target=client.receive_data,
            args=(handler_map, stop_event),  # Pass stop_event to receive_data
            kwargs={"timeout": 1.0}
        )
        thread.daemon = True
        thread.start()
        
        # Wait for metadata
        try:
            metadata = metadata_queue.get(timeout=10)
            assert metadata is not None
            assert '<tt:MetadataStream' in metadata
        except queue.Empty:
            pytest.fail("No metadata received within timeout")
        finally:
            stop_event.set()  # Signal thread to stop
            thread.join(timeout=2)
            if thread.is_alive():
                pytest.fail("Thread failed to stop")
            
    finally:
        if thread and thread.is_alive():
            stop_event.set()
            thread.join(timeout=2)
        client.teardown()
