"""
Unit tests for libproxy segmentation fault workaround.

Tests the detection, application, and validation of the libproxy workaround
using mocked system conditions.
"""

import os
import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from ax_devil_rtsp.setup_workarounds.libproxy_segfault import (
    LibproxySegfaultDetector,
    LibproxyWorkaround,
    VulnerabilityDetails,
    ensure_safe_environment
)


class TestLibproxySegfaultDetector:
    """Test the vulnerability detection logic."""
    
    def test_not_vulnerable_on_non_linux(self):
        """Test that non-Linux systems are not vulnerable."""
        detector = LibproxySegfaultDetector()
        
        with patch('platform.system', return_value='Windows'):
            details = detector.get_vulnerability_details()
            
        assert not details.is_vulnerable
        assert details.os_info == 'Windows'
        assert 'Not Linux - not vulnerable' in details.reasons
    
    def test_not_vulnerable_when_workaround_already_applied(self):
        """Test that systems with workaround applied are not vulnerable."""
        detector = LibproxySegfaultDetector()
        
        with patch.dict(os.environ, {'GIO_MODULE_DIR': '/dev/null'}):
            with patch('platform.system', return_value='Linux'):
                with patch.object(detector, '_get_os_info', return_value='Ubuntu 22.04'):
                    with patch.object(detector, '_get_gstreamer_version', return_value='1.20.3'):
                        with patch.object(detector, '_has_libproxy_module', return_value=True):
                            details = detector.get_vulnerability_details()
        
        assert not details.is_vulnerable
        assert details.workaround_applied
    
    @patch('platform.system', return_value='Linux')
    def test_vulnerable_ubuntu_22_old_gstreamer_with_module(self, mock_platform):
        """Test detection of vulnerable system: Ubuntu 22.04 + old GStreamer + libproxy module."""
        detector = LibproxySegfaultDetector()
        
        with patch.dict(os.environ, {}, clear=True):  # Clear GIO_MODULE_DIR
            with patch.object(detector, '_get_os_info', return_value='Ubuntu 22.04.3 LTS'):
                with patch.object(detector, '_get_gstreamer_version', return_value='1.20.3'):
                    with patch.object(detector, '_has_libproxy_module', return_value=True):
                        details = detector.get_vulnerability_details()
        
        assert details.is_vulnerable
        assert 'Ubuntu 22.04 detected' in details.reasons
        assert 'GStreamer 1.20.3 < 1.22' in details.reasons
        assert 'libgiolibproxy.so module present' in details.reasons
    
    @patch('platform.system', return_value='Linux')
    def test_not_vulnerable_ubuntu_24_new_gstreamer(self, mock_platform):
        """Test that Ubuntu 24.04 with new GStreamer is not vulnerable."""
        detector = LibproxySegfaultDetector()
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(detector, '_get_os_info', return_value='Ubuntu 24.04.1 LTS'):
                with patch.object(detector, '_get_gstreamer_version', return_value='1.24.2'):
                    with patch.object(detector, '_has_libproxy_module', return_value=True):
                        details = detector.get_vulnerability_details()
        
        assert not details.is_vulnerable
    
    @patch('platform.system', return_value='Linux')
    def test_not_vulnerable_without_libproxy_module(self, mock_platform):
        """Test that systems without libproxy module are not vulnerable."""
        detector = LibproxySegfaultDetector()
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(detector, '_get_os_info', return_value='Ubuntu 22.04.3 LTS'):
                with patch.object(detector, '_get_gstreamer_version', return_value='1.20.3'):
                    with patch.object(detector, '_has_libproxy_module', return_value=False):
                        details = detector.get_vulnerability_details()
        
        assert not details.is_vulnerable
    
    def test_is_ubuntu_22_detection(self):
        """Test Ubuntu 22.04 version detection."""
        detector = LibproxySegfaultDetector()
        
        test_cases = [
            ('Ubuntu 22.04.3 LTS', True),
            ('Ubuntu 22.04 LTS', True),
            ('Ubuntu 20.04.6 LTS', False),
            ('Ubuntu 24.04.1 LTS', False),
            ('Fedora 38', False),
            ('Arch Linux', False),
        ]
        
        for os_info, expected in test_cases:
            assert detector._is_ubuntu_22(os_info) == expected
    
    def test_gstreamer_version_parsing(self):
        """Test GStreamer version vulnerability detection."""
        detector = LibproxySegfaultDetector()
        
        test_cases = [
            ('1.20.3', True),    # Vulnerable
            ('1.21.9', True),    # Vulnerable
            ('1.22.0', False),   # Not vulnerable
            ('1.24.2', False),   # Not vulnerable
            ('2.0.0', False),    # Not vulnerable
            (None, False),       # Unknown version
            ('invalid', False),  # Invalid version
        ]
        
        for version, expected in test_cases:
            assert detector._is_vulnerable_gstreamer(version) == expected
    
    @patch('subprocess.run')
    def test_gstreamer_version_detection_success(self, mock_run):
        """Test successful GStreamer version detection."""
        detector = LibproxySegfaultDetector()
        
        # Mock successful subprocess call
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = '1.20.3\n'
        mock_run.return_value = mock_result
        
        version = detector._get_gstreamer_version()
        assert version == '1.20.3'
    
    @patch('subprocess.run')
    def test_gstreamer_version_detection_failure(self, mock_run):
        """Test failed GStreamer version detection."""
        detector = LibproxySegfaultDetector()
        
        # Mock failed subprocess call
        mock_result = Mock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        
        version = detector._get_gstreamer_version()
        assert version is None
    
    @patch('subprocess.run')
    def test_gstreamer_version_detection_timeout(self, mock_run):
        """Test timeout during GStreamer version detection."""
        detector = LibproxySegfaultDetector()
        
        # Mock timeout exception
        mock_run.side_effect = subprocess.TimeoutExpired('cmd', 10)
        
        version = detector._get_gstreamer_version()
        assert version is None
    
    @patch('builtins.open')
    def test_os_info_detection_success(self, mock_open):
        """Test successful OS info detection."""
        detector = LibproxySegfaultDetector()
        
        mock_open.return_value.__enter__.return_value.read.return_value = 'Ubuntu 22.04.3 LTS'
        
        os_info = detector._get_os_info()
        assert os_info == 'Ubuntu 22.04.3 LTS'
    
    @patch('builtins.open')
    def test_os_info_detection_failure(self, mock_open):
        """Test failed OS info detection."""
        detector = LibproxySegfaultDetector()
        
        mock_open.side_effect = FileNotFoundError()
        
        os_info = detector._get_os_info()
        assert os_info == 'Unknown Linux'
    
    @patch('pathlib.Path.exists')
    def test_libproxy_module_detection(self, mock_exists):
        """Test libproxy module presence detection."""
        detector = LibproxySegfaultDetector()
        
        # Test module present
        mock_exists.return_value = True
        assert detector._has_libproxy_module() is True
        
        # Test module absent
        mock_exists.return_value = False
        assert detector._has_libproxy_module() is False
    
    def test_caching_behavior(self):
        """Test that vulnerability details are cached."""
        detector = LibproxySegfaultDetector()
        
        with patch.object(detector, '_assess_vulnerability') as mock_assess:
            mock_details = VulnerabilityDetails(
                is_vulnerable=False,
                os_info='Test',
                gstreamer_version=None,
                has_libproxy_module=False,
                workaround_applied=False,
                reasons=['Test']
            )
            mock_assess.return_value = mock_details
            
            # First call should trigger assessment
            details1 = detector.get_vulnerability_details()
            
            # Second call should use cache
            details2 = detector.get_vulnerability_details()
            
            assert details1 is details2
            mock_assess.assert_called_once()


