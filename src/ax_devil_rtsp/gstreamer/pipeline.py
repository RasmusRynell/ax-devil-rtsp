"""
GStreamer pipeline setup and element creation functionality.
"""

from __future__ import annotations
from gi.repository import Gst, GstRtsp
import gi

from typing import Optional

from ..logging import get_logger

logger = get_logger("gstreamer.pipeline")


gi.require_version("Gst", "1.0")
gi.require_version("GstRtsp", "1.0")


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
        self.application_data_branch_enabled: bool = True

    def _setup_elements(self) -> None:
        """Set up all pipeline elements."""
        logger.debug("Setting up pipeline elements")
        self._create_rtspsrc()
        if self.video_branch_enabled:
            self._create_video_branch()
        self.application_data_branch_built = False

    def _create_rtspsrc(self) -> None:
        """Create and configure the RTSP source element."""
        logger.debug("Creating rtspsrc element")
        src = Gst.ElementFactory.make("rtspsrc", "src")
        if not src:
            logger.error("Unable to create rtspsrc element")
            raise RuntimeError("Unable to create rtspsrc element")
        src.props.location = self.rtsp_url
        src.props.latency = self.latency
        src.props.protocols = (GstRtsp.RTSPLowerTrans.TCP |
                               GstRtsp.RTSPLowerTrans.UDP)

        # Be stricter about timeout handling
        src.props.tcp_timeout = 100_000_000     # µs until we declare the server dead

        # 'Axis Scene Description' (the application data) streams sometimes arrive late; delay EOS
        src.props.drop_on_latency = False

        src.connect("pad-added", self._on_pad_added)
        src.connect("notify::sdes", self._on_sdes_notify)
        self.pipeline.add(src)
        self.src = src
        logger.debug("rtspsrc element created and added to pipeline")

    def _create_video_branch(self) -> None:
        """Add and link video depay, parser, decoder, converter, and appsink."""
        logger.debug("Creating video branch elements")
        elems = {
            'v_depay': Gst.ElementFactory.make("rtph264depay", "v_depay"),
            'v_parse': Gst.ElementFactory.make("h264parse", "v_parse"),
            'v_dec': Gst.ElementFactory.make("avdec_h264", "v_dec"),
            'v_conv': Gst.ElementFactory.make("videoconvert", "v_conv"),
            'v_caps': Gst.ElementFactory.make("capsfilter", "v_caps"),
            'v_sink': Gst.ElementFactory.make("appsink", "v_sink"),
        }
        if not all(elems.values()):
            raise RuntimeError("Failed to create one or more video elements")

        elems['v_caps'].props.caps = Gst.Caps.from_string(
            "video/x-raw,format=RGB")
        elems['v_sink'].props.emit_signals = True
        elems['v_sink'].props.sync = False
        elems['v_sink'].connect("new-sample", self._on_new_video_sample)

        for el in elems.values():
            self.pipeline.add(el)

        link_order = ['v_depay', 'v_parse',
                      'v_dec', 'v_conv', 'v_caps', 'v_sink']
        for src_name, dst_name in zip(link_order, link_order[1:]):
            if not elems[src_name].link(elems[dst_name]):
                raise RuntimeError(f"Failed to link {src_name} to {dst_name}")

        # RTP extension probe on depay sink pad
        pad = elems['v_depay'].get_static_pad('sink')
        pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        self.v_depay = elems['v_depay']
        logger.debug("Video branch elements created and linked")

    def _ensure_application_data_branch(self) -> None:
        """Lazily build application data branch on demand."""
        if self.application_data_branch_built:
            return

        logger.debug("Creating application data branch elements")
        m_jit = Gst.ElementFactory.make("rtpjitterbuffer", "m_jit")
        m_caps = Gst.ElementFactory.make("capsfilter", "m_caps")
        m_sink = Gst.ElementFactory.make("appsink", "m_sink")
        if not all((m_jit, m_caps, m_sink)):
            self._report_error("Application Data Branch",
                               "Failed to create application data pipeline elements")
            return

        m_jit.props.latency = self.latency
        m_caps.props.caps = Gst.Caps.from_string(
            "application/x-rtp,media=application")
        m_sink.props.emit_signals = True
        m_sink.props.sync = False
        m_sink.connect("new-sample", self._on_new_application_data_sample)

        for el in (m_jit, m_caps, m_sink):
            self.pipeline.add(el)
            el.sync_state_with_parent()

        if not (m_jit.link(m_caps) and m_caps.link(m_sink)):
            self._report_error("Application Data Branch",
                               "Failed to link application data pipeline elements")
            return

        self.m_jit = m_jit
        self.application_data_branch_built = True
        logger.info("Application data branch created")

    def _setup_bus(self) -> None:
        """Set up the GStreamer message bus."""
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
