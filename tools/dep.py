#!/usr/bin/env python3
"""
Unified Dependency Management for ax-devil-rtsp

This script provides dependency checking and generates installation commands
for the ax-devil-rtsp project. It ensures consistency between what is checked
and what needs to be installed by using a single source of truth for all dependencies.

Usage:
    python tools/dep.py --check      # Check dependencies (default)
    python tools/dep.py --install    # Show installation commands
    python tools/dep.py --help       # Show this help message
"""

import sys
import os
import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class PythonDependency:
    """Python package dependency."""
    name: str
    description: str
    import_name: str
    pip_package: str


@dataclass
class SystemDependency:
    """System package dependency."""
    name: str
    description: str
    ubuntu_packages: List[str]


# Single source of truth for all dependencies
PYTHON_DEPENDENCIES = [
    PythonDependency("numpy", "NumPy - Array processing", "numpy", "numpy>=1.20.0"),
    PythonDependency("opencv", "OpenCV - Computer vision library", "cv2", "opencv-python>=4.5.0"),
    PythonDependency("gi", "PyGObject - Python GObject bindings", "gi", "system-package"),
]

SYSTEM_DEPENDENCIES = [
    # Core development packages
    SystemDependency(
        "core-dev",
        "Core development libraries",
        ["libgirepository-2.0-dev", "gobject-introspection", "libcairo2-dev", 
         "libffi-dev", "pkg-config", "gcc", "libglib2.0-dev"]
    ),
    
    # GStreamer runtime and development
    SystemDependency(
        "gstreamer-core",
        "GStreamer core packages",
        ["gstreamer1.0-dev", "gstreamer1.0-tools", "gstreamer1.0-rtsp"]
    ),
    
    # GStreamer plugins
    SystemDependency(
        "gstreamer-plugins",
        "GStreamer plugin packages",
        ["gstreamer1.0-plugins-base", "gstreamer1.0-plugins-good", 
         "gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly", "gstreamer1.0-libav"]
    ),
    
    # RTSP server library
    SystemDependency(
        "gstreamer-rtsp",
        "GStreamer RTSP server library",
        ["libgstrtspserver-1.0-0"]
    ),
    
    # GObject introspection bindings
    SystemDependency(
        "gi-bindings",
        "GObject introspection bindings",
        ["gir1.2-gstreamer-1.0", "gir1.2-gst-plugins-base-1.0", "gir1.2-gst-rtsp-server-1.0"]
    ),
    
    # Python GI packages
    SystemDependency(
        "python-gi",
        "Python GObject integration",
        ["python3-gi", "python3-gst-1.0"]
    ),
    
    # Additional media and display support
    SystemDependency(
        "media-support",
        "Additional media and display support",
        ["gstreamer1.0-x", "gstreamer1.0-alsa", "gstreamer1.0-gl", 
         "gstreamer1.0-gtk3", "gstreamer1.0-qt5", "gstreamer1.0-pulseaudio", "xvfb"]
    ),
]

ENVIRONMENT_VARS = [
    'USE_REAL_CAMERA',
    'AX_DEVIL_TARGET_USER', 
    'AX_DEVIL_TARGET_PASS',
    'AX_DEVIL_TARGET_ADDR',
    'PYTHONPATH',
    'GIO_MODULE_DIR',
    'AX_DEVIL_DISABLE_WORKAROUNDS',
    'AX_DEVIL_FORCE_LIBPROXY_WORKAROUND'
]


def test_python_import(dep: PythonDependency) -> bool:
    """Test importing a Python module."""
    try:
        if dep.import_name == "gi":
            # Special GI/GStreamer test
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
            module = __import__(dep.import_name)
            version = getattr(module, '__version__', 'unknown')
            print(f"  └─ {dep.import_name}: ✅ (version: {version})")
            
        return True
        
    except Exception as e:
        print(f"  └─ {dep.import_name}: ❌ FAILED - {e}")
        return False