class TestLibproxyWorkaround:
    """Test the workaround application and validation."""
    
    def test_is_applied_true(self):
        """Test detection when workaround is applied."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {'GIO_MODULE_DIR': '/dev/null'}):
            assert workaround.is_applied() is True
    
    def test_is_applied_false(self):
        """Test detection when workaround is not applied."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {}, clear=True):
            assert workaround.is_applied() is False
    
    def test_apply_when_already_applied(self):
        """Test apply when workaround is already applied."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {'GIO_MODULE_DIR': '/dev/null'}):
            result = workaround.apply()
            
        assert result is True
    
    def test_apply_when_not_vulnerable(self):
        """Test apply when system is not vulnerable."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(workaround.detector, 'is_vulnerable', return_value=False):
                result = workaround.apply()
        
        assert result is False
        assert os.environ.get('GIO_MODULE_DIR') != '/dev/null'
    
    def test_apply_when_vulnerable(self):
        """Test apply when system is vulnerable."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(workaround.detector, 'is_vulnerable', return_value=True):
                result = workaround.apply()
                
                # Check that the environment was modified
                assert result is True
                assert os.environ.get('GIO_MODULE_DIR') == '/dev/null'
    
    def test_apply_force(self):
        """Test force apply regardless of vulnerability."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(workaround.detector, 'is_vulnerable', return_value=False):
                result = workaround.apply(force=True)
                
                assert result is True
                assert os.environ.get('GIO_MODULE_DIR') == '/dev/null'
    
    @patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.logger')
    @patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.os.environ')
    def test_apply_exception_handling(self, mock_environ, mock_logger):
        """Test exception handling during apply."""
        workaround = LibproxyWorkaround()
        
        # Mock environ.get to return nothing (workaround not applied)
        mock_environ.get.return_value = None
        # Mock __setitem__ to raise an exception
        mock_environ.__setitem__.side_effect = Exception('Test error')
        
        with patch.object(workaround.detector, 'is_vulnerable', return_value=True):
            result = workaround.apply()
        
        assert result is False
        mock_logger.error.assert_called_once()
    
    def test_validate_not_applied(self):
        """Test validation when workaround is not applied."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {}, clear=True):
            result = workaround.validate()
            
        assert result is False
    
    def test_validate_success(self):
        """Test successful validation."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {'GIO_MODULE_DIR': '/dev/null'}):
            # Mock the imports inside the validate method
            with patch('builtins.__import__') as mock_import:
                # Mock gi module
                mock_gi = MagicMock()
                mock_gst = MagicMock()
                mock_gst.is_initialized.return_value = True
                
                def import_side_effect(name, *args, **kwargs):
                    if name == 'gi':
                        return mock_gi
                    return MagicMock()
                    
                mock_import.side_effect = import_side_effect
                
                # Mock the gi.repository import
                with patch.dict('sys.modules', {'gi.repository': MagicMock(Gst=mock_gst)}):
                    result = workaround.validate()
        
        assert result is True
    
    def test_validate_failure(self):
        """Test validation failure."""
        workaround = LibproxyWorkaround()
        
        with patch.dict(os.environ, {'GIO_MODULE_DIR': '/dev/null'}):
            with patch('builtins.__import__', side_effect=ImportError('Mock import error')):
                result = workaround.validate()
        
        assert result is False
    
    def test_get_status_report(self):
        """Test status report generation."""
        workaround = LibproxyWorkaround()
        
        mock_details = VulnerabilityDetails(
            is_vulnerable=True,
            os_info='Ubuntu 22.04',
            gstreamer_version='1.20.3',
            has_libproxy_module=True,
            workaround_applied=False,
            reasons=['Test reason']
        )
        
        with patch.object(workaround.detector, 'get_vulnerability_details', return_value=mock_details):
            with patch.object(workaround, 'is_applied', return_value=True):
                with patch.object(workaround, 'validate', return_value=True):
                    report = workaround.get_status_report()
        
        expected_keys = {
            'vulnerable', 'workaround_applied', 'os_info', 
            'gstreamer_version', 'has_libproxy_module', 
            'reasons', 'validation_passed'
        }
        assert set(report.keys()) == expected_keys
        assert report['vulnerable'] is True
        assert report['workaround_applied'] is True
        assert report['validation_passed'] is True


