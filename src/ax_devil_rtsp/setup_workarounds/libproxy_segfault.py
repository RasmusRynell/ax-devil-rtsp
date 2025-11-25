"""
GStreamer RTSP libproxy Segmentation Fault Workaround

This module provides detection and workaround for a critical segmentation fault
that occurs when using GStreamer's RTSP source element (rtspsrc) on certain
Linux distributions with older libproxy versions.

## Executive Summary

A segmentation fault occurs when using GStreamer's RTSP source element (rtspsrc)
on Ubuntu 22.04 with GStreamer 1.20.3 due to a bug in the libproxy library
when it's invoked through GIO's proxy resolver module. The crash happens during
RTSP connection establishment when GIO attempts to determine proxy settings.

## Problem Description

### Symptoms
- Immediate crash: Application crashes with segmentation fault (SIGABRT) when
  rtspsrc attempts to connect
- Timing: Occurs right after "connecting..." message in GStreamer debug output
- Error signature: Core dump shows crash in px_proxy_factory_get_proxies()
  within libproxy.so.1

### Affected Configuration
- OS: Ubuntu 22.04 LTS
- GStreamer: 1.20.3
- libproxy: 0.4.17-2
- GIO: 2.72.x (Ubuntu 22.04 default)
- Python: 3.10
- PyGObject: 3.42.x

## Stack Trace Analysis

The typical crash signature:
```
#10 px_proxy_factory_get_proxies () at libproxy.so.1
#11 libgiolibproxy.so (GIO module)
#12 libgio-2.0.so.0 (GIO library)
...
#5  abort() 
#6-7 C++ exception handling (__gxx_personality_v0)
#8  libunwind trying to unwind the stack
#9-10 libproxy crash during proxy detection
```

## Root Cause Analysis

### The Chain of Events

1. **RTSP Connection Initiation**
   - rtspsrc element → needs to establish TCP/UDP connection

2. **GIO Network Layer**
   - GStreamer → uses GIO for network operations
   - GIO → checks for proxy configuration

3. **Proxy Resolution**
   - GIO → loads proxy resolver modules from /usr/lib/x86_64-linux-gnu/gio/modules/
   - GIO → finds and loads libgiolibproxy.so
   - libgiolibproxy.so → calls libproxy's px_proxy_factory_get_proxies()

4. **libproxy Crash**
   - libproxy → attempts to detect system proxy settings
   - libproxy → throws uncaught C++ exception
   - Exception → propagates through C boundary (undefined behavior)
   - Result → SIGABRT (abort signal)

### Why It Happens

The core issue is a bug in libproxy 0.4.17 where it throws a C++ exception
that crosses the C library boundary. This is undefined behavior in C++ and
causes the program to abort.

Specific triggers:
- libproxy tries to access D-Bus or other system services for proxy detection
- These services might not be available or properly configured
- Instead of handling the error gracefully, libproxy throws an exception
- The exception cannot be caught because it crosses from C++ (libproxy) to C (GIO)

### Why It Works on Ubuntu 24.04 / GStreamer 1.24.2

Newer versions have fixes:
- libproxy 0.4.18+: Fixed exception handling
- GStreamer 1.22+: Better error handling in network code
- GIO 2.74+: Improved module loading with better isolation

## Solution

The workaround involves setting `GIO_MODULE_DIR=/dev/null` to prevent GIO
from loading the problematic libproxy module. This is safe and effective
with no significant side effects for applications that don't require system
proxy settings.

## Usage

```python
from ax_devil_rtsp.setup_workarounds.libproxy_segfault import ensure_safe_environment

# Apply workaround automatically if needed
ensure_safe_environment()

# Then proceed with GStreamer operations
```

Or check manually:

```python
from ax_devil_rtsp.setup_workarounds.libproxy_segfault import (
    LibproxySegfaultDetector,
    LibproxyWorkaround
)

detector = LibproxySegfaultDetector()
if detector.is_vulnerable():
    print("System is vulnerable")
    workaround = LibproxyWorkaround()
    workaround.apply()
```
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class VulnerabilityDetails:
    """Details about the libproxy vulnerability detection."""
    
    is_vulnerable: bool
    os_info: str
    gstreamer_version: Optional[str]
    has_libproxy_module: bool
    workaround_applied: bool
    reasons: List[str]


class LibproxySegfaultDetector:
    """Detects if the system is vulnerable to the libproxy segmentation fault."""
    
    def __init__(self) -> None:
        self._cached_result: Optional[VulnerabilityDetails] = None
    
    def is_vulnerable(self) -> bool:
        """Check if system is vulnerable to the libproxy segfault."""
        return self.get_vulnerability_details().is_vulnerable
    
    def get_vulnerability_details(self) -> VulnerabilityDetails:
        """Get detailed vulnerability assessment."""
        if self._cached_result is None:
            self._cached_result = self._assess_vulnerability()
        return self._cached_result
    
    def _assess_vulnerability(self) -> VulnerabilityDetails:
        """Perform the actual vulnerability assessment."""
        reasons = []
        
        # Check if workaround is already applied
        workaround_applied = os.environ.get('GIO_MODULE_DIR') == '/dev/null'
        if workaround_applied:
            logger.debug("Workaround already applied (GIO_MODULE_DIR=/dev/null)")
        
        # Check OS platform
        if platform.system() != 'Linux':
            return VulnerabilityDetails(
                is_vulnerable=False,
                os_info=platform.system(),
                gstreamer_version=None,
                has_libproxy_module=False,
                workaround_applied=workaround_applied,
                reasons=["Not Linux - not vulnerable"]
            )
        
        # Get OS info
        os_info = self._get_os_info()
        
        # Check Ubuntu version
        is_ubuntu_22 = self._is_ubuntu_22(os_info)
        if is_ubuntu_22:
            reasons.append("Ubuntu 22.04 detected")
        
        # Check GStreamer version
        gstreamer_version = self._get_gstreamer_version()
        is_old_gstreamer = self._is_vulnerable_gstreamer(gstreamer_version)
        if is_old_gstreamer and gstreamer_version:
            reasons.append(f"GStreamer {gstreamer_version} < 1.22")
        
        # Check for problematic module
        has_libproxy_module = self._has_libproxy_module()
        if has_libproxy_module:
            reasons.append("libgiolibproxy.so module present")
        
        # Determine vulnerability
        is_vulnerable = (
            is_ubuntu_22 and 
            is_old_gstreamer and 
            has_libproxy_module and 
            not workaround_applied
        )
        
        if not is_vulnerable and not reasons:
            reasons.append("System not vulnerable")
        
        return VulnerabilityDetails(
            is_vulnerable=is_vulnerable,
            os_info=os_info,
            gstreamer_version=gstreamer_version,
            has_libproxy_module=has_libproxy_module,
            workaround_applied=workaround_applied,
            reasons=reasons
        )
    
    def _get_os_info(self) -> str:
        """Get OS release information."""
        try:
            with open('/etc/os-release') as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.debug("/etc/os-release not found, trying alternatives")
            # Try alternatives for different Linux distributions
            for alt_path in ['/etc/lsb-release', '/etc/redhat-release', '/etc/debian_version']:
                try:
                    with open(alt_path) as f:
                        content = f.read().strip()
                        logger.debug(f"Found OS info in {alt_path}: {content}")
                        return content
                except (FileNotFoundError, PermissionError):
                    continue
            return "Unknown Linux"
        except PermissionError:
            logger.debug("Permission denied reading /etc/os-release")
            return "Unknown Linux"
        except Exception as e:
            logger.debug(f"Unexpected error reading OS info: {e}")
            return "Unknown Linux"
    
    def _is_ubuntu_22(self, os_info: str) -> bool:
        """Check if this is Ubuntu 22.04."""
        return 'Ubuntu 22.04' in os_info
    
    def _get_gstreamer_version(self) -> Optional[str]:
        """Get GStreamer version string."""
        try:
            # Try to get version from GStreamer itself
            result = subprocess.run([
                sys.executable, '-c',
                'import gi; gi.require_version("Gst", "1.0"); '
                'from gi.repository import Gst; Gst.init(None); '
                'v = Gst.version(); print(f"{v[0]}.{v[1]}.{v[2]}")'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.debug(f"GStreamer version detection failed with exit code {result.returncode}")
                if result.stderr:
                    logger.debug(f"stderr: {result.stderr.strip()}")
                
        except subprocess.TimeoutExpired:
            logger.debug("GStreamer version detection timed out after 10 seconds")
        except subprocess.CalledProcessError as e:
            logger.debug(f"GStreamer version detection subprocess error: {e}")
        except FileNotFoundError:
            logger.debug(f"Python executable not found: {sys.executable}")
        except Exception as e:
            logger.debug(f"Unexpected error during GStreamer version detection: {e}")
        
        return None
    
    def _is_vulnerable_gstreamer(self, version: Optional[str]) -> bool:
        """Check if GStreamer version is vulnerable."""
        if not version:
            return False
        
        try:
            major, minor, _ = map(int, version.split('.'))
            return major == 1 and minor < 22
        except Exception:
            return False
    
    def _has_libproxy_module(self) -> bool:
        """Check if the problematic GIO libproxy module exists."""
        # Common paths for GIO modules on different architectures
        possible_paths = [
            '/usr/lib/x86_64-linux-gnu/gio/modules/libgiolibproxy.so',  # Ubuntu x86_64
            '/usr/lib/aarch64-linux-gnu/gio/modules/libgiolibproxy.so',  # Ubuntu ARM64
            '/usr/lib/arm-linux-gnueabihf/gio/modules/libgiolibproxy.so',  # Ubuntu ARM32
            '/usr/lib64/gio/modules/libgiolibproxy.so',  # Fedora/RHEL x86_64
            '/usr/lib/gio/modules/libgiolibproxy.so',    # Generic path
        ]
        
        for path_str in possible_paths:
            if Path(path_str).exists():
                logger.debug(f"Found libproxy module at: {path_str}")
                return True
        
        logger.debug("No libproxy module found in common locations")
        return False


class LibproxyWorkaround:
    """Applies and manages the libproxy segfault workaround."""
    
    def __init__(self) -> None:
        self.detector = LibproxySegfaultDetector()
    
    def is_applied(self) -> bool:
        """Check if the workaround is currently applied."""
        return os.environ.get('GIO_MODULE_DIR') == '/dev/null'
    
    def apply(self, force: bool = False) -> bool:
        """
        Apply the libproxy workaround.
        
        Args:
            force: Apply even if not detected as vulnerable
            
        Returns:
            True if workaround was applied successfully
        """
        if self.is_applied():
            logger.debug("Workaround already applied")
            return True
        
        if not force and not self.detector.is_vulnerable():
            logger.debug("System not vulnerable, skipping workaround")
            return False
        
        try:
            # Set the environment variable to disable GIO proxy modules
            os.environ['GIO_MODULE_DIR'] = '/dev/null'
            
            logger.info("Applied libproxy segfault workaround (GIO_MODULE_DIR=/dev/null)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply libproxy workaround: {e}")
            return False
    
    def validate(self) -> bool:
        """
        Validate that the workaround is working.
        
        Returns:
            True if the workaround appears to be working
        """
        if not self.is_applied():
            return False
        
        # If we can import gi and initialize Gst without crashing, it's working
        try:
            import gi  # type: ignore
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore
            
            if not Gst.is_initialized():
                Gst.init(None)
            
            return True
        except Exception as e:
            logger.error(f"Workaround validation failed: {e}")
            return False
    
    def get_status_report(self) -> Dict[str, Any]:
        """Get a detailed status report of the workaround."""
        details = self.detector.get_vulnerability_details()
        
        return {
            'vulnerable': details.is_vulnerable,
            'workaround_applied': self.is_applied(),
            'os_info': details.os_info,
            'gstreamer_version': details.gstreamer_version,
            'has_libproxy_module': details.has_libproxy_module,
            'reasons': details.reasons,
            'validation_passed': self.validate() if self.is_applied() else None
        }


def ensure_safe_environment() -> bool:
    """
    Ensure the environment is safe from libproxy segfaults.
    
    This function should be called before any GStreamer operations.
    
    Environment Variables:
        AX_DEVIL_DISABLE_WORKAROUNDS: Set to '1' or 'true' to disable all workarounds
        AX_DEVIL_FORCE_LIBPROXY_WORKAROUND: Set to '1' or 'true' to force apply workaround
    
    Returns:
        True if environment is safe (either not vulnerable or workaround applied)
    """
    # Check if workarounds are disabled globally
    if os.environ.get('AX_DEVIL_DISABLE_WORKAROUNDS', '').lower() in ('1', 'true', 'yes'):
        logger.info("Workarounds disabled via AX_DEVIL_DISABLE_WORKAROUNDS")
        return True
    
    # Check if this specific workaround should be forced
    force_workaround = os.environ.get('AX_DEVIL_FORCE_LIBPROXY_WORKAROUND', '').lower() in ('1', 'true', 'yes')
    
    detector = LibproxySegfaultDetector()
    
    if not force_workaround and not detector.is_vulnerable():
        logger.debug("System not vulnerable to libproxy segfault")
        return True
    
    workaround = LibproxyWorkaround()
    
    if force_workaround:
        logger.info("Forcing libproxy workaround via AX_DEVIL_FORCE_LIBPROXY_WORKAROUND")
        if workaround.apply(force=True):
            logger.info("Successfully forced libproxy segfault workaround")
            return True
        else:
            logger.error("Failed to force libproxy segfault workaround")
            return False
    
    details = detector.get_vulnerability_details()
    logger.warning(
        f"System vulnerable to libproxy segfault: {', '.join(details.reasons)}"
    )
    
    if workaround.apply():
        logger.info("Successfully applied libproxy segfault workaround")
        return True
    else:
        logger.error("Failed to apply libproxy segfault workaround")
        return False


def get_detection_script() -> str:
    """
    Get a standalone script for detecting the vulnerability.
    
    Returns:
        Python script as string that can be executed independently
    """
    return '''#!/usr/bin/env python3
"""
Standalone libproxy vulnerability detection script.
"""

import os
import sys
import platform
import subprocess

def check_vulnerability():
    """Check if system is vulnerable to the libproxy segfault."""
    
    vulnerabilities = []
    
    # Check OS
    if platform.system() != 'Linux':
        print("✓ Not Linux - not vulnerable")
        return False
    
    # Check Ubuntu version
    try:
        with open('/etc/os-release') as f:
            os_info = f.read()
            if 'Ubuntu 22.04' in os_info:
                vulnerabilities.append("Ubuntu 22.04 detected")
    except:
        pass
    
    # Check GStreamer version
    try:
        result = subprocess.run([
            'python3', '-c', 
            'import gi; gi.require_version("Gst", "1.0"); '
            'from gi.repository import Gst; Gst.init(None); '
            'v = Gst.version(); print(f"{v[0]}.{v[1]}.{v[2]}")'
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip()
            major, minor, _ = map(int, version.split('.'))
            if major == 1 and minor < 22:
                vulnerabilities.append(f"GStreamer {version} < 1.22")
    except:
        pass
    
    # Check for problematic module
    possible_paths = [
        '/usr/lib/x86_64-linux-gnu/gio/modules/libgiolibproxy.so',
        '/usr/lib/aarch64-linux-gnu/gio/modules/libgiolibproxy.so',
        '/usr/lib/arm-linux-gnueabihf/gio/modules/libgiolibproxy.so',
        '/usr/lib64/gio/modules/libgiolibproxy.so',
        '/usr/lib/gio/modules/libgiolibproxy.so',
    ]
    
    for module_path in possible_paths:
        if os.path.exists(module_path):
            vulnerabilities.append("libgiolibproxy.so module present")
            break
    
    # Check if workaround is applied
    if os.environ.get('GIO_MODULE_DIR') == '/dev/null':
        print("✓ Workaround already applied (GIO_MODULE_DIR=/dev/null)")
        return False
    
    if vulnerabilities:
        print("⚠ VULNERABLE TO LIBPROXY SEGFAULT")
        print("Detected issues:")
        for issue in vulnerabilities:
            print(f"  - {issue}")
        print("\\nRecommended fix:")
        print("  export GIO_MODULE_DIR=/dev/null")
        return True
    else:
        print("✓ System not vulnerable")
        return False

if __name__ == "__main__":
    is_vulnerable = check_vulnerability()
    sys.exit(1 if is_vulnerable else 0)
'''
