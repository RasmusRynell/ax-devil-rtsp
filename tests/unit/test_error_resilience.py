"""
Unit test for error resilience in callback handling.
"""

import pytest
import time
import queue as queue_mod
import threading
from unittest.mock import Mock, patch
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever


def test_callback_exception_handling():
    """
    Test that exceptions in callbacks don't break retriever operation or cleanup.
    """
    # Create a callback that raises an exception
    def failing_callback(payload):
        raise ValueError("Test callback exception")
    
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        on_video_data=failing_callback
    )
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue') as mock_queue_class:
            mock_queue = Mock()
            mock_queue_class.return_value = mock_queue
            
            # Use a side_effect function to simulate one item, then queue.Empty exception
            def get_side_effect(*args, **kwargs):
                if not hasattr(get_side_effect, 'called'):
                    get_side_effect.called = True
                    return {"kind": "video", "data": "test_data"}
                raise queue_mod.Empty()
            mock_queue.get.side_effect = get_side_effect
            
            retriever.start()
            
            # Initialize for dispatch test
            retriever._queue = mock_queue
            retriever._stop_event = threading.Event()
            
            # Dispatch should handle the exception gracefully
            # The exception should not prevent the loop from continuing
            retriever._queue_dispatch_loop()
            
            # Retriever should still be able to stop cleanly
            retriever.stop()
            assert not retriever.is_running


def test_multiple_callback_exceptions():
    """
    Test that multiple callback exceptions don't accumulate problems.
    """
    exception_count = 0
    
    def sometimes_failing_callback(payload):
        nonlocal exception_count
        exception_count += 1
        if exception_count <= 2:
            raise RuntimeError(f"Exception {exception_count}")
        # After 2 exceptions, work normally
    
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        on_video_data=sometimes_failing_callback
    )
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue') as mock_queue_class:
            mock_queue = Mock()
            mock_queue_class.return_value = mock_queue
            
            # Use a side_effect function to simulate three items, then queue.Empty exception
            def get_side_effect(*args, **kwargs):
                if not hasattr(get_side_effect, 'count'):
                    get_side_effect.count = 0
                if get_side_effect.count < 3:
                    get_side_effect.count += 1
                    return {"kind": "video", "data": f"data{get_side_effect.count}"}
                raise queue_mod.Empty()
            mock_queue.get.side_effect = get_side_effect
            
            retriever.start()
            retriever._queue = mock_queue
            retriever._stop_event = threading.Event()
            
            # Should handle all exceptions and continue
            retriever._queue_dispatch_loop()
            
            retriever.stop()
            assert not retriever.is_running
            
            # Verify callback was called 3 times (2 exceptions + 1 success)
            assert exception_count == 3


def test_queue_error_handling():
    """
    Test that queue errors (like EOFError, OSError) are handled gracefully.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream"
    )
    
    with patch('multiprocessing.Process') as mock_process_class:
        mock_process = Mock()
        mock_process.is_alive.return_value = True
        mock_process_class.return_value = mock_process
        
        with patch('multiprocessing.Queue') as mock_queue_class:
            mock_queue = Mock()
            mock_queue_class.return_value = mock_queue
            
            # Queue raises EOFError (simulating broken queue/dead parent)
            mock_queue.get.side_effect = EOFError("Queue broken")
            
            retriever.start()
            
            retriever._queue = mock_queue
            retriever._stop_event = threading.Event()
            
            # Should handle EOFError gracefully and exit loop
            retriever._queue_dispatch_loop()
            
            retriever.stop()
            assert not retriever.is_running 