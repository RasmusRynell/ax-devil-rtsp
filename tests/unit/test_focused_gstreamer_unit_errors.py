"""
Focused Unit Error Tests for GStreamer Data Grabber

Unit tests for error conditions that don't require network connections:
- GStreamer pipeline creation failures
- Missing GStreamer elements
- Mocked dependency failures

These tests ALWAYS PASS regardless of hardware/network availability.
"""

import pytest
import unittest.mock

pytest.importorskip("gi")

from ax_devil_rtsp.gstreamer_data_grabber import CombinedRTSPClient


@pytest.mark.requires_gstreamer
def test_pipeline_creation_error():
    """Test error handling when GStreamer pipeline creation fails."""
    # Mock Gst.Pipeline.new to return None (simulating pipeline creation failure)
    with unittest.mock.patch('gi.repository.Gst.Pipeline.new', return_value=None):
        try:
            client = CombinedRTSPClient("rtsp://test.com/stream")
            pytest.fail("Should have raised RuntimeError for pipeline creation failure")
        except RuntimeError as e:
            assert "Failed to create GStreamer pipeline" in str(e)
            print("✅ Pipeline creation failure properly detected")


@pytest.mark.requires_gstreamer
def test_element_creation_error():
    """Test error handling when required GStreamer elements cannot be created."""
    # Mock ElementFactory.make to return None for rtspsrc (simulating missing element)
    def mock_make(element_name, name=None):
        if element_name == "rtspsrc":
            return None
        # Allow other elements to be created normally
        return unittest.mock.MagicMock()
    
    with unittest.mock.patch('gi.repository.Gst.ElementFactory.make', side_effect=mock_make):
        try:
            client = CombinedRTSPClient("rtsp://test.com/stream")
            pytest.fail("Should have raised RuntimeError for missing rtspsrc element")
        except RuntimeError as e:
            assert "Unable to create rtspsrc element" in str(e)
            print("✅ Missing element properly detected") 