"""
Focused Success Tests for GStreamer Data Grabber

Small number of effective tests that:
1. Validate successful connections work properly
2. Test real video/metadata processing
3. Ensure proper resource cleanup
4. Provide meaningful success validation
"""

import pytest
import time
import threading
import queue
import numpy as np

pytest.importorskip("gi")
pytest.importorskip("numpy")

from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient
from ax_devil_rtsp.examples.video_gstreamer import VideoGStreamerClient


@pytest.mark.requires_gstreamer
def test_successful_video_connection(test_rtsp_url):
    """Test successful video connection and frame reception.
    
    This test should PASS when camera is available and working.
    """
    frames_received = []
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None and len(frames_received) < 3:
            frames_received.append(frame)
            print(f"📹 Frame {len(frames_received)}: {frame.shape} {frame.dtype}")
    
    client = CombinedRTSPClient(
        test_rtsp_url,
        video_frame_callback=video_callback,
        timeout=8.0
    )
    
    try:
        client.start()
        time.sleep(6.0)  # Allow connection and frame reception
        
        # Should successfully connect and receive frames
        assert client.video_cnt > 0, f"Should receive video frames from working camera, got {client.video_cnt}"
        assert len(frames_received) > 0, f"Should have frames in callback, got {len(frames_received)}"
        assert client.err_cnt == 0, f"Successful connection should have no errors, got {client.err_cnt}"
        
        # Validate frame properties
        frame = frames_received[0]
        assert isinstance(frame, np.ndarray), f"Frame should be numpy array, got {type(frame)}"
        assert len(frame.shape) == 3, f"Frame should be 3D (H,W,C), got shape {frame.shape}"
        assert frame.shape[2] in [3, 4], f"Frame should have 3 or 4 channels, got {frame.shape[2]}"
        
        print(f"✅ Successful connection - Frames: {client.video_cnt}, Shape: {frame.shape}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_successful_dual_callback_processing(combined_test_rtsp_url):
    """Test successful dual callback processing with working camera."""
    video_frames = []
    metadata_samples = []
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None and len(video_frames) < 2:
            video_frames.append(frame)
    
    def metadata_callback(payload):
        data = payload.get("data")
        if data is not None and len(metadata_samples) < 2:
            metadata_samples.append(data)
    
    client = CombinedRTSPClient(
        combined_test_rtsp_url,
        video_frame_callback=video_callback,
        metadata_callback=metadata_callback,
        timeout=8.0
    )
    
    try:
        client.start()
        time.sleep(6.0)  # Allow connection and processing
        
        # Should successfully process both streams
        assert client.video_cnt > 0, f"Should receive video from working camera, got {client.video_cnt}"
        assert len(video_frames) > 0, f"Should have video frames, got {len(video_frames)}"
        
        # Metadata may or may not be present depending on camera
        print(f"✅ Dual processing - Video: {len(video_frames)}, Metadata: {len(metadata_samples)}")
        print(f"   Counters - Video: {client.video_cnt}, Meta: {client.meta_cnt}, Errors: {client.err_cnt}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_successful_diagnostics_collection(test_rtsp_url):
    """Test that diagnostics are properly collected during successful operation."""
    client = CombinedRTSPClient(test_rtsp_url, timeout=6.0)
    
    try:
        initial_time = time.time()
        client.start()
        time.sleep(4.0)  # Allow operation
        
        # Should have proper diagnostics
        assert client.start_time is not None, "Start time should be recorded"
        assert client.start_time > initial_time - 1, "Start time should be recent"
        
        video_diag = client._video_diag()
        assert isinstance(video_diag, dict), "Video diagnostics should be dict"
        assert 'video_sample_count' in video_diag, "Should track video samples"
        assert 'uptime' in video_diag, "Should track uptime"
        assert video_diag['uptime'] >= 3.0, f"Should have uptime >= 3s, got {video_diag['uptime']}"
        
        meta_diag = client._meta_diag()
        assert isinstance(meta_diag, dict), "Metadata diagnostics should be dict"
        assert 'metadata_sample_count' in meta_diag, "Should track metadata samples"
        
        print(f"✅ Diagnostics working - Uptime: {video_diag['uptime']:.1f}s")
        print(f"   Video samples: {video_diag['video_sample_count']}, Meta samples: {meta_diag['metadata_sample_count']}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer
def test_successful_processing_function_integration(test_rtsp_url):
    """Test successful custom processing function integration."""
    processed_frames = []
    shared_config = {"processing_enabled": True, "border_color": [255, 0, 0]}
    
    def custom_processing(frame, config):
        """Add red border to frame."""
        assert isinstance(frame, np.ndarray)
        assert config == shared_config
        
        processed = np.copy(frame)
        if len(processed.shape) == 3 and processed.shape[0] > 10:
            # Add red border at top
            processed[0:5, :] = config["border_color"]
        return processed
    
    def video_callback(payload):
        frame = payload.get("data")
        if frame is not None and len(processed_frames) < 2:
            processed_frames.append(frame)
    
    client = CombinedRTSPClient(
        test_rtsp_url,
        video_frame_callback=video_callback,
        video_processing_fn=custom_processing,
        shared_config=shared_config,
        timeout=6.0
    )
    
    try:
        client.start()
        time.sleep(4.0)  # Allow processing
        
        # Should successfully apply processing function
        assert len(processed_frames) > 0, f"Should have processed frames, got {len(processed_frames)}"
        
        frame = processed_frames[0]
        assert isinstance(frame, np.ndarray), "Processed frame should be numpy array"
        
        # Check if processing was applied (red border)
        if len(frame.shape) == 3 and frame.shape[2] == 3 and frame.shape[0] > 10:
            top_border = frame[0:5, :, :]
            # Should have red pixels in border area
            red_pixels = np.sum(top_border[:, :, 0] == 255)
            assert red_pixels > 0, "Processing function should have added red border"
            
        print(f"✅ Processing function working - Frames: {len(processed_frames)}")
        
    finally:
        client.stop()


@pytest.mark.requires_gstreamer  
def test_successful_context_manager_usage(test_rtsp_url):
    """Test successful context manager usage with working camera."""
    frame_received = False
    
    def video_callback(payload):
        nonlocal frame_received
        frame = payload.get("data")
        if frame is not None:
            frame_received = True
            print(f"📹 Frame received in context manager: {frame.shape}")
    
    with CombinedRTSPClient(
        test_rtsp_url, 
        video_frame_callback=video_callback,
        timeout=6.0
    ) as client:
        time.sleep(4.0)  # Allow connection and frame reception
        
        # Should successfully receive frames in context manager
        assert client.video_cnt > 0, f"Should receive frames in context manager, got {client.video_cnt}"
        assert frame_received, "Video callback should have been triggered"
        assert client.err_cnt == 0, f"Context manager should work without errors, got {client.err_cnt}"
    
    print("✅ Context manager working properly")


@pytest.mark.requires_gstreamer
def test_successful_resource_cleanup(test_rtsp_url):
    """Test that resources are properly cleaned up after successful operation."""
    client = CombinedRTSPClient(test_rtsp_url, timeout=5.0)
    
    try:
        client.start()
        time.sleep(3.0)  # Allow operation
        
        # Should be running successfully
        assert client.video_cnt > 0, "Should have received frames during operation"
        assert not client._stop_event.is_set(), "Stop event should not be set during operation"
        
    finally:
        client.stop()
    
    # After stopping, should be properly cleaned up
    assert client._stop_event.is_set(), "Stop event should be set after stopping"
    
    # Pipeline should be in NULL state
    from gi.repository import Gst
    pipeline_state = client.pipeline.get_state(timeout=Gst.SECOND)[1]
    assert pipeline_state == Gst.State.NULL, f"Pipeline should be in NULL state, got {pipeline_state}"
    
    print("✅ Resource cleanup working properly") 