import pytest
import os
import sys
from pathlib import Path
import types

from ax_devil_rtsp.utils import build_axis_rtsp_url
from ax_devil_rtsp.logging import setup_logging

# Configure logging for tests (DEBUG level, detailed format)
setup_logging(debug=True)

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

from enhanced_rtsp_server import dual_stream_rtsp_server

@pytest.fixture(scope="session")
def rtsp_url(rtsp_credentials, dual_stream_rtsp_server):
    """
    Provide an RTSP URL for integration tests.
    - If USE_REAL_CAMERA=true, use real device credentials.
    - Otherwise, use the local dual-stream RTSP server.
    """
    use_real = os.getenv("USE_REAL_CAMERA", "false").lower() == "true"
    if use_real:
        creds = rtsp_credentials
        # Construct the real device RTSP URL (adjust path as needed)
        return build_axis_rtsp_url(
            ip=creds["ip"],
            username=creds["username"],
            password=creds["password"],
            video_source=1,
            get_video_data=True,
            get_application_data=True,
            rtp_ext=False
        )
    else:
        # Use the local dual-stream server (video + application data)
        return dual_stream_rtsp_server
