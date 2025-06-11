import pytest
from ax_devil_rtsp.examples.cli import build_rtsp_url, parse_args
from unittest.mock import patch
import sys


class TestCLIArgumentParsing:
    """Test CLI argument parsing functionality."""
    
    def test_parse_args_with_ip(self):
        """Test parsing arguments with IP address."""
        test_args = ['--ip', '192.168.1.100', '--username', 'admin', '--password', 'secret']
        
        with patch.object(sys, 'argv', ['cli.py'] + test_args):
            args = parse_args()
            
        assert args.ip == '192.168.1.100'
        assert args.username == 'admin'
        assert args.password == 'secret'
        assert args.latency == 100  # default
        assert args.source == '1'   # default

    def test_parse_args_with_rtsp_url(self):
        """Test parsing arguments with full RTSP URL."""
        test_args = ['--rtsp-url', 'rtsp://user:pass@192.168.1.50/test']
        
        with patch.object(sys, 'argv', ['cli.py'] + test_args):
            args = parse_args()
            
        assert args.rtsp_url == 'rtsp://user:pass@192.168.1.50/test'

    def test_parse_args_with_options(self):
        """Test parsing arguments with various options."""
        test_args = [
            '--ip', '192.168.1.100',
            '--latency', '200',
            '--no-video',
            '--no-metadata',
            '--log-level', 'DEBUG'
        ]
        
        with patch.object(sys, 'argv', ['cli.py'] + test_args):
            args = parse_args()
            
        assert args.latency == 200
        assert args.no_video is True
        assert args.no_metadata is True
        assert args.log_level == 'DEBUG'


class TestRTSPURLBuilding:
    """Test RTSP URL building functionality."""
    
    def test_build_rtsp_url_basic(self):
        """Test building basic RTSP URL."""
        class MockArgs:
            rtsp_url = None
            ip = '192.168.1.100'
            username = 'admin'
            password = 'secret'
            source = '1'
            no_video = False
            no_metadata = False
            rtp_ext = True
            
        args = MockArgs()
        url = build_rtsp_url(args)
        
        assert url.startswith('rtsp://admin:secret@192.168.1.100/axis-media/media.amp')
        assert 'onvifreplayext=1' in url
        assert 'analytics=polygon' in url
        assert 'camera=1' in url

    def test_build_rtsp_url_no_credentials(self):
        """Test building RTSP URL without credentials."""
        class MockArgs:
            rtsp_url = None
            ip = '192.168.1.100'
            username = ''
            password = ''
            source = '1'
            no_video = False
            no_metadata = False
            rtp_ext = True
            
        args = MockArgs()
        url = build_rtsp_url(args)
        
        assert url.startswith('rtsp://192.168.1.100/axis-media/media.amp')
        assert '@' not in url.split('/')[2]  # No credentials in host part

    def test_build_rtsp_url_video_only(self):
        """Test building RTSP URL for video only."""
        class MockArgs:
            rtsp_url = None
            ip = '192.168.1.100'
            username = 'admin'
            password = 'secret'
            source = '1'
            no_video = False
            no_metadata = True
            rtp_ext = True
            
        args = MockArgs()
        url = build_rtsp_url(args)
        
        assert 'analytics=polygon' not in url
        assert 'onvifreplayext=1' in url

    def test_build_rtsp_url_metadata_only(self):
        """Test building RTSP URL for metadata only."""
        class MockArgs:
            rtsp_url = None
            ip = '192.168.1.100'
            username = 'admin'
            password = 'secret'
            source = '1'
            no_video = True
            no_metadata = False
            rtp_ext = True
            
        args = MockArgs()
        url = build_rtsp_url(args)
        
        assert 'video=0' in url
        assert 'audio=0' in url
        assert 'analytics=polygon' in url

    def test_build_rtsp_url_with_provided_url(self):
        """Test that provided RTSP URL is used directly."""
        class MockArgs:
            rtsp_url = 'rtsp://test:test@192.168.1.50/custom/path'
            ip = '192.168.1.100'  # Should be ignored
            username = 'admin'    # Should be ignored
            password = 'secret'   # Should be ignored
            source = '1'
            no_video = False
            no_metadata = False
            rtp_ext = True
            
        args = MockArgs()
        url = build_rtsp_url(args)
        
        assert url == 'rtsp://test:test@192.168.1.50/custom/path'

    def test_build_rtsp_url_no_ip_raises_error(self):
        """Test that missing IP raises ValueError."""
        class MockArgs:
            rtsp_url = None
            ip = None
            username = 'admin'
            password = 'secret'
            source = '1'
            no_video = False
            no_metadata = False
            rtp_ext = True
            
        args = MockArgs()
        
        with pytest.raises(ValueError, match="No IP address provided"):
            build_rtsp_url(args)

    def test_build_rtsp_url_nothing_requested_raises_error(self):
        """Test that requesting neither video nor metadata raises error."""
        class MockArgs:
            rtsp_url = None
            ip = '192.168.1.100'
            username = 'admin'
            password = 'secret'
            source = '1'
            no_video = True
            no_metadata = True
            rtp_ext = True
            
        args = MockArgs()
        
        with pytest.raises(ValueError, match="You cannot ask for nothing"):
            build_rtsp_url(args) 