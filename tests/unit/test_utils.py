import importlib
import sys
import types
import xml.etree.ElementTree as ET
import logging

import pytest


@pytest.fixture()
def utils_module(monkeypatch):
    """Import utils with minimal dependencies."""
    if "gi" not in sys.modules:
        monkeypatch.setitem(sys.modules, "gi", types.ModuleType("gi"))
    module = importlib.import_module("ax_devil_rtsp.utils")
    return module


class TestParseMetadataXml:
    """Test the metadata XML parsing functionality."""

    def test_parse_valid_xml(self, utils_module):
        xml_data = b'''<?xml version="1.0" encoding="UTF-8"?>
        <tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">
            <tt:VideoAnalytics>
                <tt:Frame UtcTime="2023-01-01T12:00:00.000Z">
                    <tt:Object ObjectId="1">
                        <tt:Type>Human</tt:Type>
                    </tt:Object>
                    <tt:Object ObjectId="2">
                        <tt:Type>Vehicle</tt:Type>
                    </tt:Object>
                </tt:Frame>
            </tt:VideoAnalytics>
        </tt:MetadataStream>'''

        result = utils_module.parse_metadata_xml(xml_data)

        assert result is not None
        assert "objects" in result
        assert len(result["objects"]) == 2
        assert result["objects"][0]["id"] == "1"
        assert result["objects"][0]["type"] == "Human"
        assert result["objects"][1]["id"] == "2"
        assert result["objects"][1]["type"] == "Vehicle"
        assert result["utc_time"] == "2023-01-01T12:00:00.000Z"
        assert "raw_xml" in result

    def test_parse_empty_xml(self, utils_module):
        xml_data = b'''<?xml version="1.0" encoding="UTF-8"?>
        <tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">
        </tt:MetadataStream>'''

        result = utils_module.parse_metadata_xml(xml_data)

        assert result is not None
        assert result["objects"] == []
        assert result["utc_time"] is None

    def test_parse_invalid_xml(self, utils_module):
        xml_data = b"<invalid>xml<content>"

        result = utils_module.parse_metadata_xml(xml_data)

        assert result is None

    def test_parse_unicode_decode_error(self, utils_module):
        xml_data = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?><test>\xff\xfe</test>"

        result = utils_module.parse_metadata_xml(xml_data)
        assert result is not None


class TestParseSessionMetadata:
    """Test session metadata parsing functionality."""

    def test_parse_session_metadata_complete(self, utils_module):
        raw_metadata = {
            "stream_name": "recv_rtp_src_0_123456_96",
            "caps": "application/x-rtp,media=(string)video,payload=(int)96,clock-rate=(int)90000",
            "structure": "application/x-rtp,media=(string)video,payload=(int)96,clock-rate=(int)90000",
            "sdes": {"cname": "test@host"},
        }

        result = utils_module.parse_session_metadata(raw_metadata)

        assert result["stream_name"] == raw_metadata["stream_name"]
        assert result["caps"] == raw_metadata["caps"]
        assert result["structure"] == raw_metadata["structure"]
        assert result["sdes"] == raw_metadata["sdes"]

    def test_parse_session_metadata_missing_fields(self, utils_module):
        raw_metadata = {
            "caps": "application/x-rtp,media=(string)video",
        }

        result = utils_module.parse_session_metadata(raw_metadata)

        assert result["stream_name"] is None
        assert result["caps"] == raw_metadata["caps"]


class TestCapsStringParsing:
    """Test low-level caps string parsing."""

    def test_parse_caps_string_basic(self, utils_module):
        caps = "media=(string)video,payload=(int)96,clock-rate=(int)90000"
        result = utils_module._parse_caps_string(caps)
        assert result["media"] == "video"
        assert result["payload"] == 96
        assert result["clock-rate"] == 90000


class TestLoggingConfiguration:
    """Test logging configuration helper."""

    def test_configure_logging(self, utils_module):
        logger = utils_module.configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG
        assert any(isinstance(h, logging.StreamHandler) for h in logging.getLogger().handlers)
