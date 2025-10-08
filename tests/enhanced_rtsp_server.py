"""
Enhanced GStreamer RTSP Server for testing CombinedRTSPClient

This provides a GStreamer-based RTSP server that serves both:
- H.264 video stream (pay0, pt=96)  
- Application data stream (pay1, pt=127) with XML payloads

The application data stream uses proper application/x-rtp caps with media=application
to be correctly detected by CombinedRTSPClient.
"""

import pytest
import gi
import socket
import threading
import time
import xml.sax.saxutils
from contextlib import closing
from typing import Optional
from ax_devil_rtsp.logging import get_logger

logger = get_logger(__name__)

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0") 
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GstRtspServer, GLib, GstApp


class AxisRTSPServer:
    """RTSP server that provides H.264 video stream only (for basic testing)."""
    
    def __init__(self, port: int = 8554):
        self.port = port
        self.server: Optional[GstRtspServer.RTSPServer] = None
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
    def start(self) -> str:
        """Start the basic RTSP server and return the URL."""
        Gst.init(None)
        
        self.server = GstRtspServer.RTSPServer()
        self.server.props.service = str(self.port)
        
        # Create media factory for single video stream
        factory = GstRtspServer.RTSPMediaFactory()
        
        # Basic video-only pipeline
        pipeline = (
            "( videotestsrc is-live=true pattern=ball "
            "! video/x-raw,width=640,height=480,framerate=30/1 "
            "! x264enc tune=zerolatency bitrate=1000 speed-preset=ultrafast "
            "! rtph264pay name=pay0 pt=96 config-interval=1 )"
        )
        
        factory.set_launch(pipeline)
        factory.set_shared(True)
        
        # Mount the factory
        mount_points = self.server.get_mount_points()
        mount_points.add_factory("/axis-media/media.amp", factory)
        self.server.attach(None)
        
        # Start the main loop in a separate thread
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.running = True
        
        # Give server time to start
        time.sleep(1)
        
        url = f"rtsp://127.0.0.1:{self.port}/axis-media/media.amp"
        logger.info(f"AxisRTSPServer started at {url}")
        return url
        
    def stop(self) -> None:
        """Stop the RTSP server."""
        self.running = False
        if self.loop:
            self.loop.quit()
        if self.thread:
            self.thread.join(timeout=3)
        logger.info(f"AxisRTSPServer on port {self.port} stopped.")


