"""
Minimal dependency checks and user guidance for GI/GStreamer.

We avoid importing gi at top-level in other modules to keep import-time
failures user-friendly and provide actionable messages.
"""

from __future__ import annotations

_gstreamer_wheels_ready = False


def use_gstreamer_wheels() -> bool:
    """Make GStreamer from the pip wheels (``gstreamer-meta``) importable.

    The wheels keep gi, the typelibs and the plugins inside their own packages.
    Their ``.pth`` file normally adds those paths at interpreter startup; this is
    the fallback for when it did not run (``python -S``, embedded or frozen
    interpreters). Call it before ``import gi``. Returns False when the wheels
    are not installed (e.g. Linux system packages).
    """
    global _gstreamer_wheels_ready
    if _gstreamer_wheels_ready:
        return True
    try:
        from gstreamer_libs import setup_python_environment  # type: ignore
    except ImportError:
        return False
    setup_python_environment()
    _gstreamer_wheels_ready = True
    return True


def ensure_gi_ready() -> None:
    """Ensure PyGObject (gi) and core GStreamer introspection are available.

    Applies known workarounds for compatibility issues before attempting
    to import GI/GStreamer components.

    Raises a RuntimeError with distro-specific installation guidance when the
    GI stack is unavailable or misconfigured.
    """
    use_gstreamer_wheels()

    # Apply workarounds before any gi imports to prevent crashes
    from ..setup_workarounds import ensure_safe_environment
    ensure_safe_environment()
    
    try:
        import gi  # type: ignore

        # Require core namespaces used by this project
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtp", "1.0")

        # Import to validate binding availability and lazy-load shared libs
        from gi.repository import GLib, Gst, GstRtp  # type: ignore # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        guidance = (
            "PyGObject/GStreamer not available or incompatible.\n\n"
            "🔧 Check dependencies:\n"
            "   ax-devil-rtsp doctor\n\n"
            "Install the required GStreamer/GI system packages from README.md,\n"
            "then retry.\n\n"
            f"Original error: {exc}"
        )
        raise RuntimeError(guidance) from exc
