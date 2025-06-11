"""
Unit Tests for gstreamer_data_grabber.py

Hardware-independent tests that test isolated functionality:
- RTP data parsing logic
- Video format conversions
- Buffer operations
- Error handling structures
- Configuration validation
- Helper functions

These tests do NOT require:
- Real RTSP connections
- Actual camera hardware
- Network communication
- GStreamer pipeline execution
"""

import pytest
import time
import numpy as np
from unittest.mock import Mock
from datetime import datetime, timezone

pytest.importorskip("gi")
pytest.importorskip("numpy")

from ax_devil_rtsp.gstreamer_data_grabber import (
    CombinedRTSPClient, 
    _map_buffer, 
    _to_rgb_array
)


# Mock objects for isolated testing
class MockBuffer:
    def __init__(self, data: bytes = b"test_data"):
        self.data = data
        self._mapped = False
    
    def map(self, flags):
        self._mapped = True
        mock_info = Mock()
        mock_info.data = self.data
        return True, mock_info
    
    def unmap(self, info):
        self._mapped = False


class MockMapInfo:
    def __init__(self, data: bytes):
        self.data = data


class TestRTPDataParsing:
    """Test RTP data parsing logic without network communication."""
    
    def test_rtp_data_structure_initialization(self):
        """Test that RTP data tracking is properly initialized."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        
        assert client.latest_rtp_data is None
        assert hasattr(client, 'latest_rtp_data')
    
    def test_rtp_timestamp_parsing_simulation(self):
        """Test RTP timestamp parsing logic in isolation."""
        # Simulate the timestamp parsing logic from _rtp_probe
        n_sec = 3855729600  # Example NTP timestamp seconds
        n_frac = 2147483648  # Example NTP fraction (0.5 seconds)
        flags = 0xA0000042  # Example flags with C=1, E=0, D=1, T=0, CSeq=66
        
        # Convert to Unix timestamp (as done in _rtp_probe)
        unix_ts = n_sec - 2208988800 + n_frac / (1 << 32)
        human_time = datetime.fromtimestamp(unix_ts, timezone.utc)
        
        rtp_data = {
            'human_time': human_time.strftime("%Y-%m-%d %H:%M:%S.%f UTC"),
            'ntp_seconds': n_sec,
            'ntp_fraction': n_frac,
            'C': (flags >> 31) & 1,
            'E': (flags >> 30) & 1, 
            'D': (flags >> 29) & 1,
            'T': (flags >> 28) & 1,
            'CSeq': flags & 0xFF
        }
        
        # Validate parsing results
        assert rtp_data['C'] == 1  # Camera flag
        assert rtp_data['E'] == 0  # Error flag
        assert rtp_data['D'] == 1  # Dropped frame flag
        assert rtp_data['T'] == 0  # Timing flag  
        assert rtp_data['CSeq'] == 66  # Sequence number
        assert 'UTC' in rtp_data['human_time']
        assert rtp_data['ntp_seconds'] == n_sec
        assert rtp_data['ntp_fraction'] == n_frac
    
    def test_rtp_flags_bit_extraction(self):
        """Test various RTP flag combinations."""
        test_cases = [
            (0x80000001, {'C': 1, 'E': 0, 'D': 0, 'T': 0, 'CSeq': 1}),
            (0x40000002, {'C': 0, 'E': 1, 'D': 0, 'T': 0, 'CSeq': 2}),
            (0x20000003, {'C': 0, 'E': 0, 'D': 1, 'T': 0, 'CSeq': 3}),
            (0x10000004, {'C': 0, 'E': 0, 'D': 0, 'T': 1, 'CSeq': 4}),
            (0xF00000FF, {'C': 1, 'E': 1, 'D': 1, 'T': 1, 'CSeq': 255}),
        ]
        
        for flags, expected in test_cases:
            result = {
                'C': (flags >> 31) & 1,
                'E': (flags >> 30) & 1,
                'D': (flags >> 29) & 1,
                'T': (flags >> 28) & 1,
                'CSeq': flags & 0xFF
            }
            assert result == expected, f"Failed for flags 0x{flags:08X}"


class TestVideoFormatConversions:
    """Test video format conversion functions."""
    
    def test_to_rgb_array_rgb_format(self):
        """Test RGB format conversion."""
        width, height = 320, 240
        # Create mock RGB data (320x240x3 = 230400 bytes)
        rgb_data = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        mock_info = MockMapInfo(rgb_data.tobytes())
        
        result = _to_rgb_array(mock_info, width, height, "RGB")
        
        assert result.shape == (height, width, 3)
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, rgb_data)
    
    def test_to_rgb_array_rgb16_format(self):
        """Test RGB16 format conversion."""
        width, height = 160, 120
        # Create mock RGB16 data (160x120 = 19200 uint16 values)
        rgb16_data = np.random.randint(0, 65535, (height, width), dtype=np.uint16)
        mock_info = MockMapInfo(rgb16_data.tobytes())
        
        result = _to_rgb_array(mock_info, width, height, "RGB16")
        
        assert result.shape == (height, width)
        assert result.dtype == np.uint16
        np.testing.assert_array_equal(result, rgb16_data)
    
    def test_to_rgb_array_bgr16_format(self):
        """Test BGR16 format conversion."""
        width, height = 160, 120
        # Create mock BGR16 data (160x120 = 19200 uint16 values)
        bgr16_data = np.random.randint(0, 65535, (height, width), dtype=np.uint16)
        mock_info = MockMapInfo(bgr16_data.tobytes())
        
        result = _to_rgb_array(mock_info, width, height, "BGR16")
        
        assert result.shape == (height, width)
        assert result.dtype == np.uint16
        np.testing.assert_array_equal(result, bgr16_data)
    
    def test_to_rgb_array_unsupported_format(self):
        """Test handling of unsupported pixel formats."""
        mock_info = MockMapInfo(b"dummy_data")
        
        with pytest.raises(ValueError, match="Unsupported pixel format"):
            _to_rgb_array(mock_info, 320, 240, "UNSUPPORTED_FORMAT")


class TestBufferOperations:
    """Test buffer mapping and memory operations."""
    
    def test_map_buffer_function(self):
        """Test the _map_buffer helper function."""
        mock_buffer = MockBuffer(b"test_data_12345")
        
        success, info = _map_buffer(mock_buffer)
        
        assert success is True
        assert info.data == b"test_data_12345"
        assert mock_buffer._mapped is True
    
    def test_map_buffer_with_different_data_sizes(self):
        """Test buffer mapping with various data sizes."""
        test_sizes = [0, 1, 100, 1024, 65536]
        
        for size in test_sizes:
            data = b"x" * size
            mock_buffer = MockBuffer(data)
            
            success, info = _map_buffer(mock_buffer)
            
            assert success is True
            assert info.data == data
            assert len(info.data) == size


class TestDiagnosticsStructures:
    """Test diagnostic data structures and calculations."""
    
    def test_timer_initialization(self):
        """Test that timing measurements are properly initialized."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        
        expected_timers = ['rtp_probe', 'vid_sample', 'vid_proc', 'vid_cb']
        for timer_name in expected_timers:
            assert timer_name in client._timers
            assert client._timers[timer_name] is None
    
    def test_video_diagnostics_structure(self):
        """Test video diagnostics data structure and content."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        client.start_time = time.time()
        client.video_cnt = 42
        client.err_cnt = 3
        
        # Simulate some timer data
        client._timers['rtp_probe'] = time.time() - 1.0
        client._timers['vid_sample'] = time.time() - 0.5
        client._timers['vid_proc'] = 0.025
        client._timers['vid_cb'] = 0.010
        
        diag = client._video_diag()
        
        # Validate structure
        assert isinstance(diag, dict)
        assert 'video_sample_count' in diag
        assert 'time_rtp_probe' in diag
        assert 'time_sample' in diag
        assert 'time_processing' in diag
        assert 'time_callback' in diag
        assert 'error_count' in diag
        assert 'uptime' in diag
        
        # Validate values
        assert diag['video_sample_count'] == 42
        assert diag['error_count'] == 3
        assert diag['uptime'] > 0
        assert diag['time_processing'] == 0.025
        assert diag['time_callback'] == 0.010
    
    def test_metadata_diagnostics_structure(self):
        """Test metadata diagnostics data structure and content."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        client.start_time = time.time()
        client.meta_cnt = 15
        client.xml_cnt = 8
        client.err_cnt = 1
        
        diag = client._meta_diag()
        
        # Validate structure
        assert isinstance(diag, dict)
        assert 'metadata_sample_count' in diag
        assert 'xml_message_count' in diag
        assert 'error_count' in diag
        assert 'uptime' in diag
        
        # Validate values
        assert diag['metadata_sample_count'] == 15
        assert diag['xml_message_count'] == 8
        assert diag['error_count'] == 1
        assert diag['uptime'] > 0


