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
def rtsp_url(rtsp_credentials):
    """Construct RTSP URL for testing."""
    return f"rtsp://{rtsp_credentials['username']}:{rtsp_credentials['password']}@{rtsp_credentials['ip']}/axis-media/media.amp"


@pytest.fixture(scope="session")
def gst_rtsp_server():
    """Start a local RTSP server using GStreamer's gst-rtsp-server."""
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
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_launch(
        "( videotestsrc is-live=true ! x264enc tune=zerolatency ! rtph264pay name=pay0 pt=96 )"
    )
    factory.set_shared(True)
    mount_points = server.get_mount_points()
    mount_points.add_factory("/test", factory)
    server.attach(None)

    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    time.sleep(1)

    yield "rtsp://127.0.0.1:8554/test"

    loop.quit()
    thread.join(timeout=5)
