import time
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever

def test_context_manager_exception_handling():
    """
    Test that resources are cleaned up even if an exception occurs in the context.
    """
    retriever = RtspVideoDataRetriever(
        rtsp_url="rtsp://test.url/stream",
        connection_timeout=10
    )
    # Test that exception doesn't prevent cleanup
    try:
        with retriever:
            assert retriever.is_running
            # Simulate an exception
            raise ValueError("Test exception")
    except ValueError:
        pass  # Expected
    # Should still be stopped after exception
    assert not retriever.is_running 