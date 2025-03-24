#!/usr/bin/env python3
"""
RTSPMetadataClient Library

This library provides a class RTSPMetadataClient that can be used to receive
Axis metadata streams (XML) via GStreamer and process complete XML messages via
a user-provided callback.
"""

import logging
import gi
from gi.repository import Gst, GLib

logger = logging.getLogger(__name__)

class RTSPMetadataClient:
    def __init__(self, rtsp_url, latency=100, metadata_handler_callback=None):
        """
        Initialize the RTSP metadata client.

        Args:
            rtsp_url (str): The full RTSP URL for the metadata stream.
            latency (int): The latency setting for rtspsrc (in milliseconds).
            metadata_handler_callback (callable): A callback function accepting a complete XML message as bytes.
        """
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.metadata_handler_callback = metadata_handler_callback
        self.xml_buffer = b""
        Gst.init(None)
        self.loop = GLib.MainLoop()
        self.pipeline = None
        self._build_pipeline()

    def _build_pipeline(self):
        # Build a pipeline that pulls data from the RTSP source directly into an appsink.
        pipeline_str = (
            f'rtspsrc location="{self.rtsp_url}" latency={self.latency} name=src ! '
            'appsink name=appsink emit-signals=true sync=false'
        )
        logger.info("Building metadata pipeline: %s", pipeline_str)
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            logger.error("Failed to create metadata pipeline: %s", e)
            raise

        self.rtspsrc = self.pipeline.get_by_name("src")
        self.appsink = self.pipeline.get_by_name("appsink")

        # When rtspsrc adds a new pad, link it to the appsink.
        self.rtspsrc.connect("pad-added", self._on_pad_added)
        self.appsink.connect("new-sample", self._on_new_sample)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _on_pad_added(self, src, pad):
        caps = pad.get_current_caps()
        if not caps:
            logger.warning("No caps available on pad %s", pad.get_name())
            return
        structure = caps.get_structure(0)
        if structure.get_name() != "application/x-rtp":
            logger.info("Ignoring pad with caps: %s", structure.get_name())
            return

        sink_pad = self.appsink.get_static_pad("sink")
        if sink_pad.is_linked():
            return

        ret = pad.link(sink_pad)
        if ret == Gst.PadLinkReturn.OK:
            logger.info("Pad linked successfully to metadata appsink.")
        else:
            logger.error("Failed to link pad %s. Error: %s", pad.get_name(), ret)

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())

        if len(data) < 12:
            logger.warning("Received data is too small to contain a valid RTP header.")
            return Gst.FlowReturn.OK  # Ignore and continue

        # Extract RTP header
        marker = (data[1] >> 7) & 0x01
        payload_offset = 12  # Base RTP header size

        # Handle RTP header extension (skip extension if present)
        extension_bit = (data[0] >> 4) & 0x01
        if extension_bit:
            if len(data) >= payload_offset + 4:
                ext_header_length = int.from_bytes(data[payload_offset + 2:payload_offset + 4], 'big') * 4
                payload_offset += 4 + ext_header_length

        # Extract payload
        payload = data[payload_offset:]

        if not payload:
            logger.warning("Received empty RTP payload.")
            return Gst.FlowReturn.OK

        # Accumulate payload in buffer
        self.xml_buffer += payload

        # If marker is set, try decoding full XML message
        if marker == 1:
            try:
                xml_text = self.xml_buffer.decode('utf-8')

                if not xml_text.lstrip().startswith("<"):
                    logger.warning("Final accumulated data does not look like XML: %s", xml_text[:50])
                else:
                    if self.metadata_handler_callback:
                        self.metadata_handler_callback(self.xml_buffer)
                    else:
                        print("----- Received XML Metadata -----")
                        print(xml_text)

            except UnicodeDecodeError as e:
                logger.error("Error decoding XML metadata: %s", e)

            # Clear buffer after processing
            self.xml_buffer = b""

        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus, message):
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            logger.info("End-Of-Stream reached for metadata.")
            self.loop.quit()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("Metadata error: %s, Debug: %s", err, debug)
            self.loop.quit()

    def start(self):
        logger.info("Starting metadata pipeline.")
        self.pipeline.set_state(Gst.State.PLAYING)
        try:
            self.loop.run()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down metadata pipeline...")
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            logger.info("Metadata pipeline stopped.")

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)
        self.loop.quit()
        logger.info("Metadata pipeline stopped via stop() call.")
