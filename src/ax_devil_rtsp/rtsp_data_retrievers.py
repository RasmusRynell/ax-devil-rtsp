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
    
    current_pid = os.getpid()
    parent_pid = os.getppid()
    logger.debug(f"Client subprocess started: PID={current_pid}, Parent PID={parent_pid}, URL={rtsp_url}")
    logger.debug(f"Process config: latency={latency}ms, timeout={connection_timeout}s, video={enable_video}, app_data={enable_application}")
    
    client_should_stop = threading.Event()

    def parent_monitor_thread():
        """Daemon thread: shuts down client if parent process dies."""
        monitor_thread_id = threading.get_ident()
        logger.debug(f"Parent monitor thread started: TID={monitor_thread_id}, monitoring parent PID={parent_pid}")
        check_count = 0
        while not client_should_stop.is_set():
            current_parent = os.getppid()
            if current_parent != parent_pid:
                logger.error(f"Parent process changed: original={parent_pid}, current={current_parent}. Shutting down client.")
                try:
                    client.stop()
                except Exception as e:
                    logger.debug(f"Exception during emergency client stop: {e}")
                logger.debug(f"Monitor thread exiting after {check_count} checks")
                sys.exit(0)
            check_count += 1
            if check_count % 10 == 0:  # Log every 10 seconds
                logger.debug(f"Parent monitor check #{check_count}: parent still alive (PID={parent_pid})")
            time.sleep(1)

    try:
        # Validate GI/GStreamer availability in the subprocess for clear user feedback
        logger.debug("Validating GI/GStreamer availability in subprocess")
        ensure_gi_ready()
        logger.info(f"CombinedRTSPClient subprocess starting for {rtsp_url}")
        logger.debug(f"GI/GStreamer validation successful in PID={current_pid}")
        # Import here to avoid top-level GI dependency at library import time
        from .gstreamer import CombinedRTSPClient

        def video_cb(payload):
            queue.put({"kind": "video", **payload})

        def application_data_cb(payload):
            queue.put({"kind": "application_data", **payload})

        def session_cb(payload):
            logger.debug(f"Subprocess PID={current_pid}: session_start message")
            queue.put({"kind": "session_start", **payload})

        def error_cb(payload):
            logger.debug(f"Subprocess PID={current_pid}: error message - {payload.get('error_type', 'unknown')}")
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
        logger.debug(f"Parent monitor thread spawned: daemon=True")
        try:
            logger.debug(f"Starting CombinedRTSPClient in subprocess PID={current_pid}")
            client.start()
            logger.debug(f"CombinedRTSPClient finished in subprocess PID={current_pid}")
        finally:
            logger.debug(f"Setting client_should_stop event for subprocess PID={current_pid}")
            client_should_stop.set()
            logger.debug(f"Waiting for monitor thread to stop...")
    except Exception as exc:
        logger.error(f"Exception in CombinedRTSPClient subprocess PID={current_pid}: {exc}")
        logger.debug(f"Full traceback for subprocess PID={current_pid}:", exc_info=True)
        traceback.print_exc()
        
        # Try to get additional system information on crash
        try:
            import psutil
            process = psutil.Process(current_pid)
            memory_info = process.memory_info()
            logger.error(f"Process state at crash - PID={current_pid}, memory={memory_info.rss/(1024*1024):.1f}MB, status={process.status()}")
        except ImportError:
            logger.debug("psutil not available for enhanced crash reporting")
        except Exception as e:
            logger.debug(f"Could not get process info at crash: {e}")
        
        # Optionally, put an error on the queue so the parent sees it
        if queue:
            try:
                queue.put({
                    "kind": "error",
                    "error_type": "Initialization",
                    "message": str(exc),
                    "exception": str(exc),
                    "traceback": traceback.format_exc(),
                    "process_pid": current_pid,
                })
                logger.debug(f"Error message sent to parent via queue from PID={current_pid}")
            except Exception as queue_err:
                logger.error(f"Failed to send error to parent queue: {queue_err}")
        logger.debug(f"Subprocess PID={current_pid} exiting with code 1")
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
        logger.debug(f"Created multiprocessing queue for RTSP retriever: {rtsp_url}")
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
        self._last_known_alive = False  # Track process state transitions
        logger.debug(f"RtspDataRetriever initialized: URL={rtsp_url}, callbacks=(video={on_video_data is not None}, app_data={on_application_data is not None}, error={on_error is not None})")

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
        
        main_pid = os.getpid()
        logger.info("Starting retriever process...")
        logger.debug(f"Main process PID={main_pid}, spawning subprocess for URL: {self._rtsp_url}")
        
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
        
        subprocess_pid = self._proc.pid
        logger.debug(f"Subprocess spawned successfully: PID={subprocess_pid}")
        
        self._queue_thread = threading.Thread(
            target=self._queue_dispatch_loop, daemon=True)
        self._queue_thread.start()
        
        queue_thread_id = self._queue_thread.ident
        logger.debug(f"Queue dispatch thread started: TID={queue_thread_id}, daemon=True")
        logger.info("Retriever process started.")

    def stop(self) -> None:
        """
        Stop the retriever. Terminates the subprocess and queue thread. Safe to call multiple times.
        """
        if self._proc is None:
            logger.debug("Stop called but no process to stop")
            return
            
        subprocess_pid = self._proc.pid if self._proc else "unknown"
        logger.info("Stopping retriever process...")
        logger.debug(f"Stopping subprocess PID={subprocess_pid} and queue thread")
        
        self._stop_event.set()
        logger.debug("Stop event set for queue dispatch thread")
        
        try:
            if self._proc.is_alive():
                logger.debug(f"Terminating subprocess PID={subprocess_pid}")
                self._proc.terminate()
                
                logger.debug(f"Waiting for subprocess PID={subprocess_pid} to join...")
                self._proc.join(timeout=5)
                
                if self._proc.is_alive():
                    logger.warning(f"Subprocess PID={subprocess_pid} did not terminate gracefully, killing")
                    self._proc.kill()
                    self._proc.join(timeout=2)
                    
                if self._proc.exitcode is not None:
                    exit_info = self._interpret_exit_code(self._proc.exitcode)
                    logger.info(f"Subprocess PID={subprocess_pid} exited: {exit_info}")
                    
                    # Only warn on unexpected/abnormal termination
                    if not self._is_normal_termination(self._proc.exitcode):
                        logger.warning(f"Subprocess PID={subprocess_pid} terminated unexpectedly: {exit_info}")
                else:
                    logger.warning(f"Subprocess PID={subprocess_pid} exit code unknown")
            else:
                logger.debug(f"Subprocess PID={subprocess_pid} was already dead")
        finally:
            if self._queue_thread is not None and self._queue_thread.is_alive():
                queue_thread_id = self._queue_thread.ident
                logger.debug(f"Waiting for queue thread TID={queue_thread_id} to join (timeout=2s)")
                self._queue_thread.join(timeout=2)
                if self._queue_thread.is_alive():
                    logger.warning(f"Queue thread TID={queue_thread_id} did not stop within timeout")
                else:
                    logger.debug(f"Queue thread TID={queue_thread_id} stopped successfully")
            
            logger.debug("Cleaning up process and thread references")
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
        thread_id = threading.get_ident()
        logger.debug(f"Queue dispatch thread started: TID={thread_id}")
        
        wait_time_s = 10  # TODO: Move this? make it configurable?
        MAX_EMPTY_POLLS = wait_time_s/self.QUEUE_POLL_INTERVAL
        consecutive_empty = 0
        total_messages_processed = 0
        message_counts_by_kind = {}
        
        while not self._stop_event.is_set():
            if self._queue is None:
                logger.debug(f"Queue dispatch loop TID={thread_id}: queue is None, exiting")
                break
            try:
                item = self._queue.get(timeout=self.QUEUE_POLL_INTERVAL)
                consecutive_empty = 0  # reset on successful read
                total_messages_processed += 1
                
                # Track message types for debugging
                kind = item.get("kind", "unknown")
                message_counts_by_kind[kind] = message_counts_by_kind.get(kind, 0) + 1
                
                # Periodic stats logging (less frequent)
                if total_messages_processed % 500 == 0:
                    logger.debug(f"Queue processed {total_messages_processed} messages: {message_counts_by_kind}")
                    
            except queue_mod.Empty:
                # No item ready yet. Keep waiting unless the subprocess has exited or we are stopping.
                if self._stop_event.is_set():
                    logger.debug(f"Queue dispatch loop TID={thread_id}: stop event set, exiting")
                    break
                # If the subprocess has died or was never started, exit to avoid busy-loop.
                if self._proc is None or not self._proc.is_alive():
                    subprocess_status = "None" if self._proc is None else "dead"
                    logger.debug(
                        f"Queue polling ended because retriever subprocess is {subprocess_status} (TID={thread_id}).")
                    break
                # Otherwise, continue polling.
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY_POLLS:
                    logger.debug(
                        f"Queue polling ended due to {consecutive_empty} consecutive empty polls (TID={thread_id}).")
                    break
                # Log every 20 empty polls to track queue health
                if consecutive_empty % 20 == 0:
                    logger.debug(f"Queue dispatch TID={thread_id}: {consecutive_empty} consecutive empty polls")
                continue
            except (EOFError, OSError) as e:
                # Queue broken or closed due to process exit; exit the loop.
                logger.debug(
                    f"Queue polling ended due to queue closure or OS error in TID={thread_id}: {e}")
                break
                
            try:
                if kind == "video" and self._on_video_data:
                    self._on_video_data(item)
                elif kind == "application_data" and self._on_application_data:
                    self._on_application_data(item)
                elif kind == "error" and self._on_error:
                    logger.debug(f"Dispatching error: {item.get('error_type', 'unknown')}")
                    self._on_error(item)
                elif kind == "session_start" and self._on_session_start:
                    logger.debug("Dispatching session_start callback")
                    self._on_session_start(item)
                else:
                    logger.debug(f"No handler for message kind '{kind}'")
            except Exception as exc:
                logger.error(
                    f"Exception in user callback for kind '{kind}' (TID={thread_id}): {exc}", exc_info=True)
        
        logger.debug(f"Queue dispatch loop exiting: processed {total_messages_processed} messages, stats: {message_counts_by_kind}")

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

    def _is_normal_termination(self, exit_code: int) -> bool:
        """Check if exit code represents normal/expected termination."""
        if exit_code == 0:
            return True  # Successful completion
        elif exit_code < 0:
            # Negative exit codes are signals
            sig_num = abs(exit_code)
            # Normal termination signals
            normal_signals = {
                2,   # SIGINT - Interrupt from keyboard (Ctrl+C)
                15,  # SIGTERM - Normal termination request
            }
            return sig_num in normal_signals
        else:
            return False  # Positive exit codes are application errors
    
    def _interpret_exit_code(self, exit_code: int) -> str:
        """Interpret process exit code and provide detailed information."""
        if exit_code == 0:
            return "code=0 (SUCCESS)"
        elif exit_code > 0:
            return f"code={exit_code} (ERROR - application exit)"
        else:
            # Negative exit code indicates termination by signal
            sig_num = abs(exit_code)
            signal_name = "UNKNOWN"
            signal_desc = "Unknown signal"
            
            # Common signals that cause process termination
            signal_map = {
                1: ("SIGHUP", "Hangup detected on controlling terminal"),
                2: ("SIGINT", "Interrupt from keyboard (Ctrl+C)"),
                3: ("SIGQUIT", "Quit from keyboard (Ctrl+\\)"),
                4: ("SIGILL", "Illegal instruction"),
                5: ("SIGTRAP", "Trace/breakpoint trap"),
                6: ("SIGABRT", "Abort signal - program called abort()"),
                7: ("SIGBUS", "Bus error - invalid memory access"),
                8: ("SIGFPE", "Floating-point exception"),
                9: ("SIGKILL", "Kill signal - process terminated forcefully"),
                10: ("SIGUSR1", "User-defined signal 1"),
                11: ("SIGSEGV", "Segmentation fault - invalid memory reference"),
                12: ("SIGUSR2", "User-defined signal 2"),
                13: ("SIGPIPE", "Broken pipe - write to pipe with no readers"),
                14: ("SIGALRM", "Alarm clock"),
                15: ("SIGTERM", "Termination signal"),
            }
            
            if sig_num in signal_map:
                signal_name, signal_desc = signal_map[sig_num]
            
            return f"code={exit_code} (SIGNAL {sig_num}: {signal_name} - {signal_desc})"
    
    @property
    def is_running(self) -> bool:
        """
        Returns True if the retriever is running.
        """
        is_alive = self._proc is not None and self._proc.is_alive()
        if logger.isEnabledFor(logging.DEBUG):
            proc_pid = self._proc.pid if self._proc else "None"
            thread_alive = self._queue_thread is not None and self._queue_thread.is_alive()
            thread_id = self._queue_thread.ident if self._queue_thread else "None"
            
            # Include exit code information if process is dead and detect state transitions
            exit_info = ""
            if self._proc and not is_alive and self._proc.exitcode is not None:
                exit_info = f", {self._interpret_exit_code(self._proc.exitcode)}"
                # Check for unexpected termination
                if hasattr(self, '_last_known_alive') and self._last_known_alive:
                    if not self._is_normal_termination(self._proc.exitcode):
                        logger.warning(f"Subprocess PID={proc_pid} terminated unexpectedly: {self._interpret_exit_code(self._proc.exitcode)}")
                    else:
                        logger.debug(f"Subprocess PID={proc_pid} terminated normally: {self._interpret_exit_code(self._proc.exitcode)}")
                    self._last_known_alive = False
            elif is_alive and hasattr(self, '_last_known_alive'):
                self._last_known_alive = True
            
            logger.debug(f"is_running check: subprocess PID={proc_pid} alive={is_alive}{exit_info}, queue thread TID={thread_id} alive={thread_alive}")
        return is_alive


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
