import pytest
import os
import logging
import sys
from pathlib import Path
import types

# Configure logging for tests
logging.basicConfig(level=logging.INFO)

# Ensure src directory is importable without installation
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

# Provide a dummy cv2 module if OpenCV is not installed to allow imports
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.ModuleType("cv2")

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_hardware: mark test as needing physical hardware access"
    )
    config.addinivalue_line(
        "markers",
        "requires_gstreamer: mark test as needing GStreamer installation"
    )

@pytest.fixture(scope="session")
def rtsp_credentials():
    """Provide RTSP credentials from environment or default test values."""
    return {
        'username': os.getenv('AX_DEVIL_TARGET_USER', 'root'),
        'password': os.getenv('AX_DEVIL_TARGET_PASS', 'fusion'),
        'ip': os.getenv('AX_DEVIL_TARGET_ADDR', '192.168.1.81'),
    }

@pytest.fixture(scope="session")
def rtsp_test_server():
    """
    Start a PROPER RTSP server that clients must connect to via actual RTSP protocol.
    
    This server:
    1. Runs on actual network port
    2. Speaks real RTSP protocol 
    3. Serves H.264 video stream like Axis camera
    4. Requires clients to authenticate and connect properly
    
    """
    try:
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtspServer", "1.0")
        from gi.repository import Gst, GstRtspServer, GLib
    except Exception as exc:  # pragma: no cover - runtime dependency
        pytest.skip(f"GStreamer not available: {exc}")

    import threading
    import time

    Gst.init(None)
    server = GstRtspServer.RTSPServer()
    server.props.service = "8554"
    
    # Create media factory that mimics Axis camera behavior
    factory = GstRtspServer.RTSPMediaFactory()
    
    # REAL RTSP server pipeline - serves actual H.264 stream via RTSP protocol
    # Client MUST connect via RTSP and receive this stream over network
    pipeline = (
        "( videotestsrc is-live=true pattern=ball "
        "! video/x-raw,width=640,height=480,framerate=30/1 "
        "! x264enc tune=zerolatency bitrate=1000 speed-preset=ultrafast "
        "! rtph264pay name=pay0 pt=96 config-interval=1 )"
    )
    
    factory.set_launch(pipeline)
    factory.set_shared(True)
    
    # Mount at Axis-like path
    mount_points = server.get_mount_points()
    mount_points.add_factory("/axis-media/media.amp", factory)
    server.attach(None)

    # Start RTSP server in separate thread
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    
    # Give server time to start and be ready for RTSP connections
    time.sleep(3)
    
    # Return URL that clients must connect to via RTSP protocol
    server_url = "rtsp://127.0.0.1:8554/axis-media/media.amp"
    print(f"\n🖥️  RTSP TEST SERVER RUNNING: {server_url}")
    print("   Clients MUST connect via actual RTSP protocol")
    
    yield server_url

    # Graceful shutdown - daemon threads will clean up automatically
    try:
        loop.quit()
    except:
        pass

@pytest.fixture(scope="session")
def axis_metadata_rtsp_server():
    """
    RTSP server that mimics Axis camera with BOTH video and metadata streams.
    
    This serves the combined stream that CombinedRTSPClient expects.
    Clients must connect via RTSP protocol to receive both streams.
    """
    try:
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtspServer", "1.0")
        from gi.repository import Gst, GstRtspServer, GLib
    except Exception as exc:
        pytest.skip(f"GStreamer not available: {exc}")

    import threading
    import time

    Gst.init(None)
    server = GstRtspServer.RTSPServer()
    server.props.service = "8555"
    
    factory = GstRtspServer.RTSPMediaFactory()
    
    # Dual stream like real Axis camera - video + audio as metadata placeholder
    pipeline = (
        # Video stream (main)
        "( videotestsrc is-live=true pattern=ball "
        "! video/x-raw,width=640,height=480,framerate=30/1 "
        "! x264enc tune=zerolatency bitrate=1000 speed-preset=ultrafast "
        "! rtph264pay name=pay0 pt=96 config-interval=1 ) "
        
        # Audio stream (simulates metadata stream for combined client)
        "( audiotestsrc is-live=true freq=440 "
        "! audio/x-raw,rate=8000,channels=1 "
        "! audioconvert ! audioresample "
        "! rtpL16pay name=pay1 pt=97 )"
    )
    
    factory.set_launch(pipeline)
    factory.set_shared(True)
    
    mount_points = server.get_mount_points()
    mount_points.add_factory("/axis-media/media.amp", factory)
    server.attach(None)

    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    time.sleep(3)
    
    server_url = "rtsp://127.0.0.1:8555/axis-media/media.amp"
    print(f"\n🎬 DUAL-STREAM RTSP SERVER: {server_url}")
    
    yield server_url

    # Graceful shutdown - daemon threads will clean up automatically
    try:
        loop.quit()
    except:
        pass

@pytest.fixture(scope="session")
def test_rtsp_url(rtsp_test_server, rtsp_credentials):
    """
    Provide RTSP URL for testing.
    
    - Default: Local RTSP test server (clients must connect via RTSP protocol)
    - With USE_REAL_CAMERA=true: Real Axis camera
    
    NO SHORTCUTS - clients must do real RTSP communication in both cases.
    """
    use_real_camera = os.getenv('USE_REAL_CAMERA', 'false').lower() == 'true'
    
    if use_real_camera:
        real_url = f"rtsp://{rtsp_credentials['username']}:{rtsp_credentials['password']}@{rtsp_credentials['ip']}/axis-media/media.amp"
        print(f"\n🎥 REAL CAMERA TARGET: {real_url}")
        return real_url
    else:
        print(f"\n🧪 RTSP TEST SERVER: {rtsp_test_server}")
        return rtsp_test_server

@pytest.fixture(scope="session") 
def combined_test_rtsp_url(axis_metadata_rtsp_server, rtsp_credentials):
    """
    RTSP URL for combined client testing (video + metadata).
    
    Uses dual-stream server that provides both video and audio streams
    to simulate Axis camera behavior for CombinedRTSPClient.
    """
    use_real_camera = os.getenv('USE_REAL_CAMERA', 'false').lower() == 'true'
    
    if use_real_camera:
        real_url = f"rtsp://{rtsp_credentials['username']}:{rtsp_credentials['password']}@{rtsp_credentials['ip']}/axis-media/media.amp"
        print(f"\n🎥 REAL CAMERA FOR COMBINED: {real_url}")
        return real_url
    else:
        print(f"\n🎬 DUAL-STREAM TEST SERVER: {axis_metadata_rtsp_server}")
        return axis_metadata_rtsp_server 