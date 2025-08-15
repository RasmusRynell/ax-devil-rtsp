from __future__ import annotations

"""
Minimal dependency checks and user guidance for GI/GStreamer.

We avoid importing gi at top-level in other modules to keep import-time
failures user-friendly and provide actionable messages.
"""


def ensure_gi_ready() -> None:
    """Ensure PyGObject (gi) and core GStreamer introspection are available.

    Applies known workarounds for compatibility issues before attempting
    to import GI/GStreamer components.

    Raises a RuntimeError with distro-specific installation guidance when the
    GI stack is unavailable or misconfigured.
    """
    # Apply workarounds before any gi imports to prevent crashes
    from .setup_workarounds import ensure_safe_environment
    ensure_safe_environment()
    
    try:
        import gi  # type: ignore

        # Require core namespaces used by this project
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtsp", "1.0")
        gi.require_version("GstRtp", "1.0")

        # Import to validate binding availability and lazy-load shared libs
        from gi.repository import GLib, Gst, GstRtp  # type: ignore # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        guidance = (
            "PyGObject/GStreamer not available or incompatible.\n\n"
            "🔧 Check dependencies:\n"
            "   python tools/dep.py --check\n\n"
            "🛠️ Get install commands (Ubuntu/Debian):\n"
            "   python tools/dep.py --install\n\n"
            "For other platforms, see README.md for manual installation.\n\n"
            f"Original error: {exc}"
        )
        raise RuntimeError(guidance) from exc
