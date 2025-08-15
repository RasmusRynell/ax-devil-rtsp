#!/usr/bin/env python3
"""
Dependency Checker for ax-devil-rtsp

This script verifies that all required dependencies are properly installed
and can be imported. Useful for debugging CI/local environment issues.

Usage:
    python tools/check_dependencies.py
"""

import sys
import os

def test_import(name, description, extra_check=None):
    """Test importing a module and print detailed result."""
    try:
        if name == "gi_gstreamer":
            # Special case for GStreamer - test the full import chain
            import gi  # type: ignore
            print(f"  ├─ gi: ✅ (version: {getattr(gi, '__version__', 'unknown')})")
            
            gi.require_version("Gst", "1.0")
            gi.require_version("GstRtspServer", "1.0")
            print(f"  ├─ gi.require_version: ✅")
            
            from gi.repository import Gst, GstRtspServer, GLib  # type: ignore
            print(f"  ├─ Gst: ✅")
            print(f"  ├─ GstRtspServer: ✅") 
            print(f"  └─ GLib: ✅")
            
            # Test GStreamer initialization
            Gst.init(None)
            print(f"  └─ Gst.init(): ✅")
            
        else:
            module = __import__(name)
            version = getattr(module, '__version__', 'unknown')
            print(f"  └─ {name}: ✅ (version: {version})")
            
        if extra_check:
            extra_check()
            
        return True
            
    except Exception as e:
        print(f"  └─ {name}: ❌ FAILED - {e}")
        return False

def check_environment():
    """Check environment variables and system info."""
    print("=== ENVIRONMENT INFO ===")
    print(f"Python version: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print(f"Platform: {sys.platform}")
    
    # Check relevant environment variables
    env_vars = [
        'USE_REAL_CAMERA',
        'AX_DEVIL_TARGET_USER', 
        'AX_DEVIL_TARGET_PASS',
        'AX_DEVIL_TARGET_ADDR',
        'PYTHONPATH',
        'GIO_MODULE_DIR',  # Important for libproxy workaround
        'AX_DEVIL_DISABLE_WORKAROUNDS',  # Global workaround control
        'AX_DEVIL_FORCE_LIBPROXY_WORKAROUND'  # Force libproxy workaround
    ]
    
    print(f"\n=== ENVIRONMENT VARIABLES ===")
    for var in env_vars:
        value = os.getenv(var, '<not set>')
        print(f"{var}: {value}")

def check_workarounds():
    """Check status of applied workarounds."""
    print(f"\n=== WORKAROUND STATUS ===")
    
    try:
        # Import the workaround status checker
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from ax_devil_rtsp.setup_workarounds import get_workaround_status
        
        status = get_workaround_status()
        
        for name, details in status.items():
            print(f"\n🔧 {name.replace('_', ' ').title()}")
            
            if 'error' in details:
                print(f"  └─ Error: {details['error']}")
                continue
                
            vulnerable = details.get('vulnerable', False)
            applied = details.get('workaround_applied', False)
            
            if not vulnerable:
                print(f"  └─ ✅ Not vulnerable")
            elif applied:
                print(f"  └─ ✅ Vulnerable but workaround applied")
                validation = details.get('validation_passed')
                if validation is True:
                    print(f"     └─ Validation: ✅ Passed")
                elif validation is False:
                    print(f"     └─ Validation: ❌ Failed")
            else:
                print(f"  └─ ⚠️  Vulnerable - workaround needed")
                
            # Show reasons if available
            reasons = details.get('reasons', [])
            if reasons and vulnerable:
                print(f"     Reasons: {', '.join(reasons)}")
                
            # Show version info
            if details.get('gstreamer_version'):
                print(f"     GStreamer: {details['gstreamer_version']}")
        
        return True
        
    except Exception as e:
        print(f"  └─ ❌ Failed to check workarounds: {e}")
        return False

def main():
    """Main dependency checking routine."""
    print("🔍 ax-devil-rtsp Dependency Checker")
    print("=" * 50)
    
    check_environment()
    check_workarounds()
    
    print(f"\n=== TESTING IMPORTS ===")
    
    # Define all critical imports with descriptions
    imports_to_test = [
        ("numpy", "NumPy - Array processing"),
        ("cv2", "OpenCV - Computer vision library"), 
        ("gi", "PyGObject - Python GObject bindings"),
        ("gi_gstreamer", "GStreamer - Multimedia framework"),
    ]
    
    results = {}
    
    for import_name, description in imports_to_test:
        print(f"\n🔧 {description}")
        results[import_name] = test_import(import_name, description)
    
    # Summary
    print(f"\n=== SUMMARY ===")
    failed_imports = [name for name, success in results.items() if not success]
    
    if failed_imports:
        print(f"❌ FAILED IMPORTS: {', '.join(failed_imports)}")
        print(f"\n💡 Troubleshooting:")
        for failed in failed_imports:
            if failed == "cv2":
                print(f"   • Install OpenCV: pip install opencv-python")
            elif failed == "gi":
                print("   • Install PyGObject via your distro's package manager:")
                print("     - Ubuntu/Debian: sudo apt install python3-gi gobject-introspection")
                print("     - Fedora/RHEL: sudo dnf install python3-gobject gobject-introspection")
                print("     - Arch: sudo pacman -S python-gobject gobject-introspection")
            elif failed == "gi_gstreamer":
                print("   • Install GStreamer and introspection packages:")
                print("     - Ubuntu/Debian: sudo apt install gstreamer1.0-dev gstreamer1.0-plugins-\\{base,good,bad,ugly\\} gstreamer1.0-libav gir1.2-gstreamer-1.0")
                print("     - Fedora/RHEL: sudo dnf install gstreamer1-plugins-\\{base,good,bad,ugly\\}-freeworld gstreamer1-libav gobject-introspection")
        
        return 1
    else:
        print("✅ ALL DEPENDENCIES AVAILABLE!")
        print("🚀 Ready to run tests!")
        return 0

if __name__ == "__main__":
    sys.exit(main()) 