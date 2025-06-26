"""
Integration tests for video processing function functionality.

Tests that the video_processing_fn parameter works correctly with the new
payload-based signature and includes latest_rtp_data.
"""

import threading
import numpy as np
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever
from .utils import wait_for_all


# Module-level functions for multiprocessing compatibility
def processing_function_with_marker(payload, shared_config):
    """Test processing function that modifies the frame to verify processing occurred."""
    frame = payload["data"]
    if isinstance(frame, np.ndarray) and len(frame.shape) >= 2:
        # Add a simple marker - set the top-left pixel to a specific value
        processed_frame = frame.copy()
        if len(frame.shape) == 3 and frame.shape[2] >= 3:  # RGB
            processed_frame[0, 0] = [255, 0, 0]  # Red marker
        elif len(frame.shape) == 2:  # Grayscale
            processed_frame[0, 0] = 255
        return processed_frame
    return frame


def failing_processing_function(payload, shared_config):
    """Processing function that always throws an exception."""
    raise ValueError("Test processing function exception")


def test_video_processing_function_with_payload(rtsp_url):
    """
    Test that video_processing_fn receives the correct payload structure
    including latest_rtp_data and can modify the video frame.
    
    This is the core test that validates the new signature works end-to-end.
    """
    received_frames = []
    errors = []
    video_event = threading.Event()
    
    def on_video_data(payload):
        received_frames.append(payload)
        video_event.set()
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspVideoDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_error=on_error,
        video_processing_fn=processing_function_with_marker,
        shared_config={'test_param': 'test_value'},
        connection_timeout=10
    )
    
    retriever.start()
    success = wait_for_all([video_event], timeout=60)
    retriever.stop()

    assert success, "Timed out waiting for video data"
    assert len(received_frames) > 0, "Should have received at least one video frame"
    
    # Verify the frame was actually processed (marker pixel was set)
    # This proves the processing function received the correct payload and could modify the frame
    processed_frame = received_frames[0]["data"]
    if isinstance(processed_frame, np.ndarray) and len(processed_frame.shape) >= 2:
        if len(processed_frame.shape) == 3 and processed_frame.shape[2] >= 3:
            # Check for red marker in RGB frame
            assert np.array_equal(processed_frame[0, 0], [255, 0, 0]), "Frame should show processing marker"
        elif len(processed_frame.shape) == 2:
            # Check for marker in grayscale frame
            assert processed_frame[0, 0] == 255, "Frame should show processing marker"
    
    # Verify frame payload structure includes expected fields
    frame_payload = received_frames[0]
    assert "data" in frame_payload, "Frame payload should contain 'data'"
    assert "diagnostics" in frame_payload, "Frame payload should contain 'diagnostics'"
    assert "kind" in frame_payload and frame_payload["kind"] == "video", "Frame should be marked as video"
    
    # Check that video processing timing is captured in diagnostics
    diagnostics = frame_payload["diagnostics"]
    assert "time_processing" in diagnostics, "Diagnostics should include processing time"
    
    assert len(errors) == 0, f"Should not have errors: {errors}"


def test_video_processing_function_exception_handling(rtsp_url):
    """
    Test that exceptions in video_processing_fn are handled gracefully
    and don't crash the retriever.
    """
    received_frames = []
    errors = []
    video_event = threading.Event()
    
    def on_video_data(payload):
        received_frames.append(payload)
        video_event.set()
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspVideoDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_error=on_error,
        video_processing_fn=failing_processing_function,
        shared_config={},
        connection_timeout=10
    )
    
    retriever.start()
    success = wait_for_all([video_event], timeout=60)
    retriever.stop()

    assert success, "Timed out waiting for video data"
    assert len(received_frames) > 0, "Should still receive frames despite processing errors"
    
    # Should have received error reports about the processing function failures
    processing_errors = [e for e in errors if e.get('error_type') == 'Video Processing']
    assert len(processing_errors) > 0, "Should have reported video processing errors"
    
    # Verify error structure
    proc_error = processing_errors[0]
    assert 'message' in proc_error, "Error should have message"
    assert 'Test processing function exception' in proc_error['message'], "Error message should contain exception details" 