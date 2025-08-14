"""
Main GStreamer RTSP client implementation.
"""

from __future__ import annotations
from ..logging import get_logger
from .pipeline import PipelineSetupMixin
from .diagnostics import DiagnosticMixin
from .callbacks import CallbackHandlerMixin
from gi.repository import Gst, GLib

import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")


logger = get_logger("gstreamer.client")


class CombinedRTSPClient(CallbackHandlerMixin, DiagnosticMixin, PipelineSetupMixin):
    """Unified RTSP client with video and application data callbacks."""

    def __init__(
        self,
        rtsp_url: str,
        *,
        latency: int = 100,
        video_frame_callback: Optional[Callable[[
            Dict[str, Any]], None]] = None,
        application_data_callback: Optional[Callable[[
            Dict[str, Any]], None]] = None,
        stream_session_metadata_callback: Optional[Callable[[
            Dict[str, Any]], None]] = None,
        error_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        video_processing_fn: Optional[Callable[[
            Dict[str, Any], dict], Any]] = None,
        shared_config: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> None:
        # Initialize all mixins
        CallbackHandlerMixin.__init__(self)
        DiagnosticMixin.__init__(self)
        PipelineSetupMixin.__init__(self)

        self.rtsp_url = rtsp_url
        self.latency = latency
        self.video_frame_cb = video_frame_callback
        self.application_data_cb = application_data_callback
        self.session_md_cb = stream_session_metadata_callback
        self.error_cb = error_callback
        self.video_proc_fn = video_processing_fn
        self.shared_cfg = shared_config or {}

        self.video_branch_enabled = video_frame_callback is not None or video_processing_fn is not None
        self.application_data_branch_enabled = application_data_callback is not None

        # Initialize GStreamer
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("combined_pipeline")
        if not self.pipeline:
            raise RuntimeError("Failed to create GStreamer pipeline")

        self._setup_elements()
        self._setup_bus()

        self._timeout = timeout
        self._timer: Optional[threading.Timer] = None

    def start(self) -> None:
        """Start the GStreamer pipeline and main loop."""
        logger.info("Starting CombinedRTSPClient")
        self.start_time = time.time()
        logger.debug("Setting pipeline state to PLAYING")
        state_change_result = self.pipeline.set_state(Gst.State.PLAYING)
        logger.debug(f"Pipeline state change result: {state_change_result}")
        
        if state_change_result == Gst.StateChangeReturn.FAILURE:
            logger.error("Unable to set pipeline to PLAYING state")
            raise RuntimeError("Unable to set pipeline to PLAYING state")
        elif state_change_result == Gst.StateChangeReturn.SUCCESS:
            logger.debug("Pipeline state changed to PLAYING immediately")
        elif state_change_result == Gst.StateChangeReturn.ASYNC:
            logger.debug("Pipeline state change to PLAYING is asynchronous")
        elif state_change_result == Gst.StateChangeReturn.NO_PREROLL:
            logger.debug("Pipeline state change to PLAYING completed but no preroll")
        else:
            logger.debug(f"Unknown pipeline state change result: {state_change_result}")
        try:
            if self._timeout:
                logger.debug(f"Starting with {self._timeout}s timeout")
                self._timer = threading.Timer(
                    self._timeout, self._timeout_handler)
                self._timer.start()
            self.loop.run()
            logger.debug("Main loop exited")
        except Exception as e:
            self._report_error("Main Loop", f"Main loop error: {e}", e)
            self.stop()
        finally:
            logger.debug("CombinedRTSPClient.start() exiting")

    def stop(self) -> None:
        """Stop the GStreamer pipeline and quit the loop."""
        logger.info("Stopping CombinedRTSPClient")
        
        # Cancel timeout timer if it exists
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
            
        logger.debug("Setting pipeline state to NULL")
        state_change_result = self.pipeline.set_state(Gst.State.NULL)
        logger.debug(f"Pipeline state change to NULL result: {state_change_result}")
        
        if state_change_result == Gst.StateChangeReturn.FAILURE:
            logger.warning("Failed to set pipeline state to NULL")
        elif state_change_result == Gst.StateChangeReturn.SUCCESS:
            logger.debug("Pipeline state changed to NULL successfully")
        elif state_change_result == Gst.StateChangeReturn.ASYNC:
            logger.debug("Pipeline state change to NULL is asynchronous")
        else:
            logger.debug(f"Pipeline state change to NULL result: {state_change_result}")
        if self.loop.is_running():
            logger.debug("Quitting main loop")
            self.loop.quit()
        else:
            logger.debug("Main loop is not running")

    def __enter__(self) -> "CombinedRTSPClient":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()
