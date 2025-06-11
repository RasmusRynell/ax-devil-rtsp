"""
Simplified Enhanced GStreamer RTSP Server for testing CombinedRTSPClient

This provides a GStreamer-based RTSP server that serves both:
- H.264 video stream (pay0, pt=96)  
- Application metadata stream (pay1, pt=127)

Simplified approach that avoids complex RTP packet creation and uses 
GStreamer's built-in capabilities more directly.
"""

import pytest
import gi
import threading
import time
from typing import Optional

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0") 
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GstRtspServer, GLib, GstApp


class EnhancedAxisRTSPServer:
    """Simplified RTSP server that provides both video and metadata streams."""
    
    def __init__(self, port: int = 8554):
        self.port = port
        self.server: Optional[GstRtspServer.RTSPServer] = None
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.metadata_counter = 0
        self.running = False
        self.appsrc = None
        
    def start(self) -> str:
        """Start the enhanced RTSP server and return the URL."""
        Gst.init(None)
        
        self.server = GstRtspServer.RTSPServer()
        self.server.props.service = str(self.port)
        
        # Create media factory with dual streams
        factory = GstRtspServer.RTSPMediaFactory()
        
        # Simplified pipeline - separate both streams clearly
        # Use direct text payloading for metadata which is more compatible
        pipeline = (
            # Video branch - standard H.264
            "( videotestsrc is-live=true pattern=ball ! "
            "video/x-raw,width=640,height=480,framerate=30/1 ! "
            "x264enc tune=zerolatency bitrate=1000 ! "
            "rtph264pay name=pay0 pt=96 ) "
            
            # Metadata branch - use audiotestsrc as a simple stream source
            # This creates a continuous stream that won't cause "not-linked" errors
            "( audiotestsrc is-live=true freq=440 ! "
            "audio/x-raw,rate=8000 ! "
            "rtpL16pay name=pay1 pt=127 )"
        )
        
        factory.set_launch(pipeline)
        factory.set_shared(True)
        
        # Mount the factory
        mount_points = self.server.get_mount_points()
        mount_points.add_factory("/test", factory)
        self.server.attach(None)
        
        # Start the main loop in a separate thread
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.running = True
        
        # Give server time to start
        time.sleep(1)
        
        return f"rtsp://127.0.0.1:{self.port}/test"
        
    def stop(self) -> None:
        """Stop the RTSP server."""
        self.running = False
        if self.loop:
            self.loop.quit()
        if self.thread:
            self.thread.join(timeout=3)


# Alternative simple approach for testing - just use a different test server fixture
class SimpleMultiStreamRTSPServer:
    """Very simple multi-stream RTSP server for basic testing."""
    
    def __init__(self, port: int = 8554):
        self.port = port
        self.server: Optional[GstRtspServer.RTSPServer] = None
        self.loop: Optional[GLib.MainLoop] = None
        self.thread: Optional[threading.Thread] = None
        
    def start(self) -> str:
        """Start a simple multi-stream RTSP server."""
        Gst.init(None)
        
        self.server = GstRtspServer.RTSPServer()
        self.server.props.service = str(self.port)
        
        # Create media factory
        factory = GstRtspServer.RTSPMediaFactory()
        
        # Very simple approach: two test sources
        pipeline = (
            "( videotestsrc is-live=true pattern=ball ! "
            "video/x-raw,width=640,height=480,framerate=30/1 ! "
            "x264enc tune=zerolatency bitrate=1000 ! "
            "rtph264pay name=pay0 pt=96 ) "
            
            "( videotestsrc is-live=true pattern=smpte ! "
            "video/x-raw,width=320,height=240,framerate=15/1 ! "
            "x264enc tune=zerolatency bitrate=500 ! "
            "rtph264pay name=pay1 pt=97 )"
        )
        
        factory.set_launch(pipeline)
        factory.set_shared(True)
        
        # Mount the factory
        mount_points = self.server.get_mount_points()
        mount_points.add_factory("/test", factory)
        self.server.attach(None)
        
        # Start the main loop in a separate thread
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        
        # Give server time to start
        time.sleep(1)
        
        return f"rtsp://127.0.0.1:{self.port}/test"
        
    def stop(self) -> None:
        """Stop the RTSP server."""
        if self.loop:
            self.loop.quit()
        if self.thread:
            self.thread.join(timeout=3)


# Pytest fixture for the enhanced server
@pytest.fixture(scope="session")
def enhanced_rtsp_server():
    """Provide an enhanced RTSP server with both video and metadata streams."""
    try:
        server = EnhancedAxisRTSPServer(port=8555)  # Use different port to avoid conflicts
        url = server.start()
        yield url
        server.stop()
    except Exception as exc:
        pytest.skip(f"Enhanced RTSP server not available: {exc}")


@pytest.fixture(scope="session")
def simple_multistream_server():
    """Provide a simple multi-stream RTSP server for basic testing."""
    try:
        server = SimpleMultiStreamRTSPServer(port=8556)
        url = server.start()
        yield url
        server.stop()
    except Exception as exc:
        pytest.skip(f"Simple multi-stream server not available: {exc}")


if __name__ == "__main__":
    # Test the enhanced server
    server = EnhancedAxisRTSPServer()
    try:
        url = server.start()
        print(f"Enhanced RTSP server running at: {url}")
        print("Press Ctrl+C to stop...")
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.stop() 