"""
Unit test for callback dispatch logic in retrievers.
"""

import pytest
import time
import queue as queue_mod
import threading
from unittest.mock import Mock, patch
from ax_devil_rtsp.rtsp_data_retrievers import RtspDataRetriever


def test_callback_dispatch_logic():
    """
    Test that queue items are dispatched to the correct callbacks.
    """
    # Mock callbacks
    video_callback = Mock()
    application_data_callback = Mock()
    error_callback = Mock()
    session_callback = Mock()
    
    retriever = RtspDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        on_video_data=video_callback,
        on_application_data=application_data_callback,
        on_error=error_callback,
        on_session_start=session_callback
    )
    
    # Mock the queue and manually inject items
    with patch('multiprocessing.Queue') as mock_queue_class:
        mock_queue = Mock()
        mock_queue_class.return_value = mock_queue
        
        # Set up queue behavior
        test_items = [
            {"kind": "video", "data": "video_data"},
            {"kind": "application_data", "data": "application_data_data"},
            {"kind": "error", "data": "error_data"},
            {"kind": "session_start", "data": "session_data"}
        ]
        
        # Mock queue.get to return items then raise Empty
        mock_queue.get.side_effect = test_items + [queue_mod.Empty()]
        
        # Initialize retriever components
        retriever._queue = mock_queue
        retriever._stop_event = threading.Event()
        
        # Run dispatch loop once
        retriever._queue_dispatch_loop()
        
        # Verify correct callbacks were called
        video_callback.assert_called_once_with({"kind": "video", "data": "video_data"})
        application_data_callback.assert_called_once_with({"kind": "application_data", "data": "application_data_data"})
        error_callback.assert_called_once_with({"kind": "error", "data": "error_data"})
        session_callback.assert_called_once_with({"kind": "session_start", "data": "session_data"})


def test_callback_dispatch_with_none_callbacks():
    """
    Test that dispatch works correctly when some callbacks are None.
    """
    video_callback = Mock()
    
    retriever = RtspDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        on_video_data=video_callback,
        # Other callbacks are None
    )
    
    with patch('multiprocessing.Queue') as mock_queue_class:
        mock_queue = Mock()
        mock_queue_class.return_value = mock_queue
        
        test_items = [
            {"kind": "video", "data": "video_data"},
            {"kind": "application_data", "data": "application_data_data"},  # Should be ignored
            {"kind": "error", "data": "error_data"},        # Should be ignored
        ]
        
        mock_queue.get.side_effect = test_items + [queue_mod.Empty()]
        
        retriever._queue = mock_queue
        retriever._stop_event = threading.Event()
        
        retriever._queue_dispatch_loop()
        
        # Only video callback should be called
        video_callback.assert_called_once_with({"kind": "video", "data": "video_data"}) 


def test_dispatch_waits_for_delayed_data(monkeypatch):
    """
    The dispatch loop should wait for delayed data and call the callback when data arrives.
    """
    import threading
    import time
    from ax_devil_rtsp.rtsp_data_retrievers import RtspDataRetriever
    video_callback_called = threading.Event()
    def video_callback(payload):
        video_callback_called.set()
    retriever = RtspDataRetriever(rtsp_url="rtsp://test.url/stream", on_video_data=video_callback)
    # Patch the _proc.is_alive method to always return True
    class DummyProc:
        def is_alive(self):
            return True
    retriever._proc = DummyProc()
    retriever._stop_event = threading.Event()
    dispatch_thread = threading.Thread(target=retriever._queue_dispatch_loop)
    dispatch_thread.start()
    time.sleep(0.5)
    retriever._queue.put({"kind": "video", "data": "delayed_data"})
    assert video_callback_called.wait(timeout=2), "Callback was not called after delayed data"
    retriever._stop_event.set()
    dispatch_thread.join(timeout=1)


def test_dispatch_exits_after_max_empty_polls(monkeypatch):
    """
    The dispatch loop should exit after MAX_EMPTY_POLLS when the queue is always empty.
    """
    import threading
    import queue as queue_mod
    from ax_devil_rtsp.rtsp_data_retrievers import RtspDataRetriever
    retriever = RtspDataRetriever(rtsp_url="rtsp://test.url/stream")
    retriever._stop_event = threading.Event()
    # Patch queue.get to always raise queue.Empty
    class AlwaysEmptyQueue:
        def get(self, timeout=None):
            raise queue_mod.Empty()
    retriever._queue = AlwaysEmptyQueue()
    # Patch _proc to look alive
    class DummyProc:
        def is_alive(self):
            return True
    retriever._proc = DummyProc()
    # Patch logger.debug to record calls
    debug_calls = []
    def fake_debug(msg):
        debug_calls.append(msg)
    monkeypatch.setattr("ax_devil_rtsp.rtsp_data_retrievers.logger.debug", fake_debug)
    # Run dispatch loop (should exit after ~2s)
    dispatch_thread = threading.Thread(target=retriever._queue_dispatch_loop)
    dispatch_thread.start()
    dispatch_thread.join(timeout=3)
    assert not dispatch_thread.is_alive(), "Dispatch loop did not exit after max empty polls"
    # Check that the excessive empty polls message was logged
    assert any("excessive empty polls" in str(msg) for msg in debug_calls), "Did not log excessive empty polls" 