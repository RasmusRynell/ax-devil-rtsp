from __future__ import annotations

"""
Minimal dependency checks and user guidance for GI/GStreamer.

We avoid importing gi at top-level in other modules to keep import-time
failures user-friendly and provide actionable messages.
"""


def ensure_gi_ready() -> None:
    """Ensure PyGObject (gi) and core GStreamer introspection are available.

    Raises a RuntimeError with distro-specific installation guidance when the
    GI stack is unavailable or misconfigured.
    """
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
            "Install system packages:\n"
            "- Ubuntu/Debian: sudo apt install python3-gi gobject-introspection "
            "gir1.2-gstreamer-1.0 gstreamer1.0-plugins-{base,good,bad,ugly} gstreamer1.0-libav\n"
            "- Fedora/RHEL: sudo dnf install python3-gobject gobject-introspection "
            "gstreamer1-plugins-{base,good,bad,ugly}-freeworld gstreamer1-libav\n"
            "- Arch: sudo pacman -S python-gobject gobject-introspection "
            "gst-plugins-{base,good,bad,ugly} gst-libav\n"
            "- macOS (Homebrew): brew install gobject-introspection pygobject3 gstreamer "
            "gst-plugins-base gst-plugins-good\n"
            "- Windows (MSYS2): pacman -S mingw-w64-ucrt-x86_64-python-gobject "
            "mingw-w64-ucrt-x86_64-gstreamer\n\n"
            f"Original error: {exc}"
        )
        raise RuntimeError(guidance) from exc


