from __future__ import annotations

import logging
import multiprocessing as mp
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import cv2
import gi
import numpy as np
import sys

from .utils import parse_session_metadata

gi.require_version("Gst", "1.0")
gi.require_version("GstRtp", "1.0")
gi.require_version("GstRtsp", "1.0")
from gi.repository import Gst, GstRtp, GLib, GstRtsp

# Configure basic logging only when run as a standalone script. When this
# module is imported (e.g. through the high level retrievers) logging should
# be configured by the parent application so that options like `--log-level`
# work as expected.
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

logger = logging.getLogger("ax-devil-rtsp.CombinedRTSPClient")


def _map_buffer(buf: Gst.Buffer) -> tuple[bool, Gst.MapInfo]:
    """Map a GStreamer buffer for reading."""
    return buf.map(Gst.MapFlags.READ)


def _to_rgb_array(info: Gst.MapInfo, width: int, height: int, fmt: str) -> np.ndarray:
    """Convert raw buffer data into an RGB numpy array based on format."""
    data = info.data
    if fmt == "RGB":
        return np.frombuffer(data, np.uint8).reshape(height, width, 3)
    if fmt in ("RGB16", "BGR16"):
        return np.frombuffer(data, np.uint16).reshape(height, width)
    raise ValueError(f"Unsupported pixel format {fmt}")


