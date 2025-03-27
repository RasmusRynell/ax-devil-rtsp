#!/usr/bin/env python3
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import logging

logger = logging.getLogger("ax-devil-rtsp.metadata")

class SceneMetadataClient:
    """
    A production-ready GStreamer RTSP client for retrieving Axis Scene Metadata
    without using the GStreamer ONVIF depayloader. This version builds a pipeline
    that:
      - Forces TCP transport via rtspsrc.
      - Uses rtpjitterbuffer for handling packet reordering.
      - Filters for RTP packets of media type "application".
      - Uses appsink to receive raw RTP packets.
    
    The RTP packets are manually depayloaded by parsing the header to extract the XML
    payload. The code accumulates fragments until the RTP marker bit indicates the end
    of the current XML message.
    """

    def __init__(self, rtsp_url, latency=100, raw_data_callback=None):
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.raw_data_callback = raw_data_callback
        self.xml_buffer = b""
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("axis_metadata_pipeline")
        if not self.pipeline:
            logger.error("Failed to create pipeline")
            raise Exception("Pipeline creation failed")
        self._build_pipeline()

    def _build_pipeline(self):
        # Create rtspsrc and configure properties
        self.src = Gst.ElementFactory.make("rtspsrc", "src")
        if not self.src:
            logger.error("Failed to create rtspsrc element")
            raise Exception("Element creation failed: rtspsrc")
        self.src.set_property("location", self.rtsp_url)
        self.src.set_property("latency", self.latency)
        self.src.set_property("protocols", "tcp")

        # Create rtpjitterbuffer to handle RTP reordering
        self.jitter = Gst.ElementFactory.make("rtpjitterbuffer", "jitter")
        if not self.jitter:
            logger.error("Failed to create rtpjitterbuffer element")
            raise Exception("Element creation failed: rtpjitterbuffer")

        # Create a capsfilter to select only metadata RTP packets
        self.capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        if not self.capsfilter:
            logger.error("Failed to create capsfilter element")
            raise Exception("Element creation failed: capsfilter")
        caps = Gst.Caps.from_string("application/x-rtp, media=application")
        self.capsfilter.set_property("caps", caps)

        # Create appsink to receive the raw RTP packets
        self.appsink = Gst.ElementFactory.make("appsink", "appsink")
        if not self.appsink:
            logger.error("Failed to create appsink element")
            raise Exception("Element creation failed: appsink")
        self.appsink.set_property("emit-signals", True)
        self.appsink.set_property("sync", False)

        # Add elements to the pipeline
        for element in [self.src, self.jitter, self.capsfilter, self.appsink]:
            self.pipeline.add(element)

        # Link static elements: rtpjitterbuffer -> capsfilter -> appsink
        for element1, element2 in [(self.jitter, self.capsfilter), (self.capsfilter, self.appsink)]:
            if not element1.link(element2):
                logger.error("Failed to link %s to %s", element1.get_name(), element2.get_name())
                raise Exception("Static linking failed")

        # Connect dynamic pad from rtspsrc to the jitterbuffer
        self.src.connect("pad-added", self._on_pad_added)
        # Connect appsink new-sample signal
        self.appsink.connect("new-sample", self._on_new_sample)

        # Setup bus message handling
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        logger.debug("Pipeline built successfully")

    def _on_pad_added(self, src, pad):
        """
        Callback for dynamically added pads from rtspsrc. Only links pads
        with media type "application" (metadata).
        """
        caps = pad.get_current_caps()
        if not caps:
            logger.warning("No caps available on pad: %s", pad.get_name())
            return

        structure = caps.get_structure(0)
        media_type = structure.get_string("media")
        if media_type != "application":
            logger.debug("Ignoring pad '%s' with media type '%s'", pad.get_name(), media_type)
            return

        logger.debug("Linking pad '%s' to rtpjitterbuffer", pad.get_name())
        sink_pad = self.jitter.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            ret = pad.link(sink_pad)
            if ret == Gst.PadLinkReturn.OK:
                logger.debug("Pad linked successfully")
            else:
                logger.error("Failed to link pad '%s': %s", pad.get_name(), ret)
        else:
            logger.debug("Jitterbuffer sink pad is already linked or unavailable")

    def _on_new_sample(self, sink):
        """
        Callback for each new sample from appsink. It manually parses the RTP packet:
         - Extracts the header length (taking CSRC count into account).
         - Reads the marker bit to determine if the current XML message is complete.
         - Accumulates payload fragments until the XML message is complete,
           then decodes and passes the XML text to the callback.
        """
        sample = sink.emit("pull-sample")
        if not sample:
            logger.error("Failed to retrieve sample from appsink")
            return Gst.FlowReturn.ERROR

        buffer = sample.get_buffer()
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if not success:
            logger.error("Failed to map buffer for reading")
            return Gst.FlowReturn.ERROR

        raw_data = map_info.data

        # Verify minimum RTP header length
        if len(raw_data) < 12:
            logger.error("RTP packet too short: expected >=12 bytes, got %d bytes", len(raw_data))
            buffer.unmap(map_info)
            return Gst.FlowReturn.ERROR

        # Compute RTP header length based on CSRC count
        csrc_count = raw_data[0] & 0x0F
        header_length = 12 + (4 * csrc_count)
        if len(raw_data) < header_length:
            logger.error("Incomplete RTP header: expected %d bytes, got %d bytes", header_length, len(raw_data))
            buffer.unmap(map_info)
            return Gst.FlowReturn.ERROR

        # Extract marker bit from the second byte
        marker = (raw_data[1] & 0x80) != 0

        # Extract payload (after RTP header) and accumulate
        payload = raw_data[header_length:]
        self.xml_buffer += payload

        if marker:
            # Marker indicates this packet is the end of the current XML message
            start_index = self.xml_buffer.find(b'<')
            if start_index == -1:
                logger.error("XML start '<' not found in accumulated data. Discarding payload")
                self.xml_buffer = b""
            else:
                xml_payload = self.xml_buffer[start_index:]
                try:
                    xml_text = xml_payload.decode("utf-8")
                    if not xml_text.lstrip().startswith("<"):
                        logger.error("Decoded XML metadata does not start with '<', discarding payload")
                    else:
                        logger.debug("Complete XML metadata received (length: %d)", len(xml_text))
                        if self.raw_data_callback:
                            try:
                                self.raw_data_callback(xml_text)
                            except Exception as e:
                                logger.error("Error in raw_data_callback: %s", e)
                except UnicodeDecodeError as e:
                    logger.error("Error decoding XML metadata: %s", e)
                # Reset accumulation buffer
                self.xml_buffer = b""

        buffer.unmap(map_info)
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus, message):
        """Handle EOS and error messages on the bus."""
        t = message.type
        if t == Gst.MessageType.EOS:
            logger.info("End-Of-Stream reached")
            self.loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("GStreamer Error: %s, Debug: %s", err, debug)
            self.loop.quit()

    def start(self):
        """Start the GStreamer pipeline and run the main loop."""
        logger.info("Starting SceneMetadataClient pipeline")
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to set pipeline to PLAYING state")
            raise RuntimeError("Pipeline failed to start")
        try:
            self.loop.run()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Stopping pipeline")
        finally:
            self.stop()

    def stop(self):
        """Stop the pipeline and quit the main loop."""
        logger.info("Stopping SceneMetadataClient pipeline")
        self.pipeline.set_state(Gst.State.NULL)
        self.loop.quit()
        logger.debug("Pipeline stopped")