class DualStreamAxisRTSPServer:
    """RTSP server that provides both video and application data streams (like real Axis cameras)."""
    
    def __init__(self, port: int = 8555):
        self.port = port
        self.server: Optional[GstRtspServer.RTSPServer] = None
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
    def start(self) -> str:
        """Start the dual-stream RTSP server and return the URL."""
        Gst.init(None)
        
        self.server = GstRtspServer.RTSPServer()
        self.server.props.service = str(self.port)
        
        factory = GstRtspServer.RTSPMediaFactory()
        
        # Dual stream pipeline - video + application data
        pipeline = (
            # Video stream (main)
            "( videotestsrc is-live=true pattern=ball "
            "! video/x-raw,width=640,height=480,framerate=30/1 "
            "! x264enc tune=zerolatency bitrate=1000 speed-preset=ultrafast "
            "! rtph264pay name=pay0 pt=96 config-interval=1 ) "
            
            # Application data stream - direct RTP packet creation
            "( appsrc name=pay1 is-live=true format=time block=true "
            "caps=\"application/x-rtp,media=application,clock-rate=90000,encoding-name=X-METADATA,payload=127\" )"
        )
        
        factory.set_launch(pipeline)
        factory.set_shared(True)
        
        # Connect to media-prepared signal to setup application data per client
        factory.connect("media-configure", self._on_media_configure)
        
        # Mount the factory
        mount_points = self.server.get_mount_points()
        mount_points.add_factory("/axis-media/media.amp", factory)
        self.server.attach(None)
        
        # Start the main loop in a separate thread
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.running = True
        
        # Give server time to start
        time.sleep(2)
        
        url = f"rtsp://127.0.0.1:{self.port}/axis-media/media.amp"
        logger.info(f"DualStreamAxisRTSPServer started at {url}")
        return url
    
    def _on_media_configure(self, factory, media):
        """Called when media is configured for each client - setup isolated application data generation."""
        def setup_application_data():
            pipeline = media.get_element()
            if not pipeline:
                logger.error("No pipeline found in media configuration.")
                return
                
            appsrc = pipeline.get_by_name("pay1")
            if not appsrc:
                logger.error("No appsrc named 'pay1' found in pipeline.")
                return
                
            # Configure appsrc for this specific media instance
            appsrc.props.format = Gst.Format.TIME
            appsrc.props.is_live = True
            appsrc.props.max_latency = 100000000  # 100ms
            appsrc.props.min_latency = 0
            appsrc.props.do_timestamp = True
            
            # Each media instance gets its own isolated state
            media.appsrc = appsrc
            media.application_data_counter = 0  # Isolated counter per media instance
            media.timer_active = True
            
            def push_application_data():
                # Check if this media instance is still active
                if not self.running or not hasattr(media, 'appsrc') or not media.appsrc:
                    return False
                if not hasattr(media, 'timer_active') or not media.timer_active:
                    return False
                    
                media.application_data_counter += 1
                
                # Generate clean, well-formed scene metadata XML
                xml_data = f'<?xml version="1.0" encoding="UTF-8"?><tns:MetadataStream xmlns:tns="http://www.onvif.org/ver10/schema"><tns:Event><tns:Source><tns:SimpleItem Name="VideoSourceConfigurationToken" Value="1"/><tns:SimpleItem Name="Rule" Value="MotionDetection"/></tns:Source><tns:Data><tns:SimpleItem Name="State" Value="true"/><tns:SimpleItem Name="Counter" Value="{media.application_data_counter}"/></tns:Data></tns:Event></tns:MetadataStream>'
                
                xml_bytes = xml_data.encode('utf-8')
                
                # Create proper RTP packet with complete XML payload
                sequence_num = media.application_data_counter & 0xFFFF
                timestamp_rtp = (media.application_data_counter * 4050) & 0xFFFFFFFF  # 90kHz clock
                ssrc = 0x12345678
                
                # RTP Header (12 bytes) - always mark as complete message
                rtp_header = bytearray(12)
                rtp_header[0] = 0x80  # V=2, P=0, X=0, CC=0
                rtp_header[1] = 0xFF  # M=1 (marker), PT=127 - complete in one packet
                rtp_header[2:4] = sequence_num.to_bytes(2, 'big')
                rtp_header[4:8] = timestamp_rtp.to_bytes(4, 'big') 
                rtp_header[8:12] = ssrc.to_bytes(4, 'big')
                
                # Combine RTP header with complete XML payload
                rtp_packet = bytes(rtp_header) + xml_bytes
                buffer = Gst.Buffer.new_allocate(None, len(rtp_packet), None)
                buffer.fill(0, rtp_packet)
                
                # Set timestamps - 2Hz application data (500ms intervals)
                timestamp = media.application_data_counter * Gst.SECOND // 2
                buffer.pts = timestamp
                buffer.dts = timestamp
                buffer.duration = Gst.SECOND // 2  # 500ms duration per sample
                
                # Push the complete RTP packet
                try:
                    ret = media.appsrc.emit('push-buffer', buffer)
                    return ret == Gst.FlowReturn.OK and media.timer_active
                except Exception as exc:
                    logger.error(f"Error pushing application data buffer: {exc}")
                    return False
            
            # Start application data generation at 2Hz for this specific media instance
            media.application_data_timer = GLib.timeout_add(500, push_application_data)
            
            # Connect to media teardown to clean up properly
            def on_unprepared():
                """Clean up when media is unprepared (client disconnects)."""
                if hasattr(media, 'timer_active'):
                    media.timer_active = False
                if hasattr(media, 'application_data_timer'):
                    GLib.source_remove(media.application_data_timer)
                    delattr(media, 'application_data_timer')
            
            # Connect cleanup to media lifecycle
            media.connect('unprepared', lambda m: on_unprepared())
        
        GLib.idle_add(setup_application_data)
        
    def stop(self) -> None:
        """Stop the RTSP server and clean up all resources."""
        self.running = False
        
        # The individual media cleanup handles their timers via on_unprepared callbacks (application data)
        # when clients disconnect, so no additional cleanup needed here
        
        if self.loop and self.loop.is_running():
            self.loop.quit()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        logger.info(f"DualStreamAxisRTSPServer on port {self.port} stopped.")


# Pytest fixtures using the cleaned-up server classes
@pytest.fixture(scope="session")
def rtsp_server():
    """Provide basic RTSP server with video-only stream."""
    try:
        server = AxisRTSPServer(port=8554)
        url = server.start()
        yield url
        server.stop()
    except Exception as exc:
        # Don't skip - let the test fail! This indicates a real problem
        raise RuntimeError(f"RTSP server failed to start: {exc}") from exc


def _pick_available_port(preferred: int = 8555) -> int:
    """Return an available TCP port, preferring the supplied value."""

    def port_free(candidate: int) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                return False
        return True

    candidate_ports = [preferred] + list(range(preferred + 1, preferred + 6))
    for candidate in candidate_ports:
        if port_free(candidate):
            return candidate

    # Fallback: ask OS for an ephemeral port and return it
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def dual_stream_rtsp_server():
    """Provide enhanced RTSP server with both video and application data streams."""

    last_error: Optional[Exception] = None
    for _ in range(8):
        port = _pick_available_port()
        server = DualStreamAxisRTSPServer(port=port)
        try:
            url = server.start()
        except Exception as exc:  # pragma: no cover - defensive path
            last_error = exc
            try:
                server.stop()
            except Exception:
                logger.exception("Error stopping failed RTSP server")
            continue

        try:
            yield url
            return
        finally:
            server.stop()

    # Don't skip - let the test fail! This indicates a real problem
    raise RuntimeError("Dual-stream RTSP server failed to start") from last_error


if __name__ == "__main__":
    # Test the dual-stream server
    server = DualStreamAxisRTSPServer()
    try:
        url = server.start()
        print(f"Dual-stream RTSP server running at: {url}")
        print("Press Ctrl+C to stop...")
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.stop() 
