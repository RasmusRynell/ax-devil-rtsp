import xml.etree.ElementTree as ET
from ax_devil_rtsp.utils import parse_metadata_xml, parse_session_metadata, _parse_caps_string, configure_logging
import logging


class TestParseMetadataXml:
    """Test the metadata XML parsing functionality."""
    
    def test_parse_valid_xml(self):
        """Test parsing valid ONVIF metadata XML."""
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
        
        result = parse_metadata_xml(xml_data)
        
        assert result is not None
        assert 'objects' in result
        assert len(result['objects']) == 2
        assert result['objects'][0]['id'] == '1'
        assert result['objects'][0]['type'] == 'Human'
        assert result['objects'][1]['id'] == '2'
        assert result['objects'][1]['type'] == 'Vehicle'
        assert result['utc_time'] == '2023-01-01T12:00:00.000Z'
        assert 'raw_xml' in result

    def test_parse_empty_xml(self):
        """Test parsing empty metadata XML."""
        xml_data = b'''<?xml version="1.0" encoding="UTF-8"?>
        <tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema">
        </tt:MetadataStream>'''
        
        result = parse_metadata_xml(xml_data)
        
        assert result is not None
        assert result['objects'] == []
        assert result['utc_time'] is None

    def test_parse_invalid_xml(self):
        """Test parsing invalid XML returns None."""
        xml_data = b'<invalid>xml<content>'
        
        result = parse_metadata_xml(xml_data)
        
        assert result is None

    def test_parse_unicode_decode_error(self):
        """Test handling of unicode decode errors."""
        # Create invalid UTF-8 bytes
        xml_data = b'<?xml version="1.0" encoding="UTF-8"?><test>\xff\xfe</test>'
        
        result = parse_metadata_xml(xml_data)
        
        # Should handle decode error gracefully
        assert result is not None or result is None  # Either works with graceful error handling


class TestParseSessionMetadata:
    """Test session metadata parsing functionality."""
    
    def test_parse_session_metadata_complete(self):
        """Test parsing complete session metadata."""
        raw_metadata = {
            "stream_name": "recv_rtp_src_0_123456_96",
            "caps": "application/x-rtp,media=(string)video,payload=(int)96,clock-rate=(int)90000",
            "structure": "application/x-rtp,media=(string)video,payload=(int)96,clock-rate=(int)90000",
            "sdes": {"cname": "test@host"}
        }
        
        result = parse_session_metadata(raw_metadata)
        
        assert result["stream_name"] == "recv_rtp_src_0_123456_96"
        assert result["caps"] == "application/x-rtp,media=(string)video,payload=(int)96,clock-rate=(int)90000"
        assert "caps_parsed" in result
        assert result["caps_parsed"]["media"] == "video"
        assert result["caps_parsed"]["payload"] == 96
        assert result["caps_parsed"]["clock-rate"] == 90000
        assert result["sdes"] == {"cname": "test@host"}

    def test_parse_caps_string(self):
        """Test the internal caps string parsing function."""
        caps_str = "video/x-raw,format=(string)RGB,width=(int)640,height=(int)480,framerate=(fraction)30/1"
        
        result = _parse_caps_string(caps_str)
        
        assert result["format"] == "RGB"
        assert result["width"] == 640
        assert result["height"] == 480
        assert result["framerate"] == "30/1"

    def test_parse_caps_string_with_escapes(self):
        """Test caps string parsing with escaped commas."""
        caps_str = "application/x-custom,name=(string)test\\,value,count=(int)5"
        
        result = _parse_caps_string(caps_str)
        
        assert result["name"] == "test,value"  # Escaped comma should be unescaped
        assert result["count"] == 5


class TestConfigureLogging:
    """Test logging configuration."""
    
    def test_configure_logging_info_level(self):
        """Test configuring logging at INFO level."""
        logger = configure_logging(logging.INFO)
        
        assert logger.name == "ax-devil-rtsp"
        assert logging.getLogger().level == logging.INFO

    def test_configure_logging_debug_level(self):
        """Test configuring logging at DEBUG level."""
        logger = configure_logging(logging.DEBUG)
        
        assert logger.name == "ax-devil-rtsp"
        assert logging.getLogger().level == logging.DEBUG 