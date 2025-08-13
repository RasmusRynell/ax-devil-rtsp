#!/usr/bin/env python3
"""
Minimal RTSP GStreamer smoke test.

Purpose:
- Verify that GStreamer (PyGObject) can initialize and pull frames from a given RTSP URL.
- Standalone: does not import this project. Requires only gi (PyGObject) and standard library.

Usage:
  python tools/gstreamer_rtsp_demo.py rtsp://user:pass@host:port/path

Behavior:
- Assumes H.264 video. Counts a small number of frames via appsink and exits.
- Exit code 0 on success; 2 on timeout or error; 1 on CLI/usage error.

Debugging levels (incrementally enable as needed):
1) Baseline (no extra env):
   python tools/gstreamer_rtsp_demo.py rtsp://...

2) Python-side debug logs (this script):
   GST_PY_DEMO_DEBUG=1 python tools/gstreamer_rtsp_demo.py rtsp://...

3) GStreamer core debug (broad):
   GST_DEBUG=3 python tools/gstreamer_rtsp_demo.py rtsp://...
   - Increase to 4-6 for more detail (6 is very verbose)

4) GStreamer targeted debug (recommended for RTSP/H264):
   GST_DEBUG=rtspsrc:6,rtp*:6,rtpjitterbuffer:6,rtph264depay:6,h264parse:6,avdec_h264:4,videoconvert:4,appsink:6 \
   python tools/gstreamer_rtsp_demo.py rtsp://...

5) Persist GStreamer logs to a file (useful for CI/support bundles):
   GST_DEBUG=6 GST_DEBUG_NO_COLOR=1 GST_DEBUG_FILE=gst.log \
   python tools/gstreamer_rtsp_demo.py rtsp://...

6) Check plugins outside Python (sanity check):
   gst-inspect-1.0 rtspsrc
   gst-inspect-1.0 rtph264depay
   gst-inspect-1.0 h264parse
   gst-inspect-1.0 avdec_h264

Environment notes:
- This script logs key GST_* env vars and GStreamer version/registry info on start.
- If elements are missing, it prints explicit install hints for Debian/Ubuntu.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Optional, Dict, Tuple

try:
    import gi  # type: ignore
    gi.require_version("Gst", "1.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gst, GLib  # type: ignore
except Exception as import_error:  # pragma: no cover - environment dependent
    print(f"[gstreamer_rtsp_demo] Import failure: {import_error}")
    print("Hint: Install PyGObject and GStreamer packages for your OS.")
    sys.exit(2)

# Optional introspection modules used by the project
GstRtsp = None  # type: ignore
GstRtp = None  # type: ignore


# ---------------------------
# Logging setup
# ---------------------------
def _configure_logging() -> logging.Logger:
    level = logging.DEBUG if os.getenv("GST_PY_DEMO_DEBUG", "").lower() in {"1", "true", "yes"} else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("gstreamer_rtsp_demo")


logger = _configure_logging()


FRAMES_TO_COLLECT: int = 20
TIMEOUT_SECONDS: int = 15
LATENCY_MS: int = 200


# ---------------------------
# Preflight diagnostics
# ---------------------------
def _log_environment_info() -> None:
    logger.info("Python executable: %s", sys.executable)
    logger.info("Python version: %s", sys.version.replace("\n", " "))
    logger.info("Platform: %s", sys.platform)
    for var in ("GST_PLUGIN_PATH", "GST_PLUGIN_SYSTEM_PATH", "GST_REGISTRY", "GST_DEBUG", "GST_DEBUG_DUMP_DOT_DIR"):
        logger.info("env %s=%s", var, os.getenv(var, "<not set>"))


def _preflight_imports() -> bool:
    global GstRtsp, GstRtp
    ok = True
    try:
        gi.require_version("GstRtsp", "1.0")
        from gi.repository import GstRtsp as _GstRtsp  # type: ignore
        GstRtsp = _GstRtsp
        logger.info("GstRtsp introspection: OK")
    except Exception as e:
        logger.error("GstRtsp introspection missing: %s", e)
        logger.error("Install: apt-get install -y gir1.2-gst-rtsp-1.0")
        ok = False

    try:
        gi.require_version("GstRtp", "1.0")
        from gi.repository import GstRtp as _GstRtp  # type: ignore
        GstRtp = _GstRtp
        logger.info("GstRtp introspection: OK")
    except Exception as e:
        logger.error("GstRtp introspection missing: %s", e)
        logger.error("Install: apt-get install -y gir1.2-gst-plugins-base-1.0")
        ok = False

    return ok


def _preflight_gstreamer_and_plugins() -> bool:
    ok = True
    try:
        Gst.init(None)
    except Exception as e:
        logger.error("Gst.init failed: %s", e)
        return False

    try:
        v = Gst.version()
        logger.info("GStreamer version: %s", ".".join(str(x) for x in v))
        logger.info("GStreamer version string: %s", Gst.version_string())
    except Exception as e:
        logger.warning("Failed to obtain GStreamer version info: %s", e)

    # Registry diagnostics
    try:
        reg = Gst.Registry.get()
        try:
            plugin_count = len(reg.get_plugin_list())  # type: ignore[attr-defined]
        except Exception:
            plugin_count = -1
        try:
            reg_path = reg.get_path()  # type: ignore[attr-defined]
        except Exception:
            reg_path = "<unknown>"
        logger.info("Registry: plugins=%s, path=%s", plugin_count, reg_path)
    except Exception as e:
        logger.warning("Failed to access Gst.Registry: %s", e)

    # Element availability checks
    required_elements: Dict[str, Tuple[str, str]] = {
        # element_name: (plugin_group_hint, apt_package_hint)
        "rtspsrc": ("plugins-good", "gstreamer1.0-plugins-good"),
        "rtph264depay": ("plugins-good", "gstreamer1.0-plugins-good"),
        "h264parse": ("plugins-bad", "gstreamer1.0-plugins-bad"),
        "avdec_h264": ("libav", "gstreamer1.0-libav"),
        "videoconvert": ("plugins-base", "gstreamer1.0-plugins-base"),
        "appsink": ("plugins-base", "gstreamer1.0-plugins-base"),
        # For the application's metadata branch
        "rtpjitterbuffer": ("plugins-good (rtpmanager)", "gstreamer1.0-plugins-good"),
        "capsfilter": ("coreelements", "gstreamer1.0"),
    }

    missing: Dict[str, Tuple[str, str]] = {}
    for name, (group_hint, apt_hint) in required_elements.items():
        try:
            factory = Gst.ElementFactory.find(name)
        except Exception as e:
            logger.error("ElementFactory.find('%s') raised: %s", name, e)
            factory = None
        if factory is None:
            logger.error("Missing element: %s (need %s; try: apt-get install -y %s)", name, group_hint, apt_hint)
            missing[name] = (group_hint, apt_hint)
        else:
            try:
                plugin_name = factory.get_plugin_name()  # type: ignore[attr-defined]
            except Exception:
                plugin_name = "<unknown>"
            logger.info("Element available: %-16s (plugin=%s)", name, plugin_name)

    if missing:
        logger.error("Missing %d GStreamer element(s): %s", len(missing), ", ".join(missing.keys()))
        logger.error("Hint (Ubuntu/Debian): apt-get install -y gstreamer1.0-dev gstreamer1.0-plugins-{base,good,bad,ugly} gstreamer1.0-libav gir1.2-gstreamer-1.0")
        ok = False

    return ok


class RTSPSmokeTest:
    """Minimal H.264 RTSP reader built directly on Gst.

    This intentionally avoids project-specific imports; it only checks that the
    local system can construct a simple RTSP pipeline and receive frames.
    """

    def __init__(self, rtsp_url: str) -> None:
        self.rtsp_url: str = rtsp_url
        self.loop: Optional[GLib.MainLoop] = None
        self.pipeline: Optional[Gst.Pipeline] = None

        # Elements created during setup
        self.src: Optional[Gst.Element] = None
        self.v_depay: Optional[Gst.Element] = None
        self.v_parse: Optional[Gst.Element] = None
        self.v_dec: Optional[Gst.Element] = None
        self.v_conv: Optional[Gst.Element] = None
        self.v_sink: Optional[Gst.Element] = None

        # State
        self.frame_count: int = 0
        self.success: bool = False

    # ---------------------------
    # Pipeline construction
    # ---------------------------
    def _create_elements(self) -> None:
        self.src = Gst.ElementFactory.make("rtspsrc", "src")
        self.v_depay = Gst.ElementFactory.make("rtph264depay", "v_depay")
        self.v_parse = Gst.ElementFactory.make("h264parse", "v_parse")
        self.v_dec = Gst.ElementFactory.make("avdec_h264", "v_dec")
        self.v_conv = Gst.ElementFactory.make("videoconvert", "v_conv")
        self.v_sink = Gst.ElementFactory.make("appsink", "v_sink")

        for name, el in (
            ("rtspsrc", self.src),
            ("rtph264depay", self.v_depay),
            ("h264parse", self.v_parse),
            ("avdec_h264", self.v_dec),
            ("videoconvert", self.v_conv),
            ("appsink", self.v_sink),
        ):
            if el is None:
                raise RuntimeError(f"Failed to create element: {name}")

        assert self.src and self.v_depay and self.v_parse and self.v_dec and self.v_conv and self.v_sink

        # Configure elements
        self.src.set_property("location", self.rtsp_url)
        self.src.set_property("latency", LATENCY_MS)
        # Align with project defaults where relevant
        if GstRtsp is not None:
            try:
                proto = GstRtsp.RTSPLowerTrans.TCP | GstRtsp.RTSPLowerTrans.UDP
                self.src.set_property("protocols", proto)
                # 100_000_000 µs = 100s
                self.src.set_property("tcp_timeout", 100_000_000)
                self.src.set_property("drop_on_latency", False)
                logger.info("rtspsrc props set: latency=%sms, protocols=TCP|UDP, tcp_timeout=100000000µs, drop_on_latency=False", LATENCY_MS)
            except Exception as e:
                logger.warning("Failed to set rtspsrc advanced properties: %s", e)

        self.v_sink.set_property("emit-signals", True)
        self.v_sink.set_property("sync", False)
        # Keep the queue tiny to avoid backpressure building up in a quick test
        self.v_sink.set_property("max-buffers", 1)
        self.v_sink.set_property("drop", True)

        # Request a common raw format to keep sink behavior predictable
        caps = Gst.Caps.from_string("video/x-raw,format=RGB")
        self.v_sink.set_property("caps", caps)

        self.v_sink.connect("new-sample", self._on_new_sample)
        self.src.connect("pad-added", self._on_pad_added)

    def _link_static_chain(self) -> None:
        assert self.pipeline and self.v_depay and self.v_parse and self.v_dec and self.v_conv and self.v_sink
        for el in (self.v_depay, self.v_parse, self.v_dec, self.v_conv, self.v_sink):
            self.pipeline.add(el)

        if not self.v_depay.link(self.v_parse):
            raise RuntimeError("Failed to link v_depay -> v_parse")
        if not self.v_parse.link(self.v_dec):
            raise RuntimeError("Failed to link v_parse -> v_dec")
        if not self.v_dec.link(self.v_conv):
            raise RuntimeError("Failed to link v_dec -> v_conv")
        if not self.v_conv.link(self.v_sink):
            raise RuntimeError("Failed to link v_conv -> v_sink")

    def _setup_bus(self) -> None:
        assert self.pipeline
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    # ---------------------------
    # Callbacks
    # ---------------------------
    def _on_pad_added(self, _src: Gst.Element, pad: Gst.Pad) -> None:
        """Link rtspsrc's dynamic pad to the depayloader when it's H.264 video."""
        caps = pad.get_current_caps()
        caps_str = caps.to_string() if caps else "<none>"
        logger.info("pad-added: %s", caps_str)

        if not caps:
            return
        struct = caps.get_structure(0)
        if struct.get_name() != "application/x-rtp":
            return
        media = struct.get_string("media") or ""
        enc = struct.get_string("encoding-name") or ""

        # Minimal scope: only H.264 video
        if media.lower() != "video" or enc.upper() != "H264":
            logger.error("Unsupported stream: media=%s, encoding=%s (only H264 video supported in this demo)", media, enc)
            return

        assert self.v_depay is not None
        sink_pad = self.v_depay.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

    def _on_new_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        self.frame_count += 1
        if self.frame_count % 5 == 0:
            logger.info("received frames: %d", self.frame_count)
        if self.frame_count >= FRAMES_TO_COLLECT:
            self.success = True
            logger.info("SUCCESS: collected %d frames", self.frame_count)
            self.stop()
        return Gst.FlowReturn.OK

    def _on_bus_message(self, _bus: Gst.Bus, msg: Gst.Message) -> None:
        msg_type = msg.type
        if msg_type == Gst.MessageType.EOS:
            logger.info("EOS received")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            logger.error("ERROR: %s | %s", err.message, dbg)
            self.stop()
        elif msg_type == Gst.MessageType.WARNING:
            gerr, dbg = msg.parse_warning()
            logger.warning("WARNING: %s | %s", gerr.message, dbg)

    def _on_timeout(self) -> bool:
        logger.error("TIMEOUT after %ss (frames=%d)", TIMEOUT_SECONDS, self.frame_count)
        self.stop()
        # Returning False ensures this timeout only fires once
        return False

    # ---------------------------
    # Lifecycle
    # ---------------------------
    def start(self) -> None:
        logger.info("Initializing GStreamer...")
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("rtsp_demo_pipeline")
        if not self.pipeline:
            raise RuntimeError("Failed to create pipeline")

        # Add source and static chain
        self._create_elements()
        assert self.src is not None
        self.pipeline.add(self.src)
        self._link_static_chain()
        self._setup_bus()

        # Timeout guard
        GLib.timeout_add_seconds(TIMEOUT_SECONDS, self._on_timeout)

        logger.info("Connecting to: %s", self.rtsp_url)
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Unable to set pipeline to PLAYING")

        try:
            self.loop.run()
        finally:
            # Ensure state is cleaned up even if loop exits due to error/timeout
            self.pipeline.set_state(Gst.State.NULL)

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.quit()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        logger.error("Usage: python tools/gstreamer_rtsp_demo.py rtsp://user:pass@host:port/path")
        return 1

    url = argv[1]
    if not (url.startswith("rtsp://") or url.startswith("rtsps://")):
        logger.error("URL must start with rtsp:// or rtsps://")
        return 1

    logger.info("Starting RTSP GStreamer smoke test...")
    logger.info("Config: frames=%d, timeout=%ss, latency=%sms", FRAMES_TO_COLLECT, TIMEOUT_SECONDS, LATENCY_MS)
    _log_environment_info()

    # Import and element availability preflight
    imports_ok = _preflight_imports()
    elements_ok = _preflight_gstreamer_and_plugins()
    if not (imports_ok and elements_ok):
        logger.error("Preflight checks FAILED. See logs above for missing components and install hints.")
        return 2

    start_time = time.time()
    try:
        tester = RTSPSmokeTest(url)
        tester.start()
        elapsed = time.time() - start_time
        logger.info("Finished in %.2fs", elapsed)
        return 0 if tester.success else 2
    except KeyboardInterrupt:
        logger.error("Interrupted")
        return 2
    except Exception as e:
        logger.exception("FAILURE: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))


