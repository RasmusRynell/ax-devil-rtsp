from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import click


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    ok: bool
    detail: str


REQUIRED_ENV_VARS = (
    "AX_DEVIL_TARGET_ADDR",
    "AX_DEVIL_TARGET_USER",
    "AX_DEVIL_TARGET_PASS",
    "GIO_MODULE_DIR",
    "AX_DEVIL_DISABLE_WORKAROUNDS",
    "AX_DEVIL_FORCE_LIBPROXY_WORKAROUND",
)

UBUNTU_PACKAGES = (
    "gcc",
    "cmake",
    "pkg-config",
    "python3-dev",
    "libcairo2-dev",
    "libffi-dev",
    "libglib2.0-dev",
    "libgirepository-2.0-dev",
    "gobject-introspection",
    "python3-gi",
    "python3-gst-1.0",
    "gir1.2-gstreamer-1.0",
    "gir1.2-gst-plugins-base-1.0",
    "gstreamer1.0-tools",
    "gstreamer1.0-plugins-base",
    "gstreamer1.0-plugins-good",
    "gstreamer1.0-plugins-bad",
    "gstreamer1.0-plugins-ugly",
    "gstreamer1.0-libav",
)

REQUIRED_ELEMENTS = (
    "rtspsrc",
    "rtph264depay",
    "h264parse",
    "tee",
    "queue",
    "mp4mux",
    "filesink",
    "avdec_h264",
    "videoconvert",
    "appsink",
    "rtpjitterbuffer",
)

PYTHON_MODULES = (
    ("numpy", "NumPy"),
    ("cv2", "OpenCV"),
)


def _status_text(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def collect_checks() -> tuple[list[DoctorCheck], int]:
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "Platform",
            sys.platform.startswith("linux"),
            sys.platform,
        )
    )

    try:
        from .setup_workarounds import ensure_safe_environment, get_workaround_status

        ensure_safe_environment()
        workaround_status = get_workaround_status()
        vulnerable = [
            name
            for name, details in workaround_status.items()
            if details.get("vulnerable") and not details.get("workaround_applied")
        ]
        checks.append(
            DoctorCheck(
                "Workarounds",
                not vulnerable,
                "pending: " + ", ".join(vulnerable) if vulnerable else "ready",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("Workarounds", False, str(exc)))

    try:
        import gi  # type: ignore

        checks.append(
            DoctorCheck(
                "PyGObject",
                True,
                getattr(gi, "__version__", "unknown"),
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("PyGObject", False, str(exc)))
        return checks, 1

    try:
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtp", "1.0")
        from gi.repository import Gst  # type: ignore

        checks.append(DoctorCheck("GI namespaces", True, "Gst, GstRtp"))
    except Exception as exc:
        checks.append(DoctorCheck("GI namespaces", False, str(exc)))
        return checks, 1

    try:
        gi.require_version("GstRtspServer", "1.0")
        from gi.repository import GstRtspServer  # type: ignore # noqa: F401

        checks.append(DoctorCheck("GstRtspServer", True, "dev/test typelib available"))
    except Exception as exc:
        checks.append(DoctorCheck("GstRtspServer", False, str(exc)))

    try:
        Gst.init(None)
        version = ".".join(str(part) for part in Gst.version())
        checks.append(DoctorCheck("GStreamer init", True, version))
    except Exception as exc:
        checks.append(DoctorCheck("GStreamer init", False, str(exc)))
        return checks, 1

    missing_elements: list[str] = []
    for element in REQUIRED_ELEMENTS:
        if Gst.ElementFactory.find(element) is None:
            missing_elements.append(element)

    checks.append(
        DoctorCheck(
            "Required plugins",
            not missing_elements,
            ", ".join(missing_elements) if missing_elements else "all required elements found",
        )
    )

    missing_python_modules: list[str] = []
    for module_name, label in PYTHON_MODULES:
        try:
            __import__(module_name)
        except Exception as exc:
            checks.append(DoctorCheck(label, False, str(exc)))
            missing_python_modules.append(label)
        else:
            checks.append(DoctorCheck(label, True, "import OK"))

    exit_code = 0 if all(check.ok for check in checks) else 1
    return checks, exit_code


def render_doctor_report() -> int:
    checks, exit_code = collect_checks()

    click.echo("ax-devil-rtsp doctor")
    click.echo(f"Python: {sys.version.split()[0]} ({sys.executable})")
    click.echo("")

    for check in checks:
        click.echo(f"{_status_text(check.ok):7} {check.label}: {check.detail}")

    click.echo("")
    click.echo("Environment variables:")
    for name in REQUIRED_ENV_VARS:
        click.echo(f"  {name}={os.getenv(name, '<not set>')}")

    if exit_code != 0:
        click.echo("")
        click.echo("Linux packages typically needed outside Python:")
        click.echo("  sudo apt-get install -y " + " ".join(UBUNTU_PACKAGES))

    return exit_code


@click.command("doctor")
def doctor_command() -> None:
    """Check external GStreamer/GI dependencies and workaround status."""
    raise SystemExit(render_doctor_report())


if __name__ == "__main__":
    raise SystemExit(render_doctor_report())
