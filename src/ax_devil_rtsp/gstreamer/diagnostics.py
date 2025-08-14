"""
Diagnostic and error reporting functionality for GStreamer RTSP operations.
"""

from __future__ import annotations

import time
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

    def _report_error(self, error_type: str, message: str, exception: Optional[Exception] = None) -> None:
        """Report an error through logging, counting, and callback."""
        self.err_cnt += 1
        logger.error(f"gstreamer_data_grabber got error: {error_type}: {message}")
        
        if self.error_cb:
            error_payload = {
                'error_type': error_type,
                'message': message,
                'exception': str(exception) if exception else None,
                'error_count': self.err_cnt,
                'timestamp': time.time(),
                'uptime': (time.time() - self.start_time) if self.start_time else 0
            }
            try:
                self.error_cb(error_payload)
            except Exception as cb_error:
                logger.error("Error callback failed: %s", cb_error) 