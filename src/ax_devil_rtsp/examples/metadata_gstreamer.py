import gi  # type: ignore
import time
import logging
import multiprocessing
from typing import Callable, Optional, Dict, Any

from ..deps import ensure_gi_ready
ensure_gi_ready()
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib  # type: ignore

logger = logging.getLogger("ax-devil-rtsp.SceneMetadataClient")

class SceneMetadataClient:
    """
    A production-ready GStreamer client for retrieving scene metadata via RTSP,
    with unified diagnostics included in the data callback.
    """
    def __init__(
        self,
        rtsp_url: str,
        latency: int = 100,
        raw_data_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Initialize the SceneMetadataClient.

        :param rtsp_url: RTSP URL for the stream.
        :param latency: Network latency in milliseconds.
        :param raw_data_callback: Callback function that receives a dictionary:
            {
                "data": <decoded XML metadata string>,
                "diagnostics": {
                    "sample_count": int,
                    "xml_message_count": int,
                    "error_count": int,
                    "uptime": float,  # seconds since the pipeline started
                }
            }
        """
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.raw_data_callback = raw_data_callback

        # Diagnostics counters and state.
        self.sample_count: int = 0
        self.xml_message_count: int = 0
        self.error_count: int = 0
        self.start_time: Optional[float] = None
        self.xml_buffer: bytes = b""

        # Initialize GStreamer.
        Gst.init(None)
        logger.info("GStreamer initialized")
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("axis_metadata_pipeline")
        if not self.pipeline:
            logger.error("Failed to create GStreamer pipeline")
            raise RuntimeError("Pipeline creation failed")
        self._build_pipeline()

    def _build_pipeline(self) -> None:
        """
        Build and link the GStreamer pipeline elements.
        """
        # Create and configure elements.
        self.src = Gst.ElementFactory.make("rtspsrc", "src")
        if not self.src:
            logger.error("Failed to create 'rtspsrc' element")
            raise RuntimeError("Element creation failed: rtspsrc")
        self.src.set_property("location", self.rtsp_url)
        self.src.set_property("latency", self.latency)
        self.src.set_property("protocols", "tcp")

        self.jitter = Gst.ElementFactory.make("rtpjitterbuffer", "jitter")
        if not self.jitter:
            logger.error("Failed to create 'rtpjitterbuffer' element")
            raise RuntimeError("Element creation failed: rtpjitterbuffer")

        self.capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        if not self.capsfilter:
            logger.error("Failed to create 'capsfilter' element")
            raise RuntimeError("Element creation failed: capsfilter")
        caps = Gst.Caps.from_string("application/x-rtp, media=application")
        self.capsfilter.set_property("caps", caps)

        self.appsink = Gst.ElementFactory.make("appsink", "appsink")
        if not self.appsink:
            logger.error("Failed to create 'appsink' element")
            raise RuntimeError("Element creation failed: appsink")
        self.appsink.set_property("emit-signals", True)
        self.appsink.set_property("sync", False)

        # Add elements to the pipeline.
        for element in [self.src, self.jitter, self.capsfilter, self.appsink]:
            self.pipeline.add(element)

        # Link jitter -> capsfilter -> appsink.
        if not self.jitter.link(self.capsfilter):
            logger.error("Failed to link 'rtpjitterbuffer' to 'capsfilter'")
            raise RuntimeError("Linking failed: jitter -> capsfilter")
        if not self.capsfilter.link(self.appsink):
            logger.error("Failed to link 'capsfilter' to 'appsink'")
            raise RuntimeError("Linking failed: capsfilter -> appsink")

        # Connect signals.
        self.src.connect("pad-added", self._on_pad_added)
        self.appsink.connect("new-sample", self._on_new_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        logger.info("Pipeline built and linked successfully")

    def _on_pad_added(self, src: Gst.Element, pad: Gst.Pad) -> None:
        """
        Handle the pad-added signal from the source element.
        """
        caps = pad.get_current_caps()
        if not caps:
            logger.warning("No caps available on pad '%s'", pad.get_name())
            return
        structure = caps.get_structure(0)
        media_type = structure.get_string("media")
        if media_type != "application":
            logger.debug("Ignoring pad '%s' with media type '%s'", pad.get_name(), media_type)
            return
        logger.info("Linking pad '%s' to rtpjitterbuffer", pad.get_name())
        sink_pad = self.jitter.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                logger.info("Pad '%s' linked successfully", pad.get_name())
            else:
                logger.error("Failed to link pad '%s': %s", pad.get_name(), result)
        else:
            logger.debug("Jitterbuffer sink pad already linked or unavailable")

    def _on_new_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """
        Process a new sample from the appsink, extract XML metadata,
        and trigger the callback with a unified payload.
        """
        sample = sink.emit("pull-sample")
        if not sample:
            logger.error("No sample received from appsink")
            self.error_count += 1
            return Gst.FlowReturn.ERROR

        self.sample_count += 1
        buffer = sample.get_buffer()
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if not success:
            logger.error("Failed to map buffer for reading")
            self.error_count += 1
            return Gst.FlowReturn.ERROR

        raw_data = map_info.data
        if len(raw_data) < 12:
            logger.error("RTP packet too short (got %d bytes)", len(raw_data))
            self.error_count += 1
            buffer.unmap(map_info)
            return Gst.FlowReturn.ERROR

        csrc_count = raw_data[0] & 0x0F
        header_length = 12 + (4 * csrc_count)
        if len(raw_data) < header_length:
            logger.error("Incomplete RTP header: expected %d bytes, got %d", header_length, len(raw_data))
            self.error_count += 1
            buffer.unmap(map_info)
            return Gst.FlowReturn.ERROR

        marker = (raw_data[1] & 0x80) != 0
        payload = raw_data[header_length:]
        self.xml_buffer += payload

        if marker:
            start_index = self.xml_buffer.find(b'<')
            if start_index == -1:
                logger.error("XML start '<' not found; discarding data")
                self.error_count += 1
                self.xml_buffer = b""
            else:
                xml_payload = self.xml_buffer[start_index:]
                try:
                    xml_text = xml_payload.decode("utf-8")
                    if not xml_text.lstrip().startswith("<"):
                        logger.error("Decoded XML does not start with '<'; discarding payload")
                        self.error_count += 1
                    else:
                        logger.debug("Received complete XML metadata (length: %d)", len(xml_text))
                        self.xml_message_count += 1
                        unified_payload = {
                            "data": xml_text,
                            "diagnostics": self.get_diagnostics()
                        }
                        if self.raw_data_callback:
                            self.raw_data_callback(unified_payload)
                except UnicodeDecodeError as e:
                    logger.error("Failed to decode XML metadata: %s", e)
                    self.error_count += 1
                self.xml_buffer = b""

        buffer.unmap(map_info)
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """
        Handle messages from the GStreamer bus.
        """
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            logger.info("End-Of-Stream received")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("GStreamer error: %s, Debug: %s", err.message, debug)
            self.error_count += 1
            self.stop()

    def start(self) -> None:
        """
        Start the GStreamer pipeline and the main loop.
        """
        logger.info("Starting SceneMetadataClient pipeline")
        self.start_time = time.time()
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to set pipeline to PLAYING state")
            raise RuntimeError("Pipeline failed to start")
        try:
            self.loop.run()
        except Exception as e:
            logger.error("Main loop encountered an error: %s", e)
            self.stop()

    def stop(self) -> None:
        """
        Stop the GStreamer pipeline and quit the main loop.
        """
        logger.info("Stopping SceneMetadataClient pipeline")
        self.pipeline.set_state(Gst.State.NULL)
        if self.loop.is_running():
            self.loop.quit()
        logger.info("Pipeline stopped")

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Return the current diagnostics information.
        """
        return {
            "sample_count": self.sample_count,
            "xml_message_count": self.xml_message_count,
            "error_count": self.error_count,
            "uptime": time.time() - self.start_time if self.start_time else 0,
        }


def run_scene_metadata_client_simple_example(rtsp_url: str, latency: int = 200, queue: Optional[multiprocessing.Queue] = None) -> None:
    """
    Instantiate and run a SceneMetadataClient.
    The XML metadata along with diagnostics will be sent via the callback.
    If a multiprocessing.Queue is provided, the unified payload is put into the queue.
    """
    def default_callback(payload: Dict[str, Any]) -> None:
        if queue is not None:
            queue.put(payload)
        else:
            logger.info("Received payload:\nData: %s\nDiagnostics: %s",
                        payload["data"], payload["diagnostics"])

    client = SceneMetadataClient(rtsp_url, latency=latency, raw_data_callback=default_callback)
    client.start()


# Example
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s"
    )

    multiprocessing.set_start_method("spawn", force=True)
    xml_queue: multiprocessing.Queue = multiprocessing.Queue()

    username = "username"
    password = "password"
    ip = "ip"

    example_rtsp_url = f"rtsp://{username}:{password}@{ip}/axis-media/media.amp?analytics=polygon"

    client_process = multiprocessing.Process(
        target=run_scene_metadata_client_simple_example,
        args=(example_rtsp_url, 200, xml_queue),
    )
    client_process.start()
    logger.info("Launched SceneMetadataClient subprocess with PID %d", client_process.pid)

    start_time = time.time()
    try:
        while time.time() - start_time < 10:
            try:
                payload = xml_queue.get(timeout=1)
                print(f"Main process received payload:\nData: {payload['data']}\nDiagnostics: {payload['diagnostics']}")
            except Exception:
                continue
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected in main process")
    finally:
        logger.info("Terminating the SceneMetadataClient subprocess")
        client_process.terminate()
        client_process.join()
        logger.info("Subprocess terminated")
