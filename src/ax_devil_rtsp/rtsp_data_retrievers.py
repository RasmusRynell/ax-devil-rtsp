"""
RTSP Data Retriever Classes

This module provides high-level, process-safe retrievers for video and/or application
data from RTSP streams, with a focus on Axis cameras. Use the specialized retrievers for
video-only, application-data-only, or combined retrieval. For Axis-style URLs, use build_axis_rtsp_url.

All retrievers run the GStreamer client in a subprocess and communicate via a thread-safe queue.

See Also:
    - build_axis_rtsp_url (in ax_devil_rtsp.utils)
    - Example usage: see the example file in the repository

Note:
    Always call stop() or use the context manager to ensure resources are cleaned up.
"""

from .logging import get_logger
import multiprocessing as mp
import threading
import queue as queue_mod
from typing import Callable, Optional, Dict, Any, TYPE_CHECKING
from abc import ABC
import os
import traceback
import logging

from .deps import ensure_gi_ready

# IMPORTANT: Always use 'spawn' start method for multiprocessing to ensure
# compatibility between parent and GStreamer subprocesses, and to avoid
# queue breakage or deadlocks. This is required for reliable cross-process
# communication, especially when using GStreamer and Python >=3.8.
mp.set_start_method('spawn', force=True)

RtspPayload = Dict[str, Any]
if TYPE_CHECKING:
    from typing import Protocol

    class VideoDataCallback(Protocol):
        def __call__(self, payload: RtspPayload) -> None: ...

    class ApplicationDataCallback(Protocol):
        def __call__(self, payload: RtspPayload) -> None: ...

    class ErrorCallback(Protocol):
        def __call__(self, payload: RtspPayload) -> None: ...

    class SessionStartCallback(Protocol):
        def __call__(self, payload: RtspPayload) -> None: ...
else:
    VideoDataCallback = Callable[[RtspPayload], None]
    ApplicationDataCallback = Callable[[RtspPayload], None]
    ErrorCallback = Callable[[RtspPayload], None]
    SessionStartCallback = Callable[[RtspPayload], None]


logger = get_logger("rtsp_data_retrievers")

__all__ = [
    "RtspPayload",
    "VideoDataCallback",
    "ApplicationDataCallback",
    "ErrorCallback",
    "SessionStartCallback",
    "RtspDataRetriever",
    "RtspVideoDataRetriever",
    "RtspApplicationDataRetriever",
]


def _client_process(
    rtsp_url: str,
    latency: int,
    queue: mp.Queue,
    video_processing_fn: Optional[Callable],
    shared_config: Optional[dict],
    connection_timeout: Optional[float],
    log_level: int,
    enable_video: bool,
    enable_application: bool,
):
    """
    Subprocess target: Instantiates CombinedRTSPClient and pushes events to the queue.
    Internal use only. Also starts a fallback thread to monitor parent process liveness.
    """
    import sys
    import time
    from .logging import setup_logging
    setup_logging(log_level=log_level)
    parent_pid = os.getppid()
    client_should_stop = threading.Event()

    def parent_monitor_thread():
        """Daemon thread: shuts down client if parent process dies."""
        while not client_should_stop.is_set():
            if os.getppid() != parent_pid:
                logger.error("Parent process exited, shutting down client.")
                try:
                    client.stop()
                except Exception:
                    pass
                sys.exit(0)
            time.sleep(1)

    try:
        # Validate GI/GStreamer availability in the subprocess for clear user feedback
        ensure_gi_ready()
        logger.info(f"CombinedRTSPClient subprocess starting for {rtsp_url}")
        # Import here to avoid top-level GI dependency at library import time
        from .gstreamer import CombinedRTSPClient

        def video_cb(payload):
            queue.put({"kind": "video", **payload})

        def application_data_cb(payload):
            queue.put({"kind": "application_data", **payload})

        def session_cb(payload):
            queue.put({"kind": "session_start", **payload})

        def error_cb(payload):
            queue.put({"kind": "error", **payload})
        client = CombinedRTSPClient(
            rtsp_url,
            latency=latency,
            video_frame_callback=video_cb if enable_video else None,
            application_data_callback=application_data_cb if enable_application else None,
            stream_session_metadata_callback=session_cb,
            error_callback=error_cb,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config or {},
            timeout=connection_timeout,
        )
        monitor = threading.Thread(target=parent_monitor_thread, daemon=True)
        monitor.start()
        try:
            client.start()
        finally:
            client_should_stop.set()
    except Exception as exc:
        logger.error(f"Exception in CombinedRTSPClient subprocess: {exc}")
        traceback.print_exc()
        # Optionally, put an error on the queue so the parent sees it
        if queue:
            queue.put({
                "kind": "error",
                "error_type": "Initialization",
                "message": str(exc),
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            })
        sys.exit(1)


