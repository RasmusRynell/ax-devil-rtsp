"""
Setup workarounds for known issues in GStreamer/Linux environments.

This module provides utilities to detect and apply workarounds for compatibility 
issues. Workarounds are applied through the standard dependency checking system
in utils/deps.py, ensuring they happen before any problematic imports.

The workarounds are applied conservatively - they only activate when:
1. The specific vulnerability is detected
2. The workaround hasn't already been applied
3. The fix is known to be safe for the detected environment

Usage:
    # Recommended: Use through standard dependency system
    from ax_devil_rtsp.utils.deps import ensure_gi_ready
    ensure_gi_ready()  # Automatically applies workarounds before GI import
    
    # Manual control (for testing/diagnostics)
    from ax_devil_rtsp.setup_workarounds import ensure_safe_environment
    ensure_safe_environment()
    
    # Status checking
    from ax_devil_rtsp.setup_workarounds import get_workaround_status
    status = get_workaround_status()
"""

from __future__ import annotations

from .libproxy_segfault import ensure_safe_environment
from ..utils.logging import get_logger

logger = get_logger("setup_workarounds")

# List of all available workarounds for reporting
AVAILABLE_WORKAROUNDS = [
    'libproxy_segfault'
]


def get_workaround_status() -> dict[str, dict]:
    """
    Get the status of all workarounds.
    
    Returns:
        Dictionary with detailed status for each workaround
    """
    from .libproxy_segfault import LibproxyWorkaround
    
    status = {}
    
    # Get libproxy status
    try:
        workaround = LibproxyWorkaround()
        status['libproxy_segfault'] = workaround.get_status_report()
    except Exception as e:
        status['libproxy_segfault'] = {
            'error': str(e),
            'vulnerable': None,
            'workaround_applied': False
        }
    
    return status


# Make key functions available at module level
__all__ = [
    'ensure_safe_environment',
    'get_workaround_status',
    'AVAILABLE_WORKAROUNDS'
]
