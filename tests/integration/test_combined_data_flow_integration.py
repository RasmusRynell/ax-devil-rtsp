"""
Integration test for combined video and application_data data flow.
"""

import threading

from ax_devil_rtsp.rtsp_data_retrievers import RtspDataRetriever
from .utils import wait_for_all


def test_combined_data_flow(rtsp_url):
    """
    Test that RtspDataRetriever can receive both video and application_data simultaneously.
    """
    received_video = []
    received_application_data = []
    errors = []

    video_data_event = threading.Event()
    application_data_event = threading.Event()

    def on_video_data(payload):
        received_video.append(payload)
        video_data_event.set()

    def on_application_data(payload):
        received_application_data.append(payload)
        application_data_event.set()

    def on_error(payload):
        errors.append(payload)

    retriever = RtspDataRetriever(
        rtsp_url=rtsp_url,
        on_video_data=on_video_data,
        on_application_data=on_application_data,
        on_error=on_error,
        connection_timeout=10
    )

    assert not retriever.is_running
    retriever.start()
    assert retriever.is_running

    success = wait_for_all([video_data_event, application_data_event], timeout=60)

    retriever.stop()
    assert not retriever.is_running

    assert success, "Timed out waiting for both video and application_data"

    assert received_video, "Should have received at least one video frame"
    assert received_application_data, "Should have received at least one application_data frame"

    video_frame = received_video[0]
    assert video_frame.get("kind") == "video", "Video frame should have 'kind': 'video'"

    application_data_frame = received_application_data[0]
    assert application_data_frame.get("kind") == "metadata", "Application data frame should have 'kind': 'metadata'"

    assert not errors, f"Unexpected errors: {errors}"
