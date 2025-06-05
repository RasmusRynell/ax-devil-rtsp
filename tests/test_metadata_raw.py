import unittest
from unittest.mock import MagicMock, patch
import socket
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

# Load the metadata_raw module directly to avoid importing package __init__
module_path = Path(__file__).resolve().parents[1] / "src" / "ax_devil_rtsp" / "examples" / "metadata_raw.py"
SceneMetadataRawClient = SourceFileLoader("metadata_raw", str(module_path)).load_module().SceneMetadataRawClient

class TestSceneMetadataRawClient(unittest.TestCase):
    def setUp(self):
        self.rtsp_url = "rtsp://root:pass@192.168.1.81/axis-media/media.amp?analytics=polygon"
        self.raw_data_callback = MagicMock()
        
    @patch('socket.socket')
    def test_init(self, mock_socket):
        client = SceneMetadataRawClient(self.rtsp_url)
        self.assertEqual(client.username, "root")
        self.assertEqual(client.password, "pass")
        self.assertEqual(client.ip, "192.168.1.81")
        self.assertEqual(client.port, 554)
        
    @patch('socket.socket')
    def test_auth_flow(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        
        # Setup mock responses
        mock_sock.recv.side_effect = [
            b"RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm=\"realm\", nonce=\"nonce\"\r\n\r\n",
            b"RTSP/1.0 200 OK\r\n\r\n"
        ]
        
        client = SceneMetadataRawClient(self.rtsp_url)
        client._connect()  # Ensure socket is connected before sending requests
        response = client._send_rtsp("DESCRIBE", self.rtsp_url)
        
        self.assertEqual(response, "RTSP/1.0 200 OK\r\n\r\n")
        self.assertEqual(mock_sock.send.call_count, 2)
        
        # Verify auth header was sent in second request
        second_request = mock_sock.send.call_args_list[1][0][0].decode()
        self.assertIn("Authorization: Digest", second_request)
        
    @patch('socket.socket')
    def test_start_stop(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        
        # Setup mock responses for RTSP sequence
        mock_sock.recv.side_effect = [
            # DESCRIBE response with SDP
            b"RTSP/1.0 200 OK\r\n\r\nv=0\r\nm=application 0 RTP/AVP 96\r\na=control:trackID=1\r\n",
            # SETUP response
            b"RTSP/1.0 200 OK\r\nSession: 12345\r\n\r\n",
            # PLAY response
            b"RTSP/1.0 200 OK\r\n\r\n",
            # Simulated RTP packet with metadata
            b"$\x00\x00\x50" + b"\x80\x80\x00\x00" + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" + 
            b'<?xml version="1.0"?><tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">' +
            b'<tt:Frame UtcTime="2024-01-01T00:00:00Z"><tt:Object ObjectId="1"><tt:Type>Human</tt:Type></tt:Object></tt:Frame>' +
            b'</tt:MetadataStream>',
            # Simulate connection close
            b""
        ]
        
        client = SceneMetadataRawClient(self.rtsp_url, raw_data_callback=self.raw_data_callback)
        
        # Run client in non-blocking way for testing
        with patch.object(client, '_receive_data') as mock_receive:
            client.start()
            
            # Verify RTSP sequence
            calls = mock_sock.send.call_args_list
            self.assertIn("DESCRIBE", calls[0][0][0].decode())
            self.assertIn("SETUP", calls[1][0][0].decode())
            self.assertIn("PLAY", calls[2][0][0].decode())
            
        client.stop()
        
        # Verify TEARDOWN was sent
        self.assertIn("TEARDOWN", mock_sock.send.call_args[0][0].decode())
        
    def test_metadata_handling(self):
        client = SceneMetadataRawClient(self.rtsp_url, raw_data_callback=self.raw_data_callback)
        
        # Test metadata packet handling
        test_xml = (
            b'<?xml version="1.0"?><tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">'
            b'<tt:Frame UtcTime="2024-01-01T00:00:00Z"><tt:Object ObjectId="1"><tt:Type>Human</tt:Type></tt:Object></tt:Frame>'
            b'</tt:MetadataStream>'
        )
        
        # Create RTP packet with marker bit set
        rtp_header = bytearray([
            0x80, 0x80, 0x00, 0x00,  # V=2, P=0, X=0, CC=0, M=1, PT=0, SeqNum=0
            0x00, 0x00, 0x00, 0x00,  # Timestamp
            0x00, 0x00, 0x00, 0x00   # SSRC
        ])
        rtp_packet = bytes(rtp_header) + test_xml
        
        client._handle_metadata_packet(rtp_packet)
        
        # Verify callback was called with raw XML
        self.raw_data_callback.assert_called_once()
        xml_text = self.raw_data_callback.call_args[0][0]
        self.assertIsInstance(xml_text, str)
        self.assertIn('<?xml version="1.0"?>', xml_text)
        self.assertIn('<tt:MetadataStream', xml_text)
        self.assertIn('UtcTime="2024-01-01T00:00:00Z"', xml_text)
        self.assertIn('<tt:Type>Human</tt:Type>', xml_text)

if __name__ == '__main__':
    unittest.main()
