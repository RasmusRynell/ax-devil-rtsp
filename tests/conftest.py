import pytest
import os
import logging

# Configure logging for tests
logging.basicConfig(level=logging.INFO)

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "camera_required: mark test as requiring a physical camera"
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
