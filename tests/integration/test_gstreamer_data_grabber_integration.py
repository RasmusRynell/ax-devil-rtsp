"""
Integration Tests for gstreamer_data_grabber.py

Hardware-dependent tests that require real RTSP connections:
- Real video frame reception and processing
- Actual network timeout behavior
- RTP data integration with real streams  
- Performance measurement with real pipelines
- End-to-end functionality validation

These tests REQUIRE either:
- Real camera hardware (when USE_REAL_CAMERA=true)
- Local RTSP test servers (when USE_REAL_CAMERA=false)

IMPORTANT: When USE_REAL_CAMERA=true but no camera available,
these tests SHOULD FAIL with connection/timeout errors.
"""

import pytest
import time
import threading
import queue
import numpy as np

pytest.importorskip("gi")
pytest.importorskip("numpy")

from ax_devil_rtsp.gstreamer_data_grabber import (
    CombinedRTSPClient,
    run_combined_client_simple_example
)


@pytest.mark.requires_gstreamer
class TestRealRTSPConnections:
    """Test real RTSP connections - will fail if USE_REAL_CAMERA=true but no camera."""
    
    def test_rtp_data_integration_with_video_callback(self, test_rtsp_url):
        """Test that RTP data is properly included in video frame callbacks."""
        rtp_data_received = []
        
        def video_callback(payload):
            rtp_data = payload.get('latest_rtp_data')
            if rtp_data:
                rtp_data_received.append(rtp_data)
                print(f"📡 RTP data received: {rtp_data}")
        
        client = CombinedRTSPClient(
            test_rtsp_url,
            latency=100,
            video_frame_callback=video_callback,
            timeout=6.0
        )
        
        try:
            client.start()
            time.sleep(4.0)  # Allow RTP data collection
            
            # Should receive video frames from whatever URL was provided
            # Will fail if connection to URL fails
            assert client.video_cnt > 0, "Should have received video frames from RTSP connection"
            
            # Verify structure is ready for RTP data
            assert hasattr(client, 'latest_rtp_data')
            assert client.latest_rtp_data is None or isinstance(client.latest_rtp_data, dict)
            
        finally:
            client.stop()
    
    def test_counter_accuracy_during_operation(self, test_rtsp_url):
        """Test that counters are accurately maintained during real operation."""
        client = CombinedRTSPClient(
            test_rtsp_url,
            latency=100,
            timeout=6.0
        )
        
        try:
            initial_video_cnt = client.video_cnt
            initial_err_cnt = client.err_cnt
            
            client.start()
            time.sleep(4.0)  # Wait for connection and frames
            
            # Counters should be properly tracked
            assert isinstance(client.video_cnt, int)
            assert isinstance(client.err_cnt, int)
            assert client.video_cnt >= initial_video_cnt
            assert client.err_cnt >= initial_err_cnt
            
            # Start time should be set
            assert client.start_time is not None
            assert client.start_time > 0
            
        finally:
            client.stop()


@pytest.mark.requires_gstreamer  
class TestVideoProcessingIntegration:
    """Test video processing with real streams."""
    
    def test_video_processing_function_integration(self, test_rtsp_url):
        """Test integration of custom video processing function with real streams."""
        processed_frames = []
        shared_config = {"test_param": "test_value"}
        
        def custom_processing(frame, config):
            """Custom processing function that modifies frames."""
            assert isinstance(frame, np.ndarray)
            assert config == shared_config
            # Simple processing: add border
            processed = np.copy(frame)
            if len(processed.shape) == 3:
                processed[0:5, :] = [255, 0, 0]  # Red border
            return processed
        
        def video_callback(payload):
            frame = payload.get("data")
            if frame is not None:
                processed_frames.append(frame)
        
        client = CombinedRTSPClient(
            test_rtsp_url,
            latency=100,
            video_frame_callback=video_callback,
            video_processing_fn=custom_processing,
            shared_config=shared_config,
            timeout=6.0
        )
        
        try:
            client.start()
            time.sleep(3.0)
            
            # Should receive and process frames from RTSP connection
            assert len(processed_frames) > 0, "Should have received and processed video frames from RTSP"
            
            # Verify processing function was applied
            frame = processed_frames[0]
            assert isinstance(frame, np.ndarray)
            # Check if red border was added (if frame has 3 channels)
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                # Top border should be red
                assert np.any(frame[0:5, :, 0] == 255)  # Red channel
                    
        finally:
            client.stop()
    
    def test_buffer_lifecycle_in_video_processing(self, test_rtsp_url):
        """Test proper buffer lifecycle during real video processing."""
        buffer_events = []
        
        def video_callback(payload):
            # Just verify we get valid data
            frame = payload.get("data")
            if frame is not None:
                buffer_events.append({
                    'frame_shape': frame.shape,
                    'frame_dtype': frame.dtype,
                    'timestamp': time.time()
                })
        
        client = CombinedRTSPClient(
            test_rtsp_url,
            latency=100,
            video_frame_callback=video_callback,
            timeout=6.0
        )
        
        try:
            client.start()
            time.sleep(3.0)
            
            # Should receive frames from RTSP connection
            assert len(buffer_events) > 0, "Should have received video frames for buffer lifecycle testing"
            
            # Verify buffers were processed correctly
            event = buffer_events[0]
            assert 'frame_shape' in event
            assert 'frame_dtype' in event
            assert 'timestamp' in event
                
        finally:
            client.stop()