class RtspDataRetriever(ABC):
    """
    Abstract base class for RTSP data retrievers. Manages process and queue thread lifecycle.
    Not intended to be instantiated directly.

    Parameters
    ----------
    rtsp_url : str
        Full RTSP URL.
    on_video_data : VideoDataCallback, optional
        Callback for video frames. Receives a payload dict from CombinedRTSPClient.
    on_application_data : ApplicationDataCallback, optional
        Callback for application data. Receives a payload dict.
    on_error : ErrorCallback, optional
        Callback for errors. Receives a payload dict.
    on_session_start : SessionStartCallback, optional
        Callback for session metadata. Receives a payload dict.
    latency : int, default=200
        GStreamer pipeline latency in ms.
    video_processing_fn : Callable, optional
        Optional function to process video frames in the GStreamer process.
    shared_config : dict, optional
        Optional shared config for the video processing function.
    connection_timeout : int, default=30
        Connection timeout in seconds.
    log_level : int, optional
        Logging level used in the subprocess. Defaults to the parent's
        effective logging level.
    """
    QUEUE_POLL_INTERVAL: float = 0.5  # seconds

    def __init__(
        self,
        rtsp_url: str,
        on_video_data: Optional[VideoDataCallback] = None,
        on_application_data: Optional[ApplicationDataCallback] = None,
        on_error: Optional[ErrorCallback] = None,
        on_session_start: Optional[SessionStartCallback] = None,
        latency: int = 200,
        video_processing_fn: Optional[Callable] = None,
        shared_config: Optional[dict] = None,
        connection_timeout: int = 30,
        log_level: Optional[int] = None,
    ):
        # Reset internal state to avoid stale references if start() is called after a crash
        self._proc: Optional[mp.Process] = None
        # Use a plain mp.Queue() for cross-process communication, as in the working example in gstreamer_data_grabber.py.
        # This is robust and avoids the pitfalls of Manager().Queue() for high-throughput or large data.
        self._queue: mp.Queue = mp.Queue()
        self._queue_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._rtsp_url = rtsp_url
        self._on_video_data = on_video_data
        self._on_application_data = on_application_data
        self._latency = latency
        self._video_processing_fn = video_processing_fn
        self._shared_config = shared_config
        self._connection_timeout = connection_timeout
        self._on_error = on_error
        self._on_session_start = on_session_start
        self._log_level = log_level if log_level is not None else logger.getEffectiveLevel()

    def start(self) -> None:
        """
        Start the retriever. Launches a subprocess for the GStreamer client and a thread to dispatch queue events to callbacks.
        Raises RuntimeError if already started.
        """
        if self._proc is not None and self._proc.is_alive():
            raise RuntimeError("Retriever already started.")
        # Reset internal state to avoid stale references if start() is called after a crash
        self._proc = None
        self._queue_thread = None
        self._stop_event.clear()
        logger.info("Starting retriever process...")
        self._proc = mp.Process(
            target=_client_process,
            args=(
                self._rtsp_url,
                self._latency,
                self._queue,
                self._video_processing_fn,
                self._shared_config,
                self._connection_timeout,
                self._log_level,
                self._on_video_data is not None or self._video_processing_fn is not None,
                self._on_application_data is not None,
            ),
        )
        self._proc.start()
        self._queue_thread = threading.Thread(
            target=self._queue_dispatch_loop, daemon=True)
        self._queue_thread.start()
        logger.info("Retriever process started.")

    def stop(self) -> None:
        """
        Stop the retriever. Terminates the subprocess and queue thread. Safe to call multiple times.
        """
        if self._proc is None:
            return
        logger.info("Stopping retriever process...")
        self._stop_event.set()
        try:
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join()
        finally:
            if self._queue_thread is not None and self._queue_thread.is_alive():
                self._queue_thread.join(timeout=2)
            self._proc = None
            self._queue_thread = None
        logger.info("Retriever process stopped.")

    def close(self) -> None:
        """
        Alias for stop(). Provided for API familiarity with file-like objects.
        """
        self.stop()

    def _queue_dispatch_loop(self) -> None:
        """
        Internal: Thread target. Reads from the queue and dispatches to the correct callback.
        Handles EOFError/OSError gracefully if the parent process is dead.
        Catches and logs exceptions in user callbacks to avoid breaking the loop.
        """
        wait_time_s = 10  # TODO: Move this? make it configurable?
        MAX_EMPTY_POLLS = wait_time_s/self.QUEUE_POLL_INTERVAL
        consecutive_empty = 0
        while not self._stop_event.is_set():
            if self._queue is None:
                break
            try:
                item = self._queue.get(timeout=self.QUEUE_POLL_INTERVAL)
                consecutive_empty = 0  # reset on successful read
            except queue_mod.Empty:
                # No item ready yet. Keep waiting unless the subprocess has exited or we are stopping.
                if self._stop_event.is_set():
                    break
                # If the subprocess has died or was never started, exit to avoid busy-loop.
                if self._proc is None or not self._proc.is_alive():
                    logger.debug(
                        "Queue polling ended because retriever subprocess is not alive.")
                    break
                # Otherwise, continue polling.
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY_POLLS:
                    logger.debug(
                        "Queue polling ended due to excessive empty polls.")
                    break
                continue
            except (EOFError, OSError):
                # Queue broken or closed due to process exit; exit the loop.
                logger.debug(
                    "Queue polling ended due to queue closure or OS error.")
                break
            kind = item.get("kind")
            try:
                if kind == "video" and self._on_video_data:
                    logger.debug("Dispatching video callback.")
                    self._on_video_data(item)
                elif kind == "application_data" and self._on_application_data:
                    logger.debug("Dispatching application data callback.")
                    self._on_application_data(item)
                elif kind == "error" and self._on_error:
                    logger.debug("Dispatching error callback.")
                    self._on_error(item)
                elif kind == "session_start" and self._on_session_start:
                    logger.debug("Dispatching session_start callback.")
                    self._on_session_start(item)
            except Exception as exc:
                logger.error(
                    f"Exception in user callback for kind '{kind}': {exc}", exc_info=True)

    def __enter__(self) -> "RtspDataRetriever":
        """
        Context manager entry. Starts the retriever.
        """
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Context manager exit. Ensures retriever is stopped and resources are cleaned up.
        """
        try:
            self.stop()
        except Exception as e:
            logger.error(f"Error during retriever cleanup: {e}")

    @property
    def is_running(self) -> bool:
        """
        Returns True if the retriever is running.
        """
        return self._proc is not None and self._proc.is_alive()


class RtspVideoDataRetriever(RtspDataRetriever):
    """
    Retrieve only video data from an RTSP stream.
    """

    def __init__(
        self,
        rtsp_url: str,
        on_video_data: Optional[VideoDataCallback] = None,
        on_error: Optional[ErrorCallback] = None,
        on_session_start: Optional[SessionStartCallback] = None,
        latency: int = 200,
        video_processing_fn: Optional[Callable] = None,
        shared_config: Optional[dict] = None,
        connection_timeout: int = 30,
        log_level: Optional[int] = None,
    ):
        super().__init__(
            rtsp_url=rtsp_url,
            on_video_data=on_video_data,
            on_application_data=None,
            on_error=on_error,
            on_session_start=on_session_start,
            latency=latency,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config,
            connection_timeout=connection_timeout,
            log_level=log_level,
        )


class RtspApplicationDataRetriever(RtspDataRetriever):
    """
    Retrieve only application (Axis Scene Description) data from an RTSP stream.
    """

    def __init__(
        self,
        rtsp_url: str,
        on_application_data: Optional[ApplicationDataCallback] = None,
        on_error: Optional[ErrorCallback] = None,
        on_session_start: Optional[SessionStartCallback] = None,
        latency: int = 200,
        video_processing_fn: Optional[Callable] = None,
        shared_config: Optional[dict] = None,
        connection_timeout: int = 30,
        log_level: Optional[int] = None,
    ):
        super().__init__(
            rtsp_url=rtsp_url,
            on_video_data=None,
            on_application_data=on_application_data,
            on_error=on_error,
            on_session_start=on_session_start,
            latency=latency,
            video_processing_fn=video_processing_fn,
            shared_config=shared_config,
            connection_timeout=connection_timeout,
            log_level=log_level,
        )
