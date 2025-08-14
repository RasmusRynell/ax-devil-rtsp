"""
Diagnostic and error reporting functionality for GStreamer RTSP operations.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Any, Dict, Optional

from ..logging import get_logger

logger = get_logger("gstreamer.diagnostics")


class DiagnosticMixin:
    """Mixin class providing diagnostic and error reporting functionality."""

    def __init__(self):
        # Diagnostic counters and state
        self.start_time: Optional[float] = None
        self.err_cnt = 0
        self.video_cnt = 0
        self.application_data_cnt = 0
        self.xml_cnt = 0
        self._timers: Dict[str, Optional[float]] = dict(
            rtp_probe=None, vid_sample=None, vid_proc=None, vid_cb=None
        )
        # Error callback should be set by the concrete class
        self.error_cb: Optional[callable] = None

    def _video_diag(self) -> Dict[str, Any]:
        """Generate video diagnostic information."""
        return {
            'video_sample_count': self.video_cnt,
            'time_rtp_probe': self._timers['rtp_probe'],
            'time_sample': self._timers['vid_sample'],
            'time_processing': self._timers['vid_proc'],
            'time_callback': self._timers['vid_cb'],
            'error_count': self.err_cnt,
            'uptime': (time.time() - self.start_time) if self.start_time else 0
        }

    def _application_data_diag(self) -> Dict[str, Any]:
        """Generate application data diagnostic information."""
        return {
            'application_data_sample_count': self.application_data_cnt,
            'xml_message_count': self.xml_cnt,
            'error_count': self.err_cnt,
            'uptime': (time.time() - self.start_time) if self.start_time else 0
        }
    
    def _get_current_diagnostics(self) -> Dict[str, Any]:
        """Get current diagnostic state for error context."""
        current_time = time.time()
        return {
            'video_samples': self.video_cnt,
            'application_data_samples': self.application_data_cnt,
            'xml_messages': self.xml_cnt,
            'error_count': self.err_cnt,
            'uptime_seconds': (current_time - self.start_time) if self.start_time else 0,
            'timers': dict(self._timers),
            'timestamp': current_time,
        }

    def _report_error(self, error_type: str, message: str, exception: Optional[Exception] = None) -> None:
        """Report an error through logging, counting, and callback."""
        self.err_cnt += 1
        
        # Enhanced context collection
        current_time = time.time()
        process_id = os.getpid()
        thread_id = threading.get_ident()
        uptime = (current_time - self.start_time) if self.start_time else 0
        
        # Log with enhanced context (PID/TID now automatic in formatters)
        context_info = f"[uptime={uptime:.2f}s, errors={self.err_cnt}]"
        logger.error(f"{context_info} {error_type}: {message}")
        
        # Include full stack trace in debug mode if exception is provided
        if exception and logger.isEnabledFor(10):  # DEBUG level
            logger.debug(f"Full traceback for {error_type}:", exc_info=True)

        if self.error_cb:
            # Enhanced error payload with context
            error_payload = {
                'error_type': error_type,
                'message': message,
                'exception': str(exception) if exception else None,
                'error_count': self.err_cnt,
                'timestamp': current_time,
                'uptime': uptime,
                'process_id': process_id,
                'thread_id': thread_id,
                'diagnostics': self._get_current_diagnostics(),
            }
            
            # Add full traceback if available
            if exception:
                error_payload['traceback'] = ''.join(traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )) if exception.__traceback__ else None
            
            try:
                self.error_cb(error_payload)
            except Exception as cb_error:
                logger.error(f"Error callback failed: {cb_error}", exc_info=True)
