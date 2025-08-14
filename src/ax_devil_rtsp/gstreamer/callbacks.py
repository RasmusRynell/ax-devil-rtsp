"""
Callback handling functionality for GStreamer RTSP operations.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..logging import get_logger

logger = get_logger("gstreamer.callbacks")

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtp", "1.0")
from gi.repository import Gst, GstRtp

from ..utils import parse_session_metadata
from .utils import _map_buffer, _to_rgb_array



class CallbackHandlerMixin:
    """Mixin class providing callback handling functionality."""
    
    def __init__(self):
        # These should be set by the concrete class
        self.video_frame_cb: Optional[callable] = None
        self.application_data_cb: Optional[callable] = None
        self.session_md_cb: Optional[callable] = None
        self.error_cb: Optional[callable] = None
        self.video_proc_fn: Optional[callable] = None
        self.shared_cfg: Dict[str, Any] = {}
        self.latest_rtp_data: Optional[Dict[str, Any]] = None
        self._xml_acc: bytearray = bytearray()
        self._timer: Optional[threading.Timer] = None
        self._timeout: Optional[float] = None

    def _on_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        """Handle GStreamer bus messages."""
        if msg.type == Gst.MessageType.EOS:
            logger.info("EOS received")
            self.stop()
        elif msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            self._report_error("GStreamer Error", f"{err.message} | {dbg}")

    def _on_pad_added(self, _src: Gst.Element, pad: Gst.Pad) -> None:
        """Handle dynamic pad addition from RTSP source."""
        caps = pad.get_current_caps()
        logger.debug(f"Pad added: {pad.get_name()}, caps: {caps.to_string() if caps else 'None'}")
        if not caps:
            return
        struct = caps.get_structure(0)
        if struct.get_name() != "application/x-rtp":
            return

        media = struct.get_string("media") or ""
        if media.lower() == "application":
            if self.application_data_branch_enabled:
                self._ensure_application_data_branch()
                sink_pad = self.m_jit.get_static_pad('sink') if self.m_jit else None
            else:
                sink_pad = None
        else:
            if self.video_branch_enabled:
                sink_pad = self.v_depay.get_static_pad('sink') if self.v_depay else None
            else:
                sink_pad = None

        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

        if self._timer is not None:
            logger.debug("Timeout timer stopped")
            self._timer.cancel()

        if self.session_md_cb:
            self.session_md_cb(parse_session_metadata({
                'stream_name': pad.get_name(),
                'caps': caps.to_string(),
                'structure': struct.to_string()
            }))

    def _on_sdes_notify(self, src: Gst.Element, _pspec) -> None:
        """Handle SDES notifications from RTSP source."""
        struct = src.get_property('sdes')
        if isinstance(struct, Gst.Structure) and self.session_md_cb:
            self.session_md_cb({
                'sdes': {k: struct.get_value(k) for k in struct.keys()}
            })

    def _rtp_probe(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        """Probe RTP packets for extension data."""
        self._timers['rtp_probe'] = time.time()
        buf = info.get_buffer()
        if not buf:
            return Gst.PadProbeReturn.OK

        ok, rtp_buf = GstRtp.RTPBuffer.map(buf, Gst.MapFlags.READ)
        if not ok:
            self._report_error("RTP Buffer", "Failed to map RTP buffer")
            return Gst.PadProbeReturn.OK

        try:
            ext = GstRtp.RTPBuffer.get_extension_data(rtp_buf)
            if not ext:
                return Gst.PadProbeReturn.OK
            ext_data, ext_id = ext
            if ext_id != 0xABAC:
                return Gst.PadProbeReturn.OK

            payload = getattr(ext_data, 'get_data', lambda: ext_data)()
            if not payload or len(payload) < 12:
                return Gst.PadProbeReturn.OK

            n_sec = int.from_bytes(payload[0:4], 'big')
            n_frac = int.from_bytes(payload[4:8], 'big')
            flags = int.from_bytes(payload[8:12], 'big')
            unix_ts = n_sec - 2208988800 + n_frac / (1 << 32)
            human_time = datetime.fromtimestamp(unix_ts, timezone.utc)
            self.latest_rtp_data = {
                'human_time': human_time.strftime("%Y-%m-%d %H:%M:%S.%f UTC"),
                'ntp_seconds': n_sec,
                'ntp_fraction': n_frac,
                'C': (flags >> 31) & 1,
                'E': (flags >> 30) & 1,
                'D': (flags >> 29) & 1,
                'T': (flags >> 28) & 1,
                'CSeq': flags & 0xFF
            }
        finally:
            GstRtp.RTPBuffer.unmap(rtp_buf)
        return Gst.PadProbeReturn.OK

    def _on_new_video_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """Handle new video sample from the video sink."""
        logger.debug("Received new video sample")
        self._timers['vid_sample'] = time.time()
        sample = sink.emit('pull-sample')
        if not sample:
            self._report_error("Video Sample", "No sample received from video sink")
            return Gst.FlowReturn.ERROR
        self.video_cnt += 1

        buf = sample.get_buffer()
        ok, info = _map_buffer(buf)
        if not ok:
            self._report_error("Video Buffer", "Failed to map video buffer")
            return Gst.FlowReturn.ERROR

        struct = sample.get_caps().get_structure(0)
        width = struct.get_value('width')
        height = struct.get_value('height')
        fmt = struct.get_string('format')
        
        # TODO: Do this fix in some better way. Also why in the world fmt can be RBG but the image is still bgr...
        fmt = "BGR"
        
        try:
            frame = _to_rgb_array(info, width, height, fmt)
        except Exception as e:
            self._report_error("Frame Parse", f"Frame parsing failed: {e}", e)
            buf.unmap(info)
            return Gst.FlowReturn.ERROR
        buf.unmap(info)

        payload = {
            'data': frame,
            'latest_rtp_data': self.latest_rtp_data,
        }

        if self.video_proc_fn:
            start = time.time()
            try:
                payload['data'] = self.video_proc_fn(payload, self.shared_cfg)
            except Exception as e:
                self._report_error("Video Processing", f"User processing function failed: {e}", e)
            self._timers['vid_proc'] = time.time() - start

        payload['diagnostics'] = self._video_diag()
        if self.video_frame_cb:
            logger.debug(f"Calling video_frame_cb (count={self.video_cnt})")
            start = time.time()
            try:
                self.video_frame_cb(payload)
            except Exception as e:
                self._report_error("Video Callback", f"Video frame callback failed: {e}", e)
            self._timers['vid_cb'] = time.time() - start

        return Gst.FlowReturn.OK

    def _on_new_application_data_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """Handle new application data sample from the application data sink."""
        logger.debug("Received new application data sample")
        sample = sink.emit('pull-sample')
        if not sample:
            self._report_error("Application Data Sample", "No sample received from application data sink")
            return Gst.FlowReturn.ERROR
        self.application_data_cnt += 1
        
        buf = sample.get_buffer()
        ok, info = _map_buffer(buf)
        if not ok:
            self._report_error("Application Data Buffer", "Failed to map application data buffer")
            return Gst.FlowReturn.ERROR

        raw = bytes(info.data)
        buf.unmap(info)

        if len(raw) < 12:
            self._report_error("RTP Header", "RTP packet too short (< 12 bytes)")
            return Gst.FlowReturn.ERROR
        csrc = raw[0] & 0x0F
        hdr_len = 12 + 4 * csrc
        if len(raw) < hdr_len:
            self._report_error("RTP Header", f"Incomplete RTP header: expected {hdr_len} bytes, got {len(raw)}")
            return Gst.FlowReturn.ERROR
        marker = bool(raw[1] & 0x80)
        self._xml_acc.extend(raw[hdr_len:])

        if not marker:
            return Gst.FlowReturn.OK

        start = self._xml_acc.find(b"<")
        if start < 0:
            self._report_error("XML Parse", "XML start marker '<' not found in accumulated data")
            self._xml_acc = bytearray()
            return Gst.FlowReturn.OK

        try:
            xml = self._xml_acc[start:].decode('utf-8')
        except Exception as e:
            self._report_error("XML Decode", f"Failed to decode XML: {e}", e)
            self._xml_acc = bytearray()
            return Gst.FlowReturn.OK

        self.xml_cnt += 1
        self._xml_acc = bytearray()
        payload = {'data': xml, 'diagnostics': self._application_data_diag()}
        if self.application_data_cb:
            logger.debug(f"Calling application_data_cb (count={self.application_data_cnt})")
            try:
                self.application_data_cb(payload)
            except Exception as e:
                self._report_error("Application Data Callback", f"Application data callback failed: {e}", e)
        return Gst.FlowReturn.OK

    def _timeout_handler(self) -> None:
        """Handle timeout by stopping client."""
        logger.warning(f"Timeout reached ({self._timeout}s), stopping client")
        self._report_error("Timeout", f"Connection timed out in {self._timeout}s")
        self.stop() 