class TestEnsureSafeEnvironment:
    """Test the main entry point function."""
    
    def test_not_vulnerable_system(self):
        """Test ensure_safe_environment on non-vulnerable system."""
        with patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.LibproxySegfaultDetector') as mock_detector_class:
            mock_detector = mock_detector_class.return_value
            mock_detector.is_vulnerable.return_value = False
            
            result = ensure_safe_environment()
            
        assert result is True
    
    def test_vulnerable_system_workaround_success(self):
        """Test ensure_safe_environment on vulnerable system with successful workaround."""
        with patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.LibproxySegfaultDetector') as mock_detector_class:
            with patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.LibproxyWorkaround') as mock_workaround_class:
                
                mock_detector = mock_detector_class.return_value
                mock_detector.is_vulnerable.return_value = True
                mock_detector.get_vulnerability_details.return_value = VulnerabilityDetails(
                    is_vulnerable=True,
                    os_info='Ubuntu 22.04',
                    gstreamer_version='1.20.3',
                    has_libproxy_module=True,
                    workaround_applied=False,
                    reasons=['Test reason']
                )
                
                mock_workaround = mock_workaround_class.return_value
                mock_workaround.apply.return_value = True
                
                result = ensure_safe_environment()
                
        assert result is True
    
    def test_vulnerable_system_workaround_failure(self):
        """Test ensure_safe_environment on vulnerable system with failed workaround."""
        with patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.LibproxySegfaultDetector') as mock_detector_class:
            with patch('ax_devil_rtsp.setup_workarounds.libproxy_segfault.LibproxyWorkaround') as mock_workaround_class:
                
                mock_detector = mock_detector_class.return_value
                mock_detector.is_vulnerable.return_value = True
                mock_detector.get_vulnerability_details.return_value = VulnerabilityDetails(
                    is_vulnerable=True,
                    os_info='Ubuntu 22.04',
                    gstreamer_version='1.20.3',
                    has_libproxy_module=True,
                    workaround_applied=False,
                    reasons=['Test reason']
                )
                
                mock_workaround = mock_workaround_class.return_value
                mock_workaround.apply.return_value = False
                
                result = ensure_safe_environment()
                
        assert result is False


@pytest.mark.parametrize("os_name,gst_version,has_module,expected", [
    ("Windows", None, False, False),          # Not Linux
    ("Linux", "1.24.2", True, False),        # New GStreamer
    ("Linux", "1.20.3", False, False),       # No module
    ("Linux", "1.20.3", True, True),         # Vulnerable
])
def test_vulnerability_combinations(os_name, gst_version, has_module, expected):
    """Test various combinations of system conditions."""
    detector = LibproxySegfaultDetector()
    
    with patch.dict(os.environ, {}, clear=True):  # No workaround applied
        with patch('platform.system', return_value=os_name):
            with patch.object(detector, '_get_os_info', return_value='Ubuntu 22.04.3 LTS'):
                with patch.object(detector, '_get_gstreamer_version', return_value=gst_version):
                    with patch.object(detector, '_has_libproxy_module', return_value=has_module):
                        result = detector.is_vulnerable()
    
    assert result == expected