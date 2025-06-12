"""
Unit test for retriever lifecycle management.
"""

import pytest
import time
from unittest.mock import Mock, patch
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever


def test_multiple_start_stop_cycles():
    """
    Test that retrievers can handle multiple start/stop cycles safely.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        connection_timeout=5
    )
    
    # Initially not running
    assert not retriever.is_running
    
    # Test multiple cycles
    for i in range(3):
        # Mock the process to avoid actual RTSP connection
        with patch('multiprocessing.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.is_alive.return_value = True
            mock_process_class.return_value = mock_process
            
            with patch('multiprocessing.Queue'):
                retriever.start()
                assert retriever.is_running
                
                retriever.stop()
                assert not retriever.is_running


def test_stop_without_start():
    """
    Test that calling stop() without start() is safe.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream"
    )
    
    # Should be safe to call stop without start
    retriever.stop()
    assert not retriever.is_running
    
    # Multiple stops should also be safe
    retriever.stop()
    retriever.stop()
    assert not retriever.is_running


def test_start_when_already_started():
    """
    Test that starting an already started retriever raises an error.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream"
    )
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue'):
            retriever.start()
            
            # Starting again should raise error
            with pytest.raises(RuntimeError, match="already started"):
                retriever.start()
            
            retriever.stop()


def test_is_running_property():
    """
    Test that is_running property accurately reflects retriever state.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream"
    )
    
    # Initially not running
    assert not retriever.is_running
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue'):
            # When process is alive, should be running
            mock_process.is_alive.return_value = True
            retriever.start()
            assert retriever.is_running
            
            # When process is dead, should not be running
            mock_process.is_alive.return_value = False
            assert not retriever.is_running
            
            retriever.stop()
            assert not retriever.is_running


def test_close_method():
    """
    Test that close() method works as alias for stop().
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream"
    )
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue'):
            retriever.start()
            assert retriever.is_running
            
            retriever.close()  # Should work like stop()
            assert not retriever.is_running 