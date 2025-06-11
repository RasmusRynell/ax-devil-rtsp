import importlib
import sys
import types
from unittest.mock import patch

import pytest


@pytest.fixture()
def cli_module(monkeypatch):
    """Import the CLI module with optional dependencies mocked."""
    if "gi" not in sys.modules:
        dummy_gi = types.ModuleType("gi")
        dummy_gi.require_version = lambda *a, **kw: None
        dummy_repo = types.ModuleType("gi.repository")
        for name in ["Gst", "GstRtp", "GstRtsp", "GLib"]:
            setattr(dummy_repo, name, types.ModuleType(name))
        dummy_gi.repository = dummy_repo
        monkeypatch.setitem(sys.modules, "gi", dummy_gi)
        monkeypatch.setitem(sys.modules, "gi.repository", dummy_repo)
    if "cv2" not in sys.modules:
        monkeypatch.setitem(sys.modules, "cv2", types.ModuleType("cv2"))
    module = importlib.import_module("ax_devil_rtsp.examples.cli")
    return module


class TestRTSPURLBuilding:
    """Test RTSP URL building functionality."""

    def test_build_rtsp_url_basic(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = "192.168.1.100"
            username = "admin"
            password = "secret"
            source = "1"
            no_video = False
            no_metadata = False
            rtp_ext = True

        url = cli_module.build_rtsp_url(MockArgs())

        assert url.startswith(
            "rtsp://admin:secret@192.168.1.100/axis-media/media.amp"
        )
        assert "onvifreplayext=1" in url
        assert "analytics=polygon" in url
        assert "camera=1" in url

    def test_build_rtsp_url_no_credentials(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = "192.168.1.100"
            username = ""
            password = ""
            source = "1"
            no_video = False
            no_metadata = False
            rtp_ext = True

        url = cli_module.build_rtsp_url(MockArgs())

        assert url.startswith("rtsp://192.168.1.100/axis-media/media.amp")
        assert "@" not in url.split("/")[2]

    def test_build_rtsp_url_video_only(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = "192.168.1.100"
            username = "admin"
            password = "secret"
            source = "1"
            no_video = False
            no_metadata = True
            rtp_ext = True

        url = cli_module.build_rtsp_url(MockArgs())

        assert "analytics=polygon" not in url
        assert "onvifreplayext=1" in url

    def test_build_rtsp_url_metadata_only(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = "192.168.1.100"
            username = "admin"
            password = "secret"
            source = "1"
            no_video = True
            no_metadata = False
            rtp_ext = True

        url = cli_module.build_rtsp_url(MockArgs())

        assert "video=0" in url
        assert "audio=0" in url
        assert "analytics=polygon" in url

    def test_build_rtsp_url_with_provided_url(self, cli_module):
        class MockArgs:
            rtsp_url = "rtsp://test:test@192.168.1.50/custom/path"
            ip = "192.168.1.100"
            username = "admin"
            password = "secret"
            source = "1"
            no_video = False
            no_metadata = False
            rtp_ext = True

        url = cli_module.build_rtsp_url(MockArgs())

        assert url == "rtsp://test:test@192.168.1.50/custom/path"

    def test_build_rtsp_url_no_ip_raises_error(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = None
            username = "admin"
            password = "secret"
            source = "1"
            no_video = False
            no_metadata = False
            rtp_ext = True

        with pytest.raises(ValueError, match="No IP address provided"):
            cli_module.build_rtsp_url(MockArgs())

    def test_build_rtsp_url_nothing_requested_raises_error(self, cli_module):
        class MockArgs:
            rtsp_url = None
            ip = "192.168.1.100"
            username = "admin"
            password = "secret"
            source = "1"
            no_video = True
            no_metadata = True
            rtp_ext = True

        with pytest.raises(ValueError, match="You cannot ask for nothing"):
            cli_module.build_rtsp_url(MockArgs())
