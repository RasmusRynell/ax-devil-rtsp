import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any
import multiprocessing

import gi
import numpy as np
import cv2

gi.require_version('Gst', '1.0')
gi.require_version('GstRtp', '1.0')
from gi.repository import Gst, GstRtp, GLib

logger = logging.getLogger("ax-devil-rtsp.VideoGStreamerClient")

class VideoGStreamerClient:
    """
    A production-ready GStreamer client for video streaming via RTSP with unified diagnostics
    and configurable sample processing.
    """
    def __init__(
        self,
        rtsp_url: str,
        latency: int = 100,
        frame_handler_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        processing_fn: Optional[Callable[[np.ndarray, dict], Any]] = None,
        shared_config: Optional[dict] = None,
    ) -> None:
        """
        Initialize the VideoGStreamerClient.

        :param rtsp_url: The full RTSP URL.
        :param latency: Latency setting for the source (in milliseconds).
        :param frame_handler_callback: A callback function receiving a unified payload:
            {
                "data": <processed video frame (numpy array)>,
                "diagnostics": {
                    "sample_count": int,
                    "error_count": int,
                    "uptime": float,  # seconds since the pipeline started
                    ...
                },
                "latest_rtp_data": <latest RTP extension data dict or None>
            }
        :param processing_fn: A function that processes each frame using a shared config.
            It should have the signature: process_sample(frame: np.ndarray, config: dict) -> np.ndarray.
            If not provided, a default function is used.
        :param shared_config: A dictionary containing configuration parameters. This can be a
            multiprocessing.Manager().dict() to allow runtime updates.
        """
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.frame_handler_callback = frame_handler_callback
        self.processing_fn = processing_fn
        self.shared_config = shared_config if shared_config is not None else {}

        # Diagnostics and state.
        self.sample_count: int = 0
        self.error_count: int = 0
        self.start_time: Optional[float] = None
        self.latest_rtp_data: Optional[Dict[str, Any]] = None

        # Initialize GStreamer.
        Gst.init(None)
        logger.info("GStreamer initialized")
        self.loop = GLib.MainLoop()

        # Build the pipeline manually.
        self.pipeline = Gst.Pipeline.new("video_pipeline")
        if not self.pipeline:
            logger.error("Failed to create GStreamer pipeline")
            raise RuntimeError("Pipeline creation failed")
        self._build_pipeline()

        # Initialize time spent metrics.
        self.time_spent_rtp_probe = None
        self.time_spent_sample = None
        self.time_spent_custom_fn = None
        self.time_spent_callback = None

    def _build_pipeline(self) -> None:
        """
        Create and link the GStreamer pipeline elements.
        Pipeline structure:
            rtspsrc -> (dynamic pad) -> rtph264depay -> h264parse ->
            avdec_h264 -> videoconvert -> capsfilter -> appsink
        """
        # Create and configure source.
        self.src = Gst.ElementFactory.make("rtspsrc", "src")
        if not self.src:
            logger.error("Failed to create 'rtspsrc' element")
            raise RuntimeError("Element creation failed: rtspsrc")
        self.src.set_property("location", self.rtsp_url)
        self.src.set_property("latency", self.latency)
        self.src.set_property("protocols", "tcp")
        self.src.connect("pad-added", self._on_pad_added)

        # Create remaining pipeline elements.
        self.depay = Gst.ElementFactory.make("rtph264depay", "depay")
        if not self.depay:
            logger.error("Failed to create 'rtph264depay' element")
            raise RuntimeError("Element creation failed: rtph264depay")

        self.h264parse = Gst.ElementFactory.make("h264parse", "h264parse")
        if not self.h264parse:
            logger.error("Failed to create 'h264parse' element")
            raise RuntimeError("Element creation failed: h264parse")

        self.decoder = Gst.ElementFactory.make("avdec_h264", "decoder")
        if not self.decoder:
            logger.error("Failed to create 'avdec_h264' element")
            raise RuntimeError("Element creation failed: avdec_h264")

        self.videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
        if not self.videoconvert:
            logger.error("Failed to create 'videoconvert' element")
            raise RuntimeError("Element creation failed: videoconvert")

        self.capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        if not self.capsfilter:
            logger.error("Failed to create 'capsfilter' element")
            raise RuntimeError("Element creation failed: capsfilter")
        # Force output format to RGB; our processing function will fix colors.
        caps = Gst.Caps.from_string("video/x-raw,format=RGB")
        self.capsfilter.set_property("caps", caps)

        self.appsink = Gst.ElementFactory.make("appsink", "appsink")
        if not self.appsink:
            logger.error("Failed to create 'appsink' element")
            raise RuntimeError("Element creation failed: appsink")
        self.appsink.set_property("emit-signals", True)
        self.appsink.set_property("sync", False)
        self.appsink.connect("new-sample", self._on_new_sample)

        # Add elements to the pipeline.
        for element in [self.src, self.depay, self.h264parse, self.decoder,
                        self.videoconvert, self.capsfilter, self.appsink]:
            self.pipeline.add(element)

        # Link static elements: depay -> h264parse -> decoder -> videoconvert -> capsfilter -> appsink.
        if not self.depay.link(self.h264parse):
            logger.error("Failed to link depay to h264parse")
            raise RuntimeError("Linking failed: depay -> h264parse")
        if not self.h264parse.link(self.decoder):
            logger.error("Failed to link h264parse to decoder")
            raise RuntimeError("Linking failed: h264parse -> decoder")
        if not self.decoder.link(self.videoconvert):
            logger.error("Failed to link decoder to videoconvert")
            raise RuntimeError("Linking failed: decoder -> videoconvert")
        if not self.videoconvert.link(self.capsfilter):
            logger.error("Failed to link videoconvert to capsfilter")
            raise RuntimeError("Linking failed: videoconvert -> capsfilter")
        if not self.capsfilter.link(self.appsink):
            logger.error("Failed to link capsfilter to appsink")
            raise RuntimeError("Linking failed: capsfilter -> appsink")

        # Add an RTP probe to extract extension data.
        depay_sink_pad = self.depay.get_static_pad("sink")
        if depay_sink_pad:
            logger.info("Adding RTP probe to depay sink pad.")
            depay_sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        else:
            logger.warning("Failed to get depay sink pad for probe.")

        # Watch the bus.
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        logger.info("Pipeline built and linked successfully")

    def _on_pad_added(self, src: Gst.Element, pad: Gst.Pad) -> None:
        """
        Handle the pad-added signal from rtspsrc.
        """
        caps = pad.get_current_caps()
        if not caps:
            logger.warning("No caps on pad '%s'", pad.get_name())
            return
        structure = caps.get_structure(0)
        if not structure.get_name().startswith("application/x-rtp"):
            logger.debug("Ignoring pad '%s' with type '%s'", pad.get_name(), structure.get_name())
            return
        logger.info("Linking pad '%s' to depayloader.", pad.get_name())
        sink_pad = self.depay.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            result = pad.link(sink_pad)
            if result == Gst.PadLinkReturn.OK:
                logger.info("Pad '%s' linked successfully.", pad.get_name())
            else:
                logger.error("Failed to link pad '%s': %s", pad.get_name(), result)
        else:
            logger.debug("Depay sink pad already linked or unavailable.")

    def _rtp_probe(self, pad, info):
        """
        Probe the RTP buffer to extract extension data.
        """
        start_time_rt = time.time()
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK

        success, rtp_buffer = GstRtp.RTPBuffer.map(buffer, Gst.MapFlags.READ)
        if not success:
            logger.error("Failed to map buffer as RTP packet.")
            self.error_count += 1
            return Gst.PadProbeReturn.OK

        try:
            result = GstRtp.RTPBuffer.get_extension_data(rtp_buffer)
            if result is None:
                logger.debug("No RTP extension data in packet.")
                return Gst.PadProbeReturn.OK

            ext_data, ext_id = result
            if ext_id != 0xABAC:  # Expected ONVIF replay extension.
                logger.debug("Received non-ONVIF extension ID: 0x%04X", ext_id)
                return Gst.PadProbeReturn.OK

            try:
                ext_bytes = ext_data.get_data() if hasattr(ext_data, "get_data") else ext_data
            except Exception as e:
                logger.error("Error retrieving extension data: %s", e)
                self.error_count += 1
                return Gst.PadProbeReturn.OK

            if not ext_bytes or len(ext_bytes) < 12:
                logger.warning("Extension payload too short; expected at least 12 bytes.")
                return Gst.PadProbeReturn.OK

            ntp_seconds = int.from_bytes(ext_bytes[0:4], byteorder='big')
            ntp_fraction = int.from_bytes(ext_bytes[4:8], byteorder='big')
            unix_timestamp = self._convert_ntp_to_unix(ntp_seconds, ntp_fraction)
            human_time = self._format_unix_timestamp(unix_timestamp)
            flags_and_seq = int.from_bytes(ext_bytes[8:12], byteorder='big')

            self.latest_rtp_data = {
                "human_time": human_time,
                "ntp_seconds": ntp_seconds,
                "ntp_fraction": ntp_fraction,
                "C": (flags_and_seq >> 31) & 0x01,
                "E": (flags_and_seq >> 30) & 0x01,
                "D": (flags_and_seq >> 29) & 0x01,
                "T": (flags_and_seq >> 28) & 0x01,
                "CSeq": flags_and_seq & 0xFF
            }
        finally:
            GstRtp.RTPBuffer.unmap(rtp_buffer)
        self.time_spent_rtp_probe = time.time() - start_time_rt
        return Gst.PadProbeReturn.OK

    @staticmethod
    def _convert_ntp_to_unix(ntp_seconds: int, ntp_fraction: int) -> float:
        """
        Convert NTP timestamp to Unix timestamp.
        """
        return ntp_seconds - 2208988800 + ntp_fraction / (2**32)

    @staticmethod
    def _format_unix_timestamp(unix_timestamp: float) -> str:
        """
        Format a Unix timestamp into a human-readable UTC string.
        """
        return datetime.fromtimestamp(unix_timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f UTC")

    def _on_new_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        """
        Process a new sample from the appsink, decode the frame, apply user-supplied processing,
        and trigger the callback with a unified payload.
        """
        start_time_sample = time.time()
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

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        pixel_format = structure.get_string("format")
        logger.debug("Received frame format: %s (%dx%d)", pixel_format, width, height)

        # Process the buffer based on pixel format.
        if pixel_format == "RGB":
            expected_size = width * height * 3
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected RGB frame size (%d).",
                             len(map_info.data), expected_size)
                buffer.unmap(map_info)
                self.error_count += 1
                return Gst.FlowReturn.ERROR
            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))
        elif pixel_format in ("RGB16", "BGR16"):
            expected_size = width * height * 2
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected 16-bit frame size (%d).",
                             len(map_info.data), expected_size)
                buffer.unmap(map_info)
                self.error_count += 1
                return Gst.FlowReturn.ERROR
            frame = np.frombuffer(map_info.data, dtype=np.uint16).reshape((height, width))
        elif pixel_format == "NV12":
            expected_size = int(width * height * 1.5)
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected NV12 frame size (%d).",
                             len(map_info.data), expected_size)
                buffer.unmap(map_info)
                self.error_count += 1
                return Gst.FlowReturn.ERROR
            nv12_frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((int(height * 1.5), width))
            # Convert NV12 to RGB; the processing function will fix the colors.
            frame = cv2.cvtColor(nv12_frame, cv2.COLOR_YUV2RGB_NV12)
        else:
            logger.error("Unhandled pixel format: %s", pixel_format)
            buffer.unmap(map_info)
            self.error_count += 1
            return Gst.FlowReturn.ERROR

        buffer.unmap(map_info)

        self.time_spent_sample = time.time() - start_time_sample

        # Apply the user-supplied processing function (which can use the shared config).
        if self.processing_fn:
            try:
                start_time_processing = time.time()
                frame = self.processing_fn(frame, self.shared_config)
                self.time_spent_custom_fn = time.time() - start_time_processing
            except Exception as e:
                logger.error("Error in processing function: %s", e)
                self.error_count += 1

        unified_payload = {
            "data": frame,
            "diagnostics": self.get_diagnostics(),
            "latest_rtp_data": self.latest_rtp_data
        }

        try:
            if callable(self.frame_handler_callback):
                start_time_callback = time.time()
                self.frame_handler_callback(unified_payload)
                self.time_spent_callback = time.time() - start_time_callback
            else:
                logger.error("frame_handler_callback is not callable.")
        except Exception as e:
            logger.error("Error in frame handler callback: %s", e)
            self.error_count += 1

        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """
        Handle messages from the GStreamer bus.
        """
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            logger.info("End-Of-Stream reached.")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("GStreamer error: %s, Debug: %s", err.message, debug)
            self.error_count += 1
            self.stop()

    def start(self) -> None:
        """
        Start the GStreamer pipeline and run the main loop.
        """
        logger.info("Starting VideoGStreamerClient pipeline.")
        self.start_time = time.time()
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to set pipeline to PLAYING state.")
            raise RuntimeError("Pipeline failed to start.")
        try:
            self.loop.run()
        except Exception as e:
            logger.error("Main loop encountered an error: %s", e)
            self.stop()

    def stop(self) -> None:
        """
        Stop the GStreamer pipeline and quit the main loop.
        """
        logger.info("Stopping VideoGStreamerClient pipeline.")
        self.pipeline.set_state(Gst.State.NULL)
        if self.loop.is_running():
            self.loop.quit()
        logger.info("Pipeline stopped.")

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Return the current diagnostics information.
        """
        return {
            "sample_count": self.sample_count,
            "timestamp": time.time(),
            "time_spent_rtp_probe": self.time_spent_rtp_probe,
            "time_spent_sample": self.time_spent_sample,
            "time_spent_custom_fn": self.time_spent_custom_fn,
            "time_spent_last_callback": self.time_spent_callback,
            "error_count": self.error_count,
            "uptime": time.time() - self.start_time if self.start_time else 0,
        }


def run_video_client_simple_example(rtsp_url: str, latency: int = 100,
                                    queue: Optional[multiprocessing.Queue] = None,
                                    processing_fn: Optional[Callable[[np.ndarray, dict], np.ndarray]] = None,
                                    shared_config: Optional[dict] = None) -> None:
    """
    Instantiate and run a VideoGStreamerClient.
    The processed video frame, diagnostics, and RTP extension data will be sent via the callback.
    If a multiprocessing.Queue is provided, the unified payload is put into the queue.
    """
    def default_callback(payload: Dict[str, Any]) -> None:
        if queue is not None:
            queue.put(payload)
        else:
            diagnostics = payload.get("diagnostics", {})
            logger.info("Received frame (shape: %s) | Diagnostics: %s | Latest RTP Data: %s",
                        payload["data"].shape, diagnostics, payload.get("latest_rtp_data"))
    client = VideoGStreamerClient(rtsp_url, latency=latency,
                                  frame_handler_callback=default_callback,
                                  processing_fn=processing_fn,
                                  shared_config=shared_config)
    client.start()


def example_processing_fn(frame: np.ndarray, config: dict) -> np.ndarray:
    """
    Important: This function runs in the same process as the gstreamer pipeline.

    Processing function that fixes color channels by converting from RGB to BGR.
    The shared config can be used to add further customizations if needed.
    return has to be pickleable since it is sent via multiprocessing.Queue.
    """
    try:
        # Convert the frame from RGB to BGR.
        fixed_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.error("Error converting colors: %s", e)
        return frame
    return fixed_frame


# Example
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s"
    )

    multiprocessing.set_start_method("spawn", force=True)
    frame_queue = multiprocessing.Queue()

    # Create a shared configuration using a Manager dict.
    manager = multiprocessing.Manager()
    shared_config = manager.dict()
    shared_config["resize_width"] = 1920
    shared_config["resize_height"] = 1080
    
    username = "username"
    password = "password"
    ip = "ip"

    rtsp_url = f"rtsp://{username}:{password}@{ip}/axis-media/media.amp"

    video_process = multiprocessing.Process(
        target=run_video_client_simple_example,
        args=(rtsp_url, 200, frame_queue, example_processing_fn, shared_config)
    )
    video_process.start()
    logger.info("Launched VideoGStreamerClient subprocess with PID %d", video_process.pid)

    try:
        while True:
            try:
                payload = frame_queue.get(timeout=1)
                frame = payload.get("data")
                diagnostics = payload.get("diagnostics", {})
                cv2.imshow("Video Frame", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            except Exception:
                continue
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected in main process")
    finally:
        logger.info("Terminating the VideoGStreamerClient subprocess")
        video_process.terminate()
        video_process.join()
        cv2.destroyAllWindows()
        logger.info("Subprocess terminated")