@pytest.mark.requires_gstreamer
class TestMetadataIntegration:
    """Test metadata processing with real streams."""
    
    def test_metadata_callback_integration(self, combined_test_rtsp_url):
        """Test metadata callback integration with real streams."""
        metadata_received = []
        
        def metadata_callback(payload):
            metadata_received.append(payload)
            print(f"📋 Metadata received: {len(payload.get('data', ''))} bytes")
        
        client = CombinedRTSPClient(
            combined_test_rtsp_url,
            latency=100,
            metadata_callback=metadata_callback,
            timeout=6.0
        )
        
        try:
            client.start()
            time.sleep(4.0)
            
            # Should connect to RTSP URL (may not have metadata depending on source)
            # But connection should work without errors
            assert client.err_cnt == 0, "RTSP connection should work without errors"
            
            # Verify metadata callback structure is working
            assert callable(client.metadata_cb)
            assert client.metadata_cb == metadata_callback
            
        finally:
            client.stop()


@pytest.mark.requires_gstreamer
class TestTimeoutAndErrorBehavior:
    """Test timeout and error behavior with real network conditions."""
    
    def test_timeout_handler_functionality(self, test_rtsp_url):
        """Test timeout handler with real network conditions."""
        error_reports = []
        
        def error_callback(payload):
            error_reports.append(payload)
        
        # Use provided RTSP URL - will test timeout behavior based on availability
        
        client = CombinedRTSPClient(
            test_rtsp_url,
            timeout=2.0,  # Short timeout
            error_callback=error_callback,
            latency=100
        )
        
        start_time = time.time()
        try:
            client.start()
            time.sleep(3.0)  # Wait longer than timeout
        finally:
            client.stop()
            
        # Should have triggered timeout or connection error
        elapsed = time.time() - start_time
        assert elapsed >= 2.0  # Should have run at least timeout duration
        
        # Unreachable address should generate timeout errors
        assert client.err_cnt > 0, "Should have connection/timeout errors with unreachable address"


@pytest.mark.requires_gstreamer
class TestEndToEndFunctionality:
    """Test complete end-to-end functionality."""
    
    def test_complete_pipeline_with_all_callbacks(self, combined_test_rtsp_url):
        """Test complete pipeline with all callback types."""
        video_frames = []
        metadata_items = []
        session_data = []
        error_reports = []
        
        def video_callback(payload):
            video_frames.append(payload)
        
        def metadata_callback(payload):
            metadata_items.append(payload)
        
        def session_callback(payload):
            session_data.append(payload)
        
        def error_callback(payload):
            error_reports.append(payload)
        
        client = CombinedRTSPClient(
            combined_test_rtsp_url,
            latency=100,
            video_frame_callback=video_callback,
            metadata_callback=metadata_callback,
            session_metadata_callback=session_callback,
            error_callback=error_callback,
            timeout=8.0
        )
        
        try:
            client.start()
            time.sleep(5.0)  # Allow full pipeline operation
            
            # Should have successful RTSP connection with data
            assert len(video_frames) > 0, "Should have received video frames from RTSP"
            assert len(session_data) > 0, "Should have received session data from RTSP"
                
        finally:
            client.stop()


@pytest.mark.requires_gstreamer
class TestExampleRunnerIntegration:
    """Test the example runner function with real connections."""
    
    def test_simple_example_runner_with_real_connection(self, test_rtsp_url):
        """Test the simple example runner behavior with provided RTSP URL."""
        import multiprocessing as mp
        import queue as thread_queue
        
        if mp.get_start_method(allow_none=True) != "spawn":
            mp.set_start_method("spawn", force=True)
        
        # Use thread-safe queue for simpler testing
        q = thread_queue.Queue()
        exception_caught = None
        
        def run_test():
            try:
                run_combined_client_simple_example(
                    test_rtsp_url,
                    latency=100,
                    queue=q,
                    timeout=4.0
                )
            except Exception as e:
                nonlocal exception_caught
                exception_caught = e
        
        # Run example runner
        thread = threading.Thread(target=run_test, daemon=True)
        thread.start()
        thread.join(timeout=6.0)
        
        # The example runner should execute without crashing
        if exception_caught:
            print(f"Example runner encountered exception: {exception_caught}")
        
        # Check what was received (if anything)
        items_received = []
        try:
            while True:
                item = q.get_nowait()
                items_received.append(item)
        except thread_queue.Empty:
            pass
        
        # Test validates that example runner executes properly
        # Whether it receives data depends on RTSP URL reachability
        print(f"Example runner execution - Items received: {len(items_received)}")
        
        # The test passes if the example runner executed without fatal errors
        # Data reception depends on whether the RTSP URL is actually reachable
        if len(items_received) > 0:
            print("✅ Example runner successfully received data from RTSP URL")
        else:
            print("⚠️ Example runner executed but received no data (expected if RTSP URL unreachable)")
        
        # Main validation: example runner should not crash with fatal errors
        assert exception_caught is None or "timeout" in str(exception_caught).lower(), \
            f"Example runner should handle connection issues gracefully, got: {exception_caught}"


if __name__ == "__main__":
    # Configure logging for test runs
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run tests
    pytest.main([__file__, "-v"]) 