class TestErrorHandlingStructures:
    """Test error handling structures and logic."""
    
    def test_error_reporting_structure(self):
        """Test error reporting mechanism and payload structure."""
        error_reports = []
        
        def error_callback(payload):
            error_reports.append(payload)
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            error_callback=error_callback,
            timeout=5.0
        )
        client.start_time = time.time()
        
        # Test error reporting
        test_exception = ValueError("Test error")
        client._report_error("Test Type", "Test message", test_exception)
        
        assert len(error_reports) == 1
        error = error_reports[0]
        
        # Validate error structure
        assert 'error_type' in error
        assert 'message' in error
        assert 'exception' in error
        assert 'error_count' in error
        assert 'timestamp' in error
        assert 'uptime' in error
        
        # Validate error content
        assert error['error_type'] == "Test Type"
        assert error['message'] == "Test message"
        assert error['exception'] == "Test error"
        assert error['error_count'] == 1
        assert error['timestamp'] > 0
        assert error['uptime'] >= 0
    
    def test_error_counter_increment(self):
        """Test that error counter is properly incremented."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        
        initial_count = client.err_cnt
        
        client._report_error("Type1", "Message1")
        assert client.err_cnt == initial_count + 1
        
        client._report_error("Type2", "Message2")
        assert client.err_cnt == initial_count + 2
    
    def test_error_callback_failure_handling(self):
        """Test handling of failures in error callback itself."""
        def failing_error_callback(payload):
            raise RuntimeError("Error callback failed")
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            error_callback=failing_error_callback,
            timeout=5.0
        )
        
        # Should not raise exception even if error callback fails
        client._report_error("Test", "Should not crash")
        assert client.err_cnt == 1


class TestConfigurationHandling:
    """Test configuration validation and handling."""
    
    def test_shared_config_handling(self):
        """Test shared configuration is properly stored and accessible."""
        shared_config = {
            "param1": "value1",
            "param2": 42,
            "param3": [1, 2, 3]
        }
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            shared_config=shared_config,
            timeout=5.0
        )
        
        assert client.shared_cfg == shared_config
        assert client.shared_cfg["param1"] == "value1"
        assert client.shared_cfg["param2"] == 42
        assert client.shared_cfg["param3"] == [1, 2, 3]
    
    def test_custom_latency_configuration(self):
        """Test custom latency setting is applied."""
        custom_latency = 500
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            latency=custom_latency,
            timeout=5.0
        )
        
        assert client.latency == custom_latency
    
    def test_timeout_configuration(self):
        """Test timeout setting is stored correctly."""
        timeout = 10.0
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            timeout=timeout,
            latency=100
        )
        
        assert client.timeout == timeout
    
    def test_callback_configuration_completeness(self):
        """Test that all callback types can be configured."""
        def dummy_video_cb(payload): pass
        def dummy_meta_cb(payload): pass  
        def dummy_session_cb(payload): pass
        def dummy_error_cb(payload): pass
        def dummy_processing_fn(frame, config): return frame
        
        client = CombinedRTSPClient(
            "rtsp://test.com/stream",
            video_frame_callback=dummy_video_cb,
            metadata_callback=dummy_meta_cb,
            session_metadata_callback=dummy_session_cb,
            error_callback=dummy_error_cb,
            video_processing_fn=dummy_processing_fn,
            timeout=5.0
        )
        
        assert client.video_frame_cb == dummy_video_cb
        assert client.metadata_cb == dummy_meta_cb
        assert client.session_md_cb == dummy_session_cb
        assert client.error_cb == dummy_error_cb
        assert client.video_proc_fn == dummy_processing_fn


class TestXMLAndMetadataStructures:
    """Test XML and metadata handling structures."""
    
    def test_xml_accumulator_initialization(self):
        """Test XML accumulator is properly initialized."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        
        assert hasattr(client, '_xml_acc')
        assert client._xml_acc == b""
        assert isinstance(client._xml_acc, bytes)
    
    def test_metadata_branch_lazy_creation(self):
        """Test that metadata branch is created on demand."""
        client = CombinedRTSPClient("rtsp://test.com/stream", timeout=5.0)
        
        # Initially not built
        assert not client.meta_branch_built
        
        # Should build on demand
        client._ensure_meta_branch()
        
        # Should now be built
        assert client.meta_branch_built
        assert hasattr(client, 'm_jit')


if __name__ == "__main__":
    # Configure logging for test runs
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run tests
    pytest.main([__file__, "-v"]) 