class CombinedRTSPClient:
    """Unified RTSP client with video and application data callbacks."""

    def __init__(
        self,
        rtsp_url: str,
        *,
        latency: int = 100,
        video_frame_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        application_data_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        session_application_data_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        error_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        video_processing_fn: Optional[Callable[[np.ndarray, dict], Any]] = None,
        shared_config: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.video_frame_cb = video_frame_callback
        self.application_data_cb = application_data_callback
        self.session_md_cb = session_application_data_callback
        self.error_cb = error_callback
        self.video_proc_fn = video_processing_fn
        self.shared_cfg = shared_config or {}

        # Diagnostic counters and state
        self.start_time: Optional[float] = None
        self.err_cnt = 0
        self.video_cnt = 0
        self.application_data_cnt = 0
        self.xml_cnt = 0
        self.latest_rtp_data: Optional[Dict[str, Any]] = None
        self._xml_acc: bytes = b""
        self._timers: Dict[str, Optional[float]] = dict(
            rtp_probe=None, vid_sample=None, vid_proc=None, vid_cb=None
        )

        # Initialize GStreamer
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("combined_pipeline")
        if not self.pipeline:
            raise RuntimeError("Failed to create GStreamer pipeline")

        self._setup_elements()
        self._setup_bus()

        self._timeout = timeout
        self._timer: Optional[None | threading.Timer] = None

    def _setup_elements(self) -> None:
        logger.debug("Setting up pipeline elements")
        self._create_rtspsrc()
        self._create_video_branch()
        self.application_data_branch_built = False

    def _create_rtspsrc(self) -> None:
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

        elems['v_caps'].props.caps = Gst.Caps.from_string("video/x-raw,format=RGB")
        elems['v_sink'].props.emit_signals = True
        elems['v_sink'].props.sync = False
        elems['v_sink'].connect("new-sample", self._on_new_video_sample)

        for el in elems.values():
            self.pipeline.add(el)

        link_order = ['v_depay', 'v_parse', 'v_dec', 'v_conv', 'v_caps', 'v_sink']
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
            self._report_error("Application Data Branch", "Failed to create application data pipeline elements")
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
            self._report_error("Application Data Branch", "Failed to link application data pipeline elements")
            return

        self.m_jit = m_jit
        self.application_data_branch_built = True
        logger.info("Application data branch created")

    def _setup_bus(self) -> None:
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _on_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        if msg.type == Gst.MessageType.EOS:
            logger.info("EOS received")
            self.stop()
        elif msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            self._report_error("GStreamer Error", f"{err.message} | {dbg}")

    def _on_pad_added(self, _src: Gst.Element, pad: Gst.Pad) -> None:
        caps = pad.get_current_caps()
        logger.debug(f"Pad added: {pad.get_name()}, caps: {caps.to_string() if caps else 'None'}")
        if not caps:
            return
        struct = caps.get_structure(0)
        if struct.get_name() != "application/x-rtp":
            return

        media = struct.get_string("media") or ""
        if media.lower() == "application":
            self._ensure_application_data_branch()
            sink_pad = self.m_jit.get_static_pad('sink')
        else:
            sink_pad = self.v_depay.get_static_pad('sink')

        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

        if self.session_md_cb:
            self.session_md_cb(parse_session_metadata({
                'stream_name': pad.get_name(),
                'caps': caps.to_string(),
                'structure': struct.to_string()
            }))

    def _on_sdes_notify(self, src: Gst.Element, _pspec) -> None:
        struct = src.get_property('sdes')
        if isinstance(struct, Gst.Structure) and self.session_md_cb:
            self.session_md_cb({
                'sdes': {k: struct.get_value(k) for k in struct.keys()}
            })

    def _rtp_probe(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
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

        try:
            frame = _to_rgb_array(info, width, height, fmt)
        except Exception as e:
            self._report_error("Frame Parse", f"Frame parsing failed: {e}", e)
            buf.unmap(info)
            return Gst.FlowReturn.ERROR
        buf.unmap(info)

        if self.video_proc_fn:
            start = time.time()
            try:
                frame = self.video_proc_fn(frame, self.shared_cfg)
            except Exception as e:
                self._report_error("Video Processing", f"User processing function failed: {e}", e)
            self._timers['vid_proc'] = time.time() - start

        payload = {
            'data': frame,
            'latest_rtp_data': self.latest_rtp_data,
            'diagnostics': self._video_diag()
        }
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

        if self._timer is not None:
            self._timer.cancel()

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
        self._xml_acc += raw[hdr_len:]

        if not marker:
            return Gst.FlowReturn.OK

        start = self._xml_acc.find(b"<")
        if start < 0:
            self._report_error("XML Parse", "XML start marker '<' not found in accumulated data")
            self._xml_acc = b""
            return Gst.FlowReturn.OK

        try:
            xml = self._xml_acc[start:].decode('utf-8')
        except Exception as e:
            self._report_error("XML Decode", f"Failed to decode XML: {e}", e)
            self._xml_acc = b""
            return Gst.FlowReturn.OK

        self.xml_cnt += 1
        self._xml_acc = b""
        payload = {'data': xml, 'diagnostics': self._application_data_diag()}
        if self.application_data_cb:
            logger.debug(f"Calling application_data_cb (count={self.application_data_cnt})")
            try:
                self.application_data_cb(payload)
            except Exception as e:
                self._report_error("Application Data Callback", f"Application data callback failed: {e}", e)
        return Gst.FlowReturn.OK

    def _video_diag(self) -> Dict[str, Any]:
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

    def _timeout_handler(self) -> None:
        """Handle timeout by stopping client."""
        logger.warning(f"Timeout reached ({self._timeout}s), stopping client")
        self._report_error("Timeout", f"Connection timed out in {self._timeout}s")
        self.stop()

    def start(self) -> None:
        """Start the GStreamer pipeline and main loop."""
        logger.info("Starting CombinedRTSPClient")
        self.start_time = time.time()
        logger.debug("Setting pipeline state to PLAYING")
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            logger.error("Unable to set pipeline to PLAYING state")
            raise RuntimeError("Unable to set pipeline to PLAYING state")
        try:
            if self._timeout:
                self._timer = threading.Timer(self._timeout, self._timeout_handler)
                self._timer.start()
            logger.debug("Starting main loop")
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
        logger.debug("Setting pipeline state to NULL")
        self.pipeline.set_state(Gst.State.NULL)
        if self.loop.is_running():
            logger.debug("Quitting main loop")
            self.loop.quit()

    def __enter__(self) -> CombinedRTSPClient:
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()


def run_combined_client_simple_example(
    rtsp_url: str,
    *,
    latency: int = 200,
    queue: Optional[mp.Queue] = None,
    video_processing_fn: Optional[Callable[[np.ndarray, dict], Any]] = None,
    shared_config: Optional[dict] = None,
) -> None:
    """Example runner: spawns client and logs or queues payloads."""
    def vid_cb(pl: dict) -> None:
        if queue:
            queue.put({**pl, 'kind': 'video'})
        else:
            logger.info("VIDEO frame %s", pl['data'].shape)

    def application_data_cb(pl: dict) -> None:
        if queue:
            queue.put({**pl, 'kind': 'application_data'})
        else:
            logger.info("XML %d bytes", len(pl['data']))

    def sess_cb(md: dict) -> None:
        logger.debug("SESSION-MD: %s", md)

    def err_cb(error: dict) -> None:
        if queue:
            queue.put({**error, 'kind': 'error'})
        else:
            logger.error("ERROR %s: %s", error.get('error_type'), error.get('message'))

    client = CombinedRTSPClient(
        rtsp_url,
        latency=latency,
        video_frame_callback=vid_cb,
        application_data_callback=application_data_cb,
        session_application_data_callback=sess_cb,
        error_callback=err_cb,
        video_processing_fn=video_processing_fn,
        shared_config=shared_config or {},
    )
    client.start()


if __name__ == "__main__":
    import argparse
    import cv2  # noqa: F401

    if mp.get_start_method(allow_none=True) != "spawn":
        mp.set_start_method("spawn", force=True)

    parser = argparse.ArgumentParser(
        description="Combined RTSP video + application data client demo"
    )
    parser.add_argument("--ip", required=True)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--analytics", action="store_true")
    parser.add_argument("--latency", type=int, default=200)
    args = parser.parse_args()

    cred = f"{args.username}:{args.password}@" if args.username or args.password else ""
    url = f"rtsp://{cred}{args.ip}/axis-media/media.amp?onvifreplayext=1"
    if args.analytics:
        url += "&analytics=polygon"

    q: mp.Queue = mp.Queue()
    proc = mp.Process(
        target=run_combined_client_simple_example,
        args=(url,),
        kwargs={"latency": args.latency, "queue": q},
    )
    proc.start()
    logger.info("Spawned client in PID %d", proc.pid)

    try:
        while True:
            try:
                item = q.get(timeout=100)
                if item["kind"] == "video":
                    print(item["latest_rtp_data"])
                    cv2.imshow("Video", item["data"])
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                elif item["kind"] == "application_data":
                    print("XML:", item["data"])
                elif item["kind"] == "error":
                    print(f"ERROR: {item.get('error_type', 'Unknown')}: {item.get('message', 'Unknown error')}")
            except Exception:
                continue
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Terminating client")
        proc.terminate()
        proc.join()
        cv2.destroyAllWindows()
