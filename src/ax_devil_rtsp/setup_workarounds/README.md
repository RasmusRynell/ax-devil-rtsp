# Setup Workarounds

This directory contains workarounds for known compatibility issues with GStreamer and related libraries on various Linux distributions.

## Overview

The workarounds in this module are designed to be:
- **Automatic**: Applied when the module is imported
- **Conservative**: Only applied when the specific issue is detected
- **Safe**: No side effects when applied unnecessarily
- **Transparent**: Fully logged and reportable

## Available Workarounds

### libproxy_segfault.py

**Issue**: Segmentation fault when using GStreamer RTSP on Ubuntu 22.04 with libproxy 0.4.17

**Symptoms**: 
- Immediate crash with SIGABRT when connecting to RTSP streams
- Crash occurs in `px_proxy_factory_get_proxies()` in libproxy.so.1

**Root Cause**: 
- libproxy 0.4.17 throws uncaught C++ exceptions across C library boundaries
- GIO loads libproxy module automatically for proxy resolution
- Exception propagation causes undefined behavior and program abort

**Solution**: 
- Set `GIO_MODULE_DIR=/dev/null` to prevent GIO from loading proxy modules
- Safe for applications that don't require system proxy settings

**Affected Systems**:
- Ubuntu 22.04 LTS
- GStreamer < 1.22
- libproxy 0.4.17-2

## Usage

### Recommended

Workarounds are automatically applied through the standard dependency system:

```python
from ax_devil_rtsp.utils.deps import ensure_gi_ready
ensure_gi_ready()  # Applies workarounds, then imports and validates GI/GStreamer
```

This is the **only recommended way** to ensure workarounds are applied. It guarantees:
- Workarounds are applied before any GI imports
- No double application
- Clear error handling and guidance

### Manual Control (For Testing/Diagnostics)

```python
from ax_devil_rtsp.setup_workarounds import ensure_safe_environment
ensure_safe_environment()  # Apply specific workarounds manually
```

### Configuration Options

Control workaround behavior with environment variables:

```bash
# Disable all workarounds (use with caution)
export AX_DEVIL_DISABLE_WORKAROUNDS=1

# Force libproxy workaround even if not detected as vulnerable
export AX_DEVIL_FORCE_LIBPROXY_WORKAROUND=1

# Normal operation (workarounds applied automatically when needed)
# No environment variables needed
```

### Advanced Usage (Direct Access)

For advanced diagnostics or custom implementations:

```python
from ax_devil_rtsp.setup_workarounds.libproxy_segfault import (
    LibproxySegfaultDetector,
    LibproxyWorkaround
)

# Check if vulnerable
detector = LibproxySegfaultDetector()
if detector.is_vulnerable():
    print("System is vulnerable to libproxy segfault")
    
    # Apply workaround
    workaround = LibproxyWorkaround()
    workaround.apply()
```

## Diagnostics

Use the dependency checker to see workaround status:

```bash
python tools/check_dependencies.py
```

Or check programmatically:

```python
from ax_devil_rtsp.setup_workarounds import get_workaround_status
status = get_workaround_status()
print(status)
```

## Adding New Workarounds

1. Create a new module in this directory (e.g., `new_issue.py`)
2. Implement detection and workaround classes following the `libproxy_segfault.py` pattern
3. Add the workaround call to `utils/deps.py`'s `ensure_gi_ready()` function
4. Export the workaround function from `setup_workarounds/__init__.py`
5. Update `tools/check_dependencies.py` to report the new workaround
6. Document the issue and solution in this README

## Design Principles

- **Single Entry Point**: All workarounds applied through `utils/deps.py` to prevent confusion
- **Fail-safe**: Workarounds should never cause more problems than they solve
- **Detectable**: All workarounds should be easily detectable and reportable
- **Reversible**: Environment changes should be minimal and non-permanent
- **Documented**: Each workaround should include comprehensive documentation
- **Tested**: Workarounds should be testable on both affected and unaffected systems
- **No Side Effects**: Module imports should not automatically apply workarounds
