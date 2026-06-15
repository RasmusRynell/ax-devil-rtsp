"""
GStreamer pipeline setup and element creation functionality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import gi
from gi.repository import Gst

from ..utils.logging import get_logger

logger = get_logger(__name__)


gi.require_version("Gst", "1.0")

# GStreamer's RTSPLowerTrans enum bitmask for TCP|UDP.
# Keeping this numeric avoids a hard runtime dependency on the GstRtsp typelib.
RTSP_PROTOCOLS_TCP_UDP = 0x1 | 0x4


class PipelineSetupMixin:
    """Mixin class providing GStreamer pipeline setup functionality."""

    def __init__(self):
        # These should be set by the concrete class
        self.pipeline: Optional[Gst.Pipeline] = None
        self.latency: int = 100
        self.rtsp_url: str = ""
        self.src: Optional[Gst.Element] = None
        self.v_depay: Optional[Gst.Element] = None
        self.m_jit: Optional[Gst.Element] = None
        self.application_data_branch_built: bool = False
        self.video_branch_enabled: bool = True
        self.decoded_video_branch_enabled: bool = True
        self.application_data_branch_enabled: bool = True
        self.raw_recording_path: Optional[Path] = None

    def _setup_elements(self) -> None:
        """Set up all pipeline elements."""
        logger.debug(
            "Setting up pipeline: "
            f"video={self.video_branch_enabled}, "
            f"app_data={self.application_data_branch_enabled}, "
            f"latency={self.latency}ms"
        )
        self._create_rtspsrc()
        if self.video_branch_enabled:
            self._create_video_branch()
        self.application_data_branch_built = False

    def _create_rtspsrc(self) -> None:
        """Create and configure the RTSP source element."""
        logger.debug(f"Creating rtspsrc: URL={self.rtsp_url}")
        src = Gst.ElementFactory.make("rtspsrc", "src")
        if not src:
            logger.error("Unable to create rtspsrc element")
            raise RuntimeError("Unable to create rtspsrc element")
        
        src.props.location = self.rtsp_url
        src.props.latency = self.latency
        src.props.protocols = RTSP_PROTOCOLS_TCP_UDP
        src.props.tcp_timeout = 100_000_000     # µs until we declare the server dead
        src.props.drop_on_latency = False

        src.connect("pad-added", self._on_pad_added)
        src.connect("notify::sdes", self._on_sdes_notify)
        
        self.pipeline.add(src)
        self.src = src

    def _create_video_branch(self) -> None:
        """Add and link video depay, parser, decoder, converter, and appsink."""
        if self.raw_recording_path is not None:
            self._create_recording_video_branch()
            return

        element_names = [
            "rtph264depay",
            "h264parse",
            "avdec_h264",
            "videoconvert",
            "capsfilter",
            "appsink",
        ]
        element_aliases = ["v_depay", "v_parse", "v_dec", "v_conv", "v_caps", "v_sink"]
        
        elems = {}
        for factory_name, alias in zip(element_names, element_aliases, strict=True):
            elem = Gst.ElementFactory.make(factory_name, alias)
            if not elem:
                logger.error(f"Failed to create video element: {factory_name}")
            elems[alias] = elem
        
        if not all(elems.values()):
            failed_elements = [alias for alias, elem in elems.items() if elem is None]
            logger.error(f"Failed to create video elements: {failed_elements}")
            raise RuntimeError("Failed to create one or more video elements")
        
        logger.debug("Video elements created")

        caps_str = "video/x-raw,format=RGB"
        elems['v_caps'].props.caps = Gst.Caps.from_string(caps_str)
        elems['v_sink'].props.emit_signals = True
        elems['v_sink'].props.sync = False
        elems['v_sink'].connect("new-sample", self._on_new_video_sample)

        for el in elems.values():
            self.pipeline.add(el)

        link_order = ['v_depay', 'v_parse', 'v_dec', 'v_conv', 'v_caps', 'v_sink']
        for src_name, dst_name in zip(link_order, link_order[1:], strict=False):
            if not elems[src_name].link(elems[dst_name]):
                logger.error(f"Failed to link video elements: {src_name} -> {dst_name}")
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        # RTP extension probe on depay sink pad
        pad = elems['v_depay'].get_static_pad('sink')
        if pad:
            pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        else:
            logger.warning("Could not get sink pad from v_depay for RTP probe")
        
        self.v_depay = elems['v_depay']
        logger.debug("Video branch created")

    def _create_recording_video_branch(self) -> None:
        """Create a video branch that also records parsed H.264 to MP4."""
        assert self.raw_recording_path is not None

        if not self.decoded_video_branch_enabled:
            self._create_recording_only_video_branch()
            return

        element_names = [
            "rtph264depay",
            "tee",
            "queue",
            "h264parse",
            "avdec_h264",
            "videoconvert",
            "capsfilter",
            "appsink",
            "queue",
            "h264parse",
            "mp4mux",
            "filesink",
        ]
        element_aliases = [
            "v_depay",
            "v_tee",
            "v_decode_queue",
            "v_decode_parse",
            "v_dec",
            "v_conv",
            "v_caps",
            "v_sink",
            "v_record_queue",
            "v_record_parse",
            "v_record_mux",
            "v_record_sink",
        ]

        elems = {}
        for factory_name, alias in zip(element_names, element_aliases, strict=True):
            elem = Gst.ElementFactory.make(factory_name, alias)
            if not elem:
                logger.error(
                    f"Failed to create recording video element: {factory_name}"
                )
            elems[alias] = elem

        if not all(elems.values()):
            failed_elements = [alias for alias, elem in elems.items() if elem is None]
            logger.error(
                f"Failed to create recording video elements: {failed_elements}"
            )
            raise RuntimeError(
                "Failed to create one or more recording video elements"
            )

        logger.debug("Recording video elements created")

        elems["v_caps"].props.caps = Gst.Caps.from_string("video/x-raw,format=RGB")
        elems["v_sink"].props.emit_signals = True
        elems["v_sink"].props.sync = False
        elems["v_sink"].connect("new-sample", self._on_new_video_sample)
        elems["v_record_sink"].props.location = str(self.raw_recording_path)
        elems["v_record_sink"].props.sync = False

        # Keep preview callbacks from blocking recording if the host app is slow.
        elems["v_decode_queue"].props.max_size_buffers = 2
        elems["v_decode_queue"].props.max_size_bytes = 0
        elems["v_decode_queue"].props.max_size_time = 0
        elems["v_decode_queue"].props.leaky = 2  # downstream

        if hasattr(elems["v_record_parse"].props, "config_interval"):
            elems["v_record_parse"].props.config_interval = -1

        for el in elems.values():
            self.pipeline.add(el)

        pre_tee_order = ["v_depay", "v_tee"]
        for src_name, dst_name in zip(pre_tee_order, pre_tee_order[1:], strict=False):
            if not elems[src_name].link(elems[dst_name]):
                logger.error(
                    "Failed to link recording video elements: "
                    f"{src_name} -> {dst_name}"
                )
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        preview_order = [
            "v_decode_queue",
            "v_decode_parse",
            "v_dec",
            "v_conv",
            "v_caps",
            "v_sink",
        ]
        for src_name, dst_name in zip(preview_order, preview_order[1:], strict=False):
            if not elems[src_name].link(elems[dst_name]):
                logger.error(
                    f"Failed to link preview branch elements: {src_name} -> {dst_name}"
                )
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        record_order = [
            "v_record_queue",
            "v_record_parse",
            "v_record_mux",
            "v_record_sink",
        ]
        for src_name, dst_name in zip(record_order, record_order[1:], strict=False):
            if not elems[src_name].link(elems[dst_name]):
                logger.error(
                    "Failed to link recording branch elements: "
                    f"{src_name} -> {dst_name}"
                )
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        self._link_tee_to_queue(
            elems["v_tee"],
            elems["v_decode_queue"],
            "preview",
        )
        self._link_tee_to_queue(
            elems["v_tee"],
            elems["v_record_queue"],
            "recording",
        )

        pad = elems["v_depay"].get_static_pad("sink")
        if pad:
            pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        else:
            logger.warning("Could not get sink pad from v_depay for RTP probe")

        self.v_depay = elems["v_depay"]
        logger.info(f"Raw RTSP recording enabled: {self.raw_recording_path}")

    def _link_tee_to_queue(
        self,
        tee: Gst.Element,
        queue: Gst.Element,
        branch_name: str,
    ) -> None:
        """Link a tee output to a queue using an explicit tee request pad."""
        tee_src_pad = tee.request_pad_simple("src_%u")
        queue_sink_pad = queue.get_static_pad("sink")
        if tee_src_pad is None or queue_sink_pad is None:
            raise RuntimeError(f"Failed to get pads for video tee {branch_name} branch")

        result = tee_src_pad.link(queue_sink_pad)
        if result != Gst.PadLinkReturn.OK:
            tee.release_request_pad(tee_src_pad)
            raise RuntimeError(f"Failed to link video tee to {branch_name} branch")

    def _create_recording_only_video_branch(self) -> None:
        """Create a stream-copy recording branch with no decoded video output."""
        assert self.raw_recording_path is not None

        element_names = ["rtph264depay", "h264parse", "mp4mux", "filesink"]
        element_aliases = ["v_depay", "v_parse", "v_record_mux", "v_record_sink"]

        elems = {}
        for factory_name, alias in zip(element_names, element_aliases, strict=True):
            elem = Gst.ElementFactory.make(factory_name, alias)
            if not elem:
                logger.error(
                    f"Failed to create recording-only video element: {factory_name}"
                )
            elems[alias] = elem

        if not all(elems.values()):
            failed_elements = [alias for alias, elem in elems.items() if elem is None]
            logger.error(
                f"Failed to create recording-only video elements: {failed_elements}"
            )
            raise RuntimeError(
                "Failed to create one or more recording-only video elements"
            )

        elems["v_record_sink"].props.location = str(self.raw_recording_path)
        elems["v_record_sink"].props.sync = False
        if hasattr(elems["v_parse"].props, "config_interval"):
            elems["v_parse"].props.config_interval = -1

        for el in elems.values():
            self.pipeline.add(el)

        link_order = ["v_depay", "v_parse", "v_record_mux", "v_record_sink"]
        for src_name, dst_name in zip(link_order, link_order[1:], strict=False):
            if not elems[src_name].link(elems[dst_name]):
                logger.error(
                    "Failed to link recording-only video elements: "
                    f"{src_name} -> {dst_name}"
                )
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        pad = elems["v_depay"].get_static_pad("sink")
        if pad:
            pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        else:
            logger.warning("Could not get sink pad from v_depay for RTP probe")

        self.v_depay = elems["v_depay"]
        logger.info(f"Raw RTSP recording enabled: {self.raw_recording_path}")

    def _ensure_application_data_branch(self) -> None:
        """Lazily build application data branch on demand."""
        if self.application_data_branch_built:
            return

        m_jit = Gst.ElementFactory.make("rtpjitterbuffer", "m_jit")
        m_caps = Gst.ElementFactory.make("capsfilter", "m_caps")
        m_sink = Gst.ElementFactory.make("appsink", "m_sink")
        
        if not all((m_jit, m_caps, m_sink)):
            logger.error("Failed to create application data pipeline elements")
            self._report_error("Application Data Branch",
                               "Failed to create application data pipeline elements")
            return

        m_jit.props.latency = self.latency
        m_caps.props.caps = Gst.Caps.from_string("application/x-rtp,media=application")
        m_sink.props.emit_signals = True
        m_sink.props.sync = False
        m_sink.connect("new-sample", self._on_new_application_data_sample)

        for el in (m_jit, m_caps, m_sink):
            self.pipeline.add(el)
            el.sync_state_with_parent()

        if not (m_jit.link(m_caps) and m_caps.link(m_sink)):
            logger.error("Failed to link application data pipeline elements")
            self._report_error("Application Data Branch",
                               "Failed to link application data pipeline elements")
            return

        self.m_jit = m_jit
        self.application_data_branch_built = True
        logger.debug("Application data branch created")

    def _setup_bus(self) -> None:
        """Set up the GStreamer message bus."""
        bus = self.pipeline.get_bus()
        if bus:
            bus.add_signal_watch()
            bus.connect("message", self._on_bus_message)
        else:
            logger.error("Failed to get message bus from pipeline")
