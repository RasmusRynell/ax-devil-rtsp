"""
Integration test for application data (AXIS scene metadata) data flow with RtspApplicationDataRetriever.
"""

import threading

from ax_devil_rtsp.rtsp_data_retrievers import RtspApplicationDataRetriever
from .utils import wait_for_all


def test_application_data_data_flow(rtsp_url):
    """
    Test that RtspApplicationDataRetriever receives application data and manages resources.
    """
    received_application_data = []
    errors = []

    application_data_event = threading.Event()
    
    def on_application_data(payload):
        received_application_data.append(payload)
        application_data_event.set()
    
    def on_error(payload):
        errors.append(payload)
    
    retriever = RtspApplicationDataRetriever(
        rtsp_url=rtsp_url,
        on_application_data=on_application_data,
        on_error=on_error,
        connection_timeout=10
    )
    
    # Test basic lifecycle
    assert not retriever.is_running
    
    retriever.start()
    assert retriever.is_running
    
    # Wait for application_data (give enough time for connection and initial application_data)
    success = wait_for_all([application_data_event], timeout=60)

    retriever.stop()
    assert not retriever.is_running
    
    assert success, "Timed out waiting for application_data"

    # Verify we received at least one application_data frame
    assert len(received_application_data) > 0, "Should have received at least one application_data frame"
    
    # Verify application_data structure
    application_data = received_application_data[0]
    assert "kind" in application_data
    assert application_data["kind"] == "application_data"
    
    # Should not have errors in normal operation
    assert len(errors) == 0, f"Unexpected errors: {errors}"
