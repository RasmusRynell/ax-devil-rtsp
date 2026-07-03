"""
Callback handling functionality for GStreamer RTSP operations.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import gi

from ..utils import parse_session_metadata
from ..utils.logging import get_logger
from .utils import _map_buffer, _to_rgb_array

logger = get_logger(__name__)


gi.require_version("Gst", "1.0")
gi.require_version("GstRtp", "1.0")
from gi.repository import GLib, Gst, GstRtp  # noqa: E402

# Newer PyGObject wraps raw bytes from GstRtp accessors in GLib.Bytes.
_GLIB_BYTES_HAS_GET_DATA = hasattr(GLib.Bytes.new(b""), "get_data")


def _unwrap_glib_bytes(data: Any) -> bytes:
    """Unwrap GLib.Bytes to raw bytes if needed."""
    if _GLIB_BYTES_HAS_GET_DATA and hasattr(data, "get_data"):
        return data.get_data()
    return bytes(data)


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
        self._application_rtp_current_xml: deque[Dict[str, Any]] = deque(maxlen=128)
        self._application_rtp_expected_sequence: Optional[int] = None
        self._application_rtp_current_timestamp: Optional[int] = None
        self._application_rtp_current_corrupt = False
        self._application_rtp_current_drop_reason: Optional[str] = None
        self._application_rtp_sequence_gap_count = 0
        self._application_xml_dropped_by_rtp_loss_count = 0
        self._application_xml_dropped_by_timestamp_resync_count = 0
        self._application_rtp_last_drop: Optional[Dict[str, Any]] = None
        self._timer: Optional[threading.Timer] = None
        self._timeout: Optional[float] = None

    def _reset_application_xml_assembly(self) -> None:
        self._xml_acc = bytearray()
        self._application_rtp_current_xml.clear()
        self._application_rtp_current_timestamp = None
        self._application_rtp_current_corrupt = False
        self._application_rtp_current_drop_reason = None

    def _application_rtp_missing_packet_count(
        self,
        expected_sequence: Optional[int],
        received_sequence: int,
    ) -> Optional[int]:
        if expected_sequence is None:
            return None
        return (received_sequence - expected_sequence) % 65536

    def _payload_starts_application_xml_document(self, payload: bytes) -> bool:
        stripped = payload.lstrip()
        if stripped.startswith(b"\xef\xbb\xbf"):
            stripped = stripped[3:].lstrip()
        if stripped.startswith(b"<?xml"):
            return True
        if not stripped.startswith(b"<") or stripped[1:2] in {b"/", b"!", b"?"}:
            return False

        tag_end = len(stripped)
        for delimiter in (b" ", b"\t", b"\r", b"\n", b"/", b">"):
            delimiter_index = stripped.find(delimiter, 1)
            if delimiter_index >= 0:
                tag_end = min(tag_end, delimiter_index)
        tag_name = stripped[1:tag_end]
        local_name = tag_name.rsplit(b":", 1)[-1]
        return local_name == b"MetadataStream"

    def _drop_application_xml_assembly(
        self,
        reason: str,
        packet: Dict[str, Any],
    ) -> None:
        if reason.startswith("timestamp_changed"):
            self._application_xml_dropped_by_timestamp_resync_count += 1
        else:
            self._application_xml_dropped_by_rtp_loss_count += 1

        expected_sequence = packet.get("expected_sequence_number")
        received_sequence = packet["sequence_number"]
        missing_packets = self._application_rtp_missing_packet_count(
            expected_sequence,
            received_sequence,
        )
        self._application_rtp_last_drop = {
            "reason": reason,
            "expected_sequence": expected_sequence,
            "received_sequence": received_sequence,
            "missing_packets": missing_packets,
            "previous_timestamp": self._application_rtp_current_timestamp,
            "current_timestamp": packet["timestamp"],
            "accumulated_bytes_discarded": len(self._xml_acc),
            "packets_discarded": len(self._application_rtp_current_xml),
            "sequence_gap_count": self._application_rtp_sequence_gap_count,
            "xml_dropped_by_rtp_loss_count": (
                self._application_xml_dropped_by_rtp_loss_count
            ),
            "xml_dropped_by_timestamp_resync_count": (
                self._application_xml_dropped_by_timestamp_resync_count
            ),
        }
        self._report_error(
            "Application RTP Loss",
            "Dropped corrupt application XML assembly "
            f"(reason={reason}, expected_sequence={expected_sequence}, "
            f"received_sequence={received_sequence}, "
            f"missing_packets={missing_packets}, "
            f"previous_timestamp={self._application_rtp_current_timestamp}, "
            f"current_timestamp={packet['timestamp']}, "
            f"accumulated_bytes={len(self._xml_acc)})",
        )
        self._reset_application_xml_assembly()

    def _record_application_rtp_packet(
        self,
        rtp_buf: GstRtp.RTPBuffer,
        payload_bytes: int,
        marker: bool,
    ) -> Dict[str, Any]:
        sequence_number = rtp_buf.get_seq()
        expected_sequence_number = self._application_rtp_expected_sequence
        sequence_gap = (
            expected_sequence_number is not None
            and sequence_number != expected_sequence_number
        )
        if sequence_gap:
            self._application_rtp_sequence_gap_count += 1

        packet = {
            "application_data_sample_count": self.application_data_cnt,
            "sequence_number": sequence_number,
            "expected_sequence_number": expected_sequence_number,
            "sequence_gap": sequence_gap,
            "sequence_gap_count": self._application_rtp_sequence_gap_count,
            "timestamp": rtp_buf.get_timestamp(),
            "ssrc": rtp_buf.get_ssrc(),
            "payload_type": rtp_buf.get_payload_type(),
            "marker": marker,
            "payload_bytes": payload_bytes,
        }
        if sequence_gap:
            packet["missing_packets"] = self._application_rtp_missing_packet_count(
                expected_sequence_number,
                sequence_number,
            )
        self._application_rtp_expected_sequence = (sequence_number + 1) % 65536
        return packet

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
        logger.debug(
            f"Pad added: {pad.get_name()}, caps: {caps.to_string() if caps else 'None'}"
        )
        if not caps:
            return
        struct = caps.get_structure(0)
        if struct.get_name() != "application/x-rtp":
            return

        media = struct.get_string("media") or ""
        if media.lower() == "application":
            if self.application_data_branch_enabled:
                self._ensure_application_data_branch()
                sink_pad = self.m_jit.get_static_pad("sink") if self.m_jit else None
            else:
                sink_pad = None
        else:
            if self.video_branch_enabled:
                sink_pad = self.v_depay.get_static_pad("sink") if self.v_depay else None
            else:
                sink_pad = None

        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

        if self._timer is not None:
            logger.debug("Timeout timer stopped")
            self._timer.cancel()

        if self.session_md_cb:
            self.session_md_cb(
                parse_session_metadata(
                    {
                        "stream_name": pad.get_name(),
                        "caps": caps.to_string(),
                        "structure": struct.to_string(),
                    }
                )
            )

    def _on_sdes_notify(self, src: Gst.Element, _pspec) -> None:
        """Handle SDES notifications from RTSP source."""
        struct = src.get_property("sdes")
        if isinstance(struct, Gst.Structure) and self.session_md_cb:
            self.session_md_cb(
                {"sdes": {k: struct.get_value(k) for k in struct.keys()}}
            )

    def _rtp_probe(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        """Probe RTP packets for extension data."""
        self._timers["rtp_probe"] = time.time()
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

            payload = getattr(ext_data, "get_data", lambda: ext_data)()
            if not payload or len(payload) < 12:
                return Gst.PadProbeReturn.OK

            n_sec = int.from_bytes(payload[0:4], "big")
            n_frac = int.from_bytes(payload[4:8], "big")
            flags = int.from_bytes(payload[8:12], "big")
            unix_ts = n_sec - 2208988800 + n_frac / (1 << 32)
            human_time = datetime.fromtimestamp(unix_ts, timezone.utc)
            self.latest_rtp_data = {
                "human_time": human_time.strftime("%Y-%m-%d %H:%M:%S.%f UTC"),
                "ntp_seconds": n_sec,
                "ntp_fraction": n_frac,
                "C": (flags >> 31) & 1,
                "E": (flags >> 30) & 1,
                "D": (flags >> 29) & 1,
                "T": (flags >> 28) & 1,
                "CSeq": flags & 0xFF,
            }
        finally:
            GstRtp.RTPBuffer.unmap(rtp_buf)
        return Gst.PadProbeReturn.OK

    def _on_new_video_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """Handle new video sample from the video sink."""
        logger.debug("Received new video sample")
        self._timers["vid_sample"] = time.time()
        sample = sink.emit("pull-sample")
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
        width = struct.get_value("width")
        height = struct.get_value("height")
        fmt = struct.get_string("format")

        try:
            frame = _to_rgb_array(info, width, height, fmt)
        except Exception as e:
            self._report_error("Frame Parse", f"Frame parsing failed: {e}", e)
            buf.unmap(info)
            return Gst.FlowReturn.ERROR
        buf.unmap(info)

        payload = {
            "data": frame,
            "latest_rtp_data": self.latest_rtp_data,
        }

        if self.video_proc_fn:
            start = time.time()
            try:
                payload["data"] = self.video_proc_fn(payload, self.shared_cfg)
            except Exception as e:
                self._report_error(
                    "Video Processing", f"User processing function failed: {e}", e
                )
            self._timers["vid_proc"] = time.time() - start

        payload["diagnostics"] = self._video_diag()
        if self.video_frame_cb:
            logger.debug(f"Calling video_frame_cb (count={self.video_cnt})")
            start = time.time()
            try:
                self.video_frame_cb(payload)
            except Exception as e:
                self._report_error(
                    "Video Callback", f"Video frame callback failed: {e}", e
                )
            self._timers["vid_cb"] = time.time() - start

        return Gst.FlowReturn.OK

    def _on_new_application_data_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """Handle new application data sample from the application data sink."""
        logger.debug("Received new application data sample")
        sample = sink.emit("pull-sample")
        if not sample:
            self._report_error(
                "Application Data Sample",
                "No sample received from application data sink",
            )
            return Gst.FlowReturn.ERROR
        self.application_data_cnt += 1

        buf = sample.get_buffer()
        ok, rtp_buf = GstRtp.RTPBuffer.map(buf, Gst.MapFlags.READ)
        if not ok:
            self._report_error(
                "Application Data Buffer", "Failed to map application data RTP buffer"
            )
            return Gst.FlowReturn.ERROR
        try:
            payload = bytes(_unwrap_glib_bytes(rtp_buf.get_payload()))
            marker = rtp_buf.get_marker()
            rtp_packet = self._record_application_rtp_packet(
                rtp_buf,
                len(payload),
                marker,
            )
        finally:
            GstRtp.RTPBuffer.unmap(rtp_buf)

        if (
            self._xml_acc
            and self._application_rtp_current_timestamp is not None
            and rtp_packet["timestamp"] != self._application_rtp_current_timestamp
        ):
            reason = (
                "timestamp_changed_after_sequence_gap"
                if rtp_packet["sequence_gap"]
                else "timestamp_changed_before_marker"
            )
            self._drop_application_xml_assembly(reason, rtp_packet)

        if self._application_rtp_current_timestamp is None:
            self._application_rtp_current_timestamp = rtp_packet["timestamp"]

        if rtp_packet["sequence_gap"]:
            starts_new_document = self._payload_starts_application_xml_document(payload)
            if not self._xml_acc and not starts_new_document:
                self._application_rtp_current_corrupt = True
                self._application_rtp_current_drop_reason = (
                    "sequence_gap_before_document_start"
                )
            elif (
                self._xml_acc
                and rtp_packet["timestamp"] == self._application_rtp_current_timestamp
            ):
                self._application_rtp_current_corrupt = True
                self._application_rtp_current_drop_reason = (
                    "same_timestamp_sequence_gap"
                )

        self._xml_acc.extend(payload)
        rtp_packet["accumulated_xml_bytes_after_packet"] = len(self._xml_acc)
        self._application_rtp_current_xml.append(rtp_packet)

        if not marker:
            return Gst.FlowReturn.OK

        if self._application_rtp_current_corrupt:
            self._drop_application_xml_assembly(
                self._application_rtp_current_drop_reason or "sequence_gap",
                rtp_packet,
            )
            return Gst.FlowReturn.OK

        start = self._xml_acc.find(b"<")
        if start < 0:
            self._report_error(
                "XML Parse",
                "XML start marker '<' not found in accumulated application data "
                f"(accumulated_bytes={len(self._xml_acc)})",
            )
            self._reset_application_xml_assembly()
            return Gst.FlowReturn.OK

        try:
            xml = self._xml_acc[start:].decode("utf-8")
        except UnicodeDecodeError as e:
            self._report_error(
                "XML Decode",
                "Failed to decode application data as UTF-8: "
                f"{e}; accumulated_bytes={len(self._xml_acc)}, xml_start={start}",
                e,
            )
            self._reset_application_xml_assembly()
            return Gst.FlowReturn.OK

        self.xml_cnt += 1
        diagnostics = self._application_data_diag()
        diagnostics["xml_prefix_bytes_discarded"] = start
        diagnostics["xml_bytes"] = len(xml.encode("utf-8"))
        diagnostics["xml_chars"] = len(xml)
        self._reset_application_xml_assembly()
        payload_out = {"data": xml, "diagnostics": diagnostics}
        if self.application_data_cb:
            logger.debug(
                f"Calling application_data_cb (count={self.application_data_cnt})"
            )
            try:
                self.application_data_cb(payload_out)
            except Exception as e:
                self._report_error(
                    "Application Data Callback",
                    f"Application data callback failed: {e}",
                    e,
                )
        return Gst.FlowReturn.OK

    def _timeout_handler(self) -> None:
        """Handle timeout by stopping client."""
        timeout_thread_id = threading.get_ident()
        logger.warning(
            f"Timeout reached ({self._timeout}s), stopping client from timeout "
            f"handler thread TID={timeout_thread_id}"
        )
        uptime = (
            time.time() - self.start_time
            if hasattr(self, "start_time") and self.start_time
            else "unknown"
        )
        logger.debug(f"Timeout handler executing: uptime={uptime}s")
        self._report_error("Timeout", f"Connection timed out in {self._timeout}s")
        logger.debug(f"Timeout handler calling stop() from TID={timeout_thread_id}")
        self.stop()
