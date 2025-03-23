import logging
from datetime import datetime, timezone
import gi
import numpy as np
import cv2

gi.require_version('Gst', '1.0')
gi.require_version('GstRtp', '1.0')
from gi.repository import Gst, GstRtp, GLib

logger = logging.getLogger(__name__)

class RTSPClient:
    def __init__(self, rtsp_url, latency=100, frame_handler_callback=None):
        """
        Initialize the RTSP client.

        Args:
            rtsp_url (str): The full RTSP URL.
            latency (int): The latency setting for rtspsrc (in milliseconds).
            frame_handler_callback (callable): A callback function accepting (buffer, rtp_info).
        """
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.frame_handler_callback = frame_handler_callback
        self.latest_rtp_data = None  # Latest RTP extension info.
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = None
        self._build_pipeline()


    def _build_pipeline(self):
        pipeline_str = (
            f'rtspsrc location="{self.rtsp_url}" latency={self.latency} name=src ! '
            'rtph264depay name=depay ! '
            'h264parse ! avdec_h264 ! videoconvert ! '
            'video/x-raw,format=RGB ! '
            'appsink name=appsink emit-signals=true sync=false'
        )

        logger.info("Building pipeline: %s", pipeline_str)
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            logger.error("Failed to create pipeline: %s", e)
            raise

        self.rtspsrc = self.pipeline.get_by_name("src")
        self.depay = self.pipeline.get_by_name("depay")
        self.appsink = self.pipeline.get_by_name("appsink")
        self.rtspsrc.connect("pad-added", self._on_pad_added, self.depay)
        sink_pad = self.depay.get_static_pad("sink")
        if sink_pad:
            logger.info("Adding RTP probe to depayloader sink pad.")
            sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        self.appsink.connect("new-sample", self._on_new_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)


    @staticmethod
    def _convert_ntp_to_unix(ntp_seconds, ntp_fraction):
        return ntp_seconds - 2208988800 + ntp_fraction / (2**32)


    @staticmethod
    def _format_unix_timestamp(unix_timestamp):
        return datetime.fromtimestamp(unix_timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f UTC")

    def _rtp_probe(self, pad, info):
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK

        success, rtp_buffer = GstRtp.RTPBuffer.map(buffer, Gst.MapFlags.READ)
        if not success:
            logger.error("Failed to map buffer as RTP packet.")
            return Gst.PadProbeReturn.OK

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
            ext_bytes = None

        if ext_bytes and len(ext_bytes) < 12:
            logger.warning("Extension payload too short; expected at least 12 bytes.")
            return Gst.PadProbeReturn.OK

        ntp_seconds = int.from_bytes(ext_bytes[0:4], byteorder='big')
        ntp_fraction = int.from_bytes(ext_bytes[4:8], byteorder='big')
        unix_timestamp = self._convert_ntp_to_unix(ntp_seconds, ntp_fraction)
        human_time = self._format_unix_timestamp(unix_timestamp)
        flags_and_seq = int.from_bytes(ext_bytes[8:12], byteorder='big')
        C = (flags_and_seq >> 31) & 0x01
        E = (flags_and_seq >> 30) & 0x01
        D = (flags_and_seq >> 29) & 0x01
        T = (flags_and_seq >> 28) & 0x01
        Cseq = flags_and_seq & 0xFF
        self.latest_rtp_data = {
            "human_time": human_time,
            "ntp_seconds": ntp_seconds,
            "ntp_fraction": ntp_fraction,
            "C": C,
            "E": E,
            "D": D,
            "T": T,
            "CSeq": Cseq
        }

        GstRtp.RTPBuffer.unmap(rtp_buffer)
        return Gst.PadProbeReturn.OK


    def _on_pad_added(self, src, pad, depay):
        logger.info("New pad added: %s", pad.get_name())
        caps = pad.get_current_caps()
        if not caps:
            logger.warning("No caps available on pad %s", pad.get_name())
            return
        
        structure = caps.get_structure(0)
        if not structure.get_name().startswith("application/x-rtp"):
            return
        
        logger.info("Linking RTP pad to depayloader.")
        pad.add_probe(Gst.PadProbeType.BUFFER, self._rtp_probe)
        sink_pad = depay.get_static_pad("sink")
        if not sink_pad or sink_pad.is_linked():
            return
        
        ret = pad.link(sink_pad)
        if ret == Gst.PadLinkReturn.OK:
            logger.info("Pad linked successfully.")
        else:
            logger.error("Failed to link pad %s. Error: %s", pad.get_name(), ret)


    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        buffer = sample.get_buffer()
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        pixel_format = structure.get_string("format")
        logger.debug("Received frame with format: %s (%dx%d)", pixel_format, width, height)

        # Now decide how to process the data based on the pixel format.
        if pixel_format == "RGB":  
            # Typically, "RGB" means 3 bytes per pixel.
            expected_size = width * height * 3
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected RGB frame size (%d).", len(map_info.data), expected_size)
                buffer.unmap(map_info)
                return Gst.FlowReturn.ERROR

            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))

        elif pixel_format in ("RGB16", "BGR16"):
            # For example, 16-bit formats like RGB565 use 2 bytes per pixel.
            expected_size = width * height * 2
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected 16-bit frame size (%d).", len(map_info.data), expected_size)
                buffer.unmap(map_info)
                return Gst.FlowReturn.ERROR

            # Read as 16-bit data. Depending on your needs, you might want to convert this to 8-bit.
            frame = np.frombuffer(map_info.data, dtype=np.uint16).reshape((height, width))
            # Conversion to 8-bit per channel might be done with bit shifting or using OpenCV's cvtColor if needed.
        
        elif pixel_format == "NV12":
            # For NV12, the expected size is width*height (Y plane) + width*height/2 (UV plane)
            expected_size = int(width * height * 1.5)
            if len(map_info.data) < expected_size:
                logger.error("Buffer size (%d) is smaller than expected NV12 frame size (%d).", len(map_info.data), expected_size)
                buffer.unmap(map_info)
                return Gst.FlowReturn.ERROR

            nv12_frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((int(height * 1.5), width))
            # Convert NV12 to RGB using OpenCV.
            frame = cv2.cvtColor(nv12_frame, cv2.COLOR_YUV2RGB_NV12)

        else:
            logger.error("Unhandled pixel format: %s", pixel_format)
            buffer.unmap(map_info)
            return Gst.FlowReturn.ERROR

        buffer.unmap(map_info)

        try:
            self.frame_handler_callback(frame, self.latest_rtp_data)
        except Exception as e:
            logger.error("Error in frame handler callback: %s", e)

        return Gst.FlowReturn.OK

    

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            logger.info("End-Of-Stream reached.")
            self.loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("Error: %s, Debug: %s", err, debug)
            self.loop.quit()


    def start(self):
        logger.info("Starting pipeline.")
        self.pipeline.set_state(Gst.State.PLAYING)
        try:
            self.loop.run()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down...")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            logger.info("Pipeline stopped.")


    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)
        self.loop.quit()
        logger.info("Pipeline stopped via stop() call.")
