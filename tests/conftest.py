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
    
    Uses the AxisRTSPServer class from enhanced_rtsp_server.py
    """
    try:
        from tests.enhanced_rtsp_server import AxisRTSPServer
    except ImportError as e:
        pytest.skip(f"Test server dependencies not available: {e}")
    
    try:
        server = AxisRTSPServer(port=8554)
        url = server.start()
        print(f"\n🖥️  RTSP TEST SERVER RUNNING: {url}")
        print("   Clients MUST connect via actual RTSP protocol")
        yield url
        server.stop()
    except Exception as exc:
        # Don't skip - let the test fail! This indicates a real problem
        raise RuntimeError(f"RTSP test server failed to start: {exc}") from exc

@pytest.fixture(scope="session")
def axis_metadata_rtsp_server():
    """
    RTSP server that mimics Axis camera with BOTH video and application metadata streams.
    
    This serves the combined stream that CombinedRTSPClient expects.
    Clients must connect via RTSP protocol to receive both streams.
    
    Uses the DualStreamAxisRTSPServer class from enhanced_rtsp_server.py
    """
    try:
        from tests.enhanced_rtsp_server import DualStreamAxisRTSPServer
    except ImportError as e:
        pytest.skip(f"Test server dependencies not available: {e}")
    
    try:
        server = DualStreamAxisRTSPServer(port=8555)
        url = server.start()
        print(f"\n🎬 DUAL-STREAM RTSP SERVER: {url}")
        yield url
        server.stop()
    except Exception as exc:
        # Don't skip - let the test fail! This indicates a real problem
        raise RuntimeError(f"Dual-stream RTSP test server failed to start: {exc}") from exc

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
    
    Uses dual-stream server that provides both video and metadata streams
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