def check_environment() -> None:
    """Print environment information."""
    print("=== ENVIRONMENT INFO ===")
    print(f"Python version: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print(f"Platform: {sys.platform}")
    
    print(f"\n=== ENVIRONMENT VARIABLES ===")
    for var in ENVIRONMENT_VARS:
        value = os.getenv(var, '<not set>')
        print(f"{var}: {value}")


def check_workarounds() -> bool:
    """Check status of applied workarounds."""
    print(f"\n=== WORKAROUND STATUS ===")
    
    try:
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
                
            # Show additional info
            reasons = details.get('reasons', [])
            if reasons and vulnerable:
                print(f"     Reasons: {', '.join(reasons)}")
                
            if details.get('gstreamer_version'):
                print(f"     GStreamer: {details['gstreamer_version']}")
        
        return True
        
    except Exception as e:
        print(f"  └─ ❌ Failed to check workarounds: {e}")
        return False


def check_dependencies() -> Tuple[List[str], bool]:
    """Check all dependencies and return failed ones."""
    print("🔍 ax-devil-rtsp Dependency Checker")
    print("=" * 50)
    
    check_environment()
    check_workarounds()
    
    print(f"\n=== TESTING PYTHON IMPORTS ===")
    
    failed_imports = []
    
    for dep in PYTHON_DEPENDENCIES:
        print(f"\n🔧 {dep.description}")
        if not test_python_import(dep):
            failed_imports.append(dep.name)
    
    return failed_imports, len(failed_imports) == 0


def print_troubleshooting(failed_imports: List[str]) -> None:
    """Print troubleshooting information for failed imports."""
    if not failed_imports:
        return
        
    print(f"\n💡 Manual installation options:")
    
    # Create lookup for failed dependencies
    failed_deps = {dep.name: dep for dep in PYTHON_DEPENDENCIES if dep.name in failed_imports}
    
    for name in failed_imports:
        if name in failed_deps:
            dep = failed_deps[name]
            if dep.pip_package == "system-package":
                print(f"   • {dep.description}: Install via system package manager")
                print(f"     Ubuntu/Debian: sudo apt install python3-gi gobject-introspection")
            else:
                print(f"   • {dep.description}: pip install {dep.pip_package}")
    
    print(f"\n🛠️  Get install commands: python tools/dep.py --install")


def generate_install_commands() -> List[str]:
    """Generate the commands needed to install all dependencies."""
    commands = []
    
    # Update package lists
    commands.append("sudo apt-get update")
    
    # Collect all system packages into one command for efficiency
    all_packages = []
    for dep in SYSTEM_DEPENDENCIES:
        all_packages.extend(dep.ubuntu_packages)
    
    # Create install command
    packages_str = " ".join(all_packages)
    commands.append(f"sudo apt-get install -y {packages_str}")
    
    # Python dependencies
    commands.append("python -m pip install -e \".[dev]\"")
    
    return commands


def print_install_commands() -> None:
    """Print installation commands for user to copy and run."""
    print("🔧 ax-devil-rtsp Installation Commands (Ubuntu/Debian)")
    print("=" * 60)
    
    if sys.platform != "linux":
        print("❌ These commands are for Linux (Ubuntu/Debian)")
        print("📖 Please see README.md for other platforms")
        return
    
    print("\n📋 Copy and run these commands:")
    print()
    
    commands = generate_install_commands()
    
    for i, cmd in enumerate(commands, 1):
        print(f"{i}. {cmd}")
    
    print()
    print("💡 Or run all at once:")
    print()
    combined = " && ".join(commands)
    print(f"   {combined}")
    print()
    print("🔍 After installation, verify with:")
    print("   python tools/dep.py --check")


def show_install_info() -> int:
    """Show installation information and commands."""
    print_install_commands()
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified dependency management for ax-devil-rtsp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/dep.py --check      # Check dependencies (default)
  python tools/dep.py --install    # Show installation commands
  python tools/dep.py --help       # Show this help
        """
    )
    
    parser.add_argument("--check", action="store_true", help="Check dependencies and report status (default)")
    parser.add_argument("--install", action="store_true", help="Show commands to install dependencies (Ubuntu/Debian)")
    
    args = parser.parse_args()
    
    # Default to check if no arguments provided
    if not args.install and not args.check:
        args.check = True
    
    if args.install:
        return show_install_info()
    elif args.check:
        failed_imports, success = check_dependencies()
        
        print(f"\n=== SUMMARY ===")
        if not success:
            print(f"❌ FAILED IMPORTS: {', '.join(failed_imports)}")
            print_troubleshooting(failed_imports)
            return 1
        else:
            print("✅ ALL DEPENDENCIES AVAILABLE!")
            print("🚀 Ready to run tests!")
            return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())