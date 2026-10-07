from __future__ import annotations

import ctypes
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import click


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    ok: bool
    detail: str
    required: bool = True


@dataclass(frozen=True)
class EnvironmentReport:
    """Result of check_environment()."""

    checks: tuple[DoctorCheck, ...]
    package_manager: str | None
    # Command installing the missing required packages, None when nothing is
    # missing or the OS has no known package manager.
    install_command: str | None
    # Command installing missing optional packages (the test-suite RTSP server).
    optional_install_command: str | None
    # Extra steps the install command cannot express (e.g. third-party repos).
    hints: tuple[str, ...] = ()
    # True when only PyGObject is missing and the system can build it: on
    # Linux, installing the gstreamer extra is the last step.
    bindings_ready: bool = False
    # False when no package can make this system stream (GLib too old).
    supported: bool = True

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [asdict(check) for check in self.checks],
            "package_manager": self.package_manager,
            "install_command": self.install_command,
            "optional_install_command": self.optional_install_command,
            "hints": list(self.hints),
            "bindings_ready": self.bindings_ready,
            "supported": self.supported,
        }


REQUIRED_ENV_VARS = (
    "AX_DEVIL_TARGET_ADDR",
    "AX_DEVIL_TARGET_USER",
    "AX_DEVIL_TARGET_PASS",
    "GIO_MODULE_DIR",
    "AX_DEVIL_DISABLE_WORKAROUNDS",
    "AX_DEVIL_FORCE_LIBPROXY_WORKAROUND",
)

REQUIRED_ELEMENTS = (
    "rtspsrc",
    "rtph264depay",
    "h264parse",
    "avdec_h264",
    "videoconvert",
    "appsink",
    "rtpjitterbuffer",
)

# PyGObject 3.54 (the gstreamer extra) builds against girepository-2.0,
# which ships with GLib 2.80.
MIN_GLIB = (2, 80)

GI_NAMESPACES = ("Gst", "GstRtp")

# Reported as missing when no package can fix the system (GLib too old).
_UNSUPPORTED = "unsupported"

PYTHON_MODULES = (
    ("numpy", "NumPy"),
    ("cv2", "OpenCV"),
)

# Requirement keys, in install order. "pygobject" covers the headers pip needs
# to build PyGObject; "rtsp_server" is optional and only used by the tests.
_REQUIRED_KEYS = ("pygobject", "gi_namespaces", "gstreamer", *REQUIRED_ELEMENTS)
_OPTIONAL_KEYS = ("rtsp_server",)

# package manager -> (install command prefix, requirement key -> packages)
_PACKAGES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "apt": (
        "sudo apt-get install -y",
        {
            "pygobject": (
                "gcc", "cmake", "pkg-config", "python3-dev", "libcairo2-dev",
                "libffi-dev", "libglib2.0-dev", "libgirepository-2.0-dev",
                "gobject-introspection",
            ),
            "gi_namespaces": ("gir1.2-gstreamer-1.0", "gir1.2-gst-plugins-base-1.0"),
            "gstreamer": ("gstreamer1.0-tools", "gstreamer1.0-plugins-base"),
            "rtspsrc": ("gstreamer1.0-plugins-good",),
            "rtph264depay": ("gstreamer1.0-plugins-good",),
            "rtpjitterbuffer": ("gstreamer1.0-plugins-good",),
            "h264parse": ("gstreamer1.0-plugins-bad",),
            "avdec_h264": ("gstreamer1.0-libav",),
            "videoconvert": ("gstreamer1.0-plugins-base",),
            "appsink": ("gstreamer1.0-plugins-base",),
            "rtsp_server": ("gir1.2-gst-rtsp-server-1.0",),
        },
    ),
    "pacman": (
        "sudo pacman -S --needed",
        {
            "pygobject": ("base-devel", "cairo", "glib2", "libffi", "pkgconf"),
            "gi_namespaces": ("gstreamer", "gst-plugins-base-libs"),
            "gstreamer": ("gstreamer", "gst-plugins-base-libs"),
            "rtspsrc": ("gst-plugins-good",),
            "rtph264depay": ("gst-plugins-good",),
            "rtpjitterbuffer": ("gst-plugins-good",),
            "h264parse": ("gst-plugins-bad-libs",),
            "avdec_h264": ("gst-libav",),
            "videoconvert": ("gst-plugins-base-libs",),
            "appsink": ("gst-plugins-base-libs",),
            "rtsp_server": ("gst-rtsp-server",),
        },
    ),
    "dnf": (
        "sudo dnf install -y",
        {
            "pygobject": (
                "gcc", "cmake", "pkgconf-pkg-config", "python3-devel", "cairo-devel",
                "cairo-gobject-devel", "libffi-devel", "glib2-devel",
                "gobject-introspection-devel",
            ),
            "gi_namespaces": ("gstreamer1", "gstreamer1-plugins-base"),
            "gstreamer": ("gstreamer1", "gstreamer1-plugins-base"),
            "rtspsrc": ("gstreamer1-plugins-good",),
            "rtph264depay": ("gstreamer1-plugins-good",),
            "rtpjitterbuffer": ("gstreamer1-plugins-good",),
            "h264parse": ("gstreamer1-plugins-bad-free",),
            "avdec_h264": ("gstreamer1-plugin-libav",),
            "videoconvert": ("gstreamer1-plugins-base",),
            "appsink": ("gstreamer1-plugins-base",),
            "rtsp_server": ("gstreamer1-rtsp-server",),
        },
    ),
    # Windows/macOS: the gstreamer-meta wheels bundle GStreamer and PyGObject.
    "pip": (
        "pip install",
        {key: ("gstreamer-meta",) for key in (*_REQUIRED_KEYS, *_OPTIONAL_KEYS)},
    ),
}


# package manager -> requirement key -> step the install command cannot express
_HINTS: dict[str, dict[str, str]] = {
    "dnf": {
        # Fedora's FFmpeg has no H.264 decoder; the plugin registry caches that.
        "avdec_h264": (
            "avdec_h264 needs FFmpeg from RPM Fusion: enable RPM Fusion Free, then "
            "sudo dnf swap -y ffmpeg-free ffmpeg --allowerasing && "
            "rm -rf ~/.cache/gstreamer-1.0"
        ),
    },
}


def _packages_for(package_manager: str, keys: Iterable[str]) -> list[str]:
    table = _PACKAGES[package_manager][1]
    return list(dict.fromkeys(pkg for key in keys for pkg in table[key]))


UBUNTU_PACKAGES = tuple(_packages_for("apt", _REQUIRED_KEYS))


def detect_package_manager() -> str | None:
    """Return "apt"/"pacman" on known Linux distros, "pip" on Windows/macOS, else None.

    The GStreamer wheels have no build for ARM64 Python on Windows, so there is
    no command there. This asks the interpreter, not the CPU: x64 Python on an
    ARM64 machine can use the wheels.
    """
    if sys.platform == "darwin":
        return "pip"
    if sys.platform == "win32":
        return None if sysconfig.get_platform() == "win-arm64" else "pip"
    if not sys.platform.startswith("linux"):
        return None
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return None
    ids = {release.get("ID", ""), *release.get("ID_LIKE", "").split()}
    if ids & {"debian", "ubuntu"}:
        return "apt"
    if "arch" in ids:
        return "pacman"
    if "fedora" in ids:
        return "dnf"
    return None


def install_command(
    package_manager: str | None = None,
    *,
    include_optional: bool = False,
) -> str | None:
    """Return the command installing all system packages ax-devil-rtsp needs.

    Detects the package manager when none is given. Returns None when the OS
    or package manager is not supported. Use check_environment() for only
    what is missing.
    """
    keys = _REQUIRED_KEYS + (_OPTIONAL_KEYS if include_optional else ())
    return _install_command(package_manager or detect_package_manager(), keys)


def _install_command(package_manager: str | None, keys: Iterable[str]) -> str | None:
    if package_manager not in _PACKAGES:
        return None
    packages = _packages_for(package_manager, keys)
    if not packages:
        return None
    return f"{_PACKAGES[package_manager][0]} {' '.join(packages)}"


def _status_text(check: DoctorCheck) -> str:
    if check.ok:
        return "OK"
    return "MISSING" if check.required else "OPTIONAL"


def _run_checks() -> tuple[list[DoctorCheck], list[str]]:
    """Run all checks; return them with the requirement keys that failed."""
    checks: list[DoctorCheck] = []

    checks.append(DoctorCheck("Platform", True, sys.platform))

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

    for module_name, label in PYTHON_MODULES:
        try:
            __import__(module_name)
        except Exception as exc:
            checks.append(DoctorCheck(label, False, str(exc)))
        else:
            checks.append(DoctorCheck(label, True, "import OK"))

    # Without GI or GStreamer the later checks cannot run, so everything
    # from that point on is reported as missing.
    try:
        from .utils.deps import use_gstreamer_wheels

        use_gstreamer_wheels()
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
        if not sys.platform.startswith("linux"):
            return checks, list(_REQUIRED_KEYS)
        # On Linux, PyGObject is the gstreamer extra; check what it needs
        # without gi so the user installs every system package in one go.
        native_checks, missing = _native_checks()
        return checks + native_checks, missing

    try:
        gi.require_version("Gst", "1.0")
        gi.require_version("GstRtp", "1.0")
        from gi.repository import Gst  # type: ignore

        checks.append(DoctorCheck("GI namespaces", True, "Gst, GstRtp"))
    except Exception as exc:
        checks.append(DoctorCheck("GI namespaces", False, str(exc)))
        return checks, list(_REQUIRED_KEYS[1:])

    missing: list[str] = []

    try:
        gi.require_version("GstRtspServer", "1.0")
        from gi.repository import GstRtspServer  # type: ignore # noqa: F401

        checks.append(
            DoctorCheck("GstRtspServer", True, "dev/test typelib available", False)
        )
    except Exception as exc:
        checks.append(
            DoctorCheck("GstRtspServer", False, f"only needed for tests: {exc}", False)
        )
        missing.append("rtsp_server")

    try:
        Gst.init(None)
        version = ".".join(str(part) for part in Gst.version())
        checks.append(DoctorCheck("GStreamer init", True, version))
    except Exception as exc:
        checks.append(DoctorCheck("GStreamer init", False, str(exc)))
        return checks, missing + list(_REQUIRED_KEYS[2:])

    missing_elements: list[str] = []
    for element in REQUIRED_ELEMENTS:
        if Gst.ElementFactory.find(element) is None:
            missing_elements.append(element)
    missing.extend(missing_elements)

    checks.append(
        DoctorCheck(
            "Required plugins",
            not missing_elements,
            ", ".join(missing_elements)
            if missing_elements
            else "all required elements found",
        )
    )

    return checks, missing


def _glib_version() -> tuple[int, ...] | None:
    """Return the runtime GLib version, read from the library without gi."""
    try:
        lib = ctypes.CDLL("libglib-2.0.so.0")
        return tuple(
            ctypes.c_uint.in_dll(lib, f"glib_{part}_version").value
            for part in ("major", "minor", "micro")
        )
    except (OSError, ValueError):
        return None


def _missing_build_tools() -> list[str]:
    """Return what pip lacks to build PyGObject for this interpreter."""
    missing = [] if shutil.which("cc") or shutil.which("gcc") else ["C compiler"]
    include = sysconfig.get_paths()["include"]
    if not os.path.isfile(os.path.join(include, "Python.h")):
        version = ".".join(str(part) for part in sys.version_info[:2])
        missing.append(f"Python {version} headers ({include})")
    if not shutil.which("pkg-config"):
        return [*missing, "pkg-config"]
    # cmake is in the install command for pip's build but not needed to detect.
    for module in ("girepository-2.0", "cairo", "cairo-gobject", "libffi"):
        found = subprocess.run(
            ["pkg-config", "--exists", module], capture_output=True, timeout=30
        )
        if found.returncode != 0:
            missing.append(module)
    return missing


def _gst_inspect(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gst-inspect-1.0", *args], capture_output=True, text=True, timeout=60
    )


def _typelib_found(namespace: str) -> bool:
    paths = [p for p in os.environ.get("GI_TYPELIB_PATH", "").split(os.pathsep) if p]
    paths += glob.glob("/usr/lib*/girepository-1.0")
    paths += glob.glob("/usr/lib/*/girepository-1.0")
    paths += glob.glob("/usr/local/lib*/girepository-1.0")
    typelib = f"{namespace}-1.0.typelib"
    return any(os.path.isfile(os.path.join(path, typelib)) for path in paths)


def _native_checks() -> tuple[list[DoctorCheck], list[str]]:
    """Check the system packages PyGObject and streaming need, without gi."""
    checks: list[DoctorCheck] = []
    missing: list[str] = []
    minimum = ".".join(str(part) for part in MIN_GLIB)

    glib = _glib_version()
    if glib is None:
        checks.append(DoctorCheck("GLib", False, "libglib-2.0 not found"))
        missing.append("pygobject")
    elif glib[:2] < MIN_GLIB:
        # No package installs a newer GLib, so no install step can help.
        found = ".".join(str(part) for part in glib)
        checks.append(
            DoctorCheck(
                "GLib",
                False,
                f"{found} is too old; streaming on Linux needs GLib {minimum}+ "
                "(e.g. Ubuntu 24.04, Debian 13, Fedora 40 or newer)",
            )
        )
        return checks, [_UNSUPPORTED]
    else:
        checks.append(DoctorCheck("GLib", True, ".".join(str(p) for p in glib)))
        build_missing = _missing_build_tools()
        checks.append(
            DoctorCheck(
                "PyGObject build",
                not build_missing,
                ", ".join(build_missing) if build_missing else "ready",
            )
        )
        if build_missing:
            missing.append("pygobject")

    namespaces_missing = [ns for ns in GI_NAMESPACES if not _typelib_found(ns)]
    checks.append(
        DoctorCheck(
            "GI namespaces",
            not namespaces_missing,
            ", ".join(namespaces_missing)
            if namespaces_missing
            else ", ".join(GI_NAMESPACES),
        )
    )
    if namespaces_missing:
        missing.append("gi_namespaces")

    try:
        version = _gst_inspect("--version").stdout.splitlines()[0]
        missing_elements = [
            element
            for element in REQUIRED_ELEMENTS
            if _gst_inspect("--exists", element).returncode != 0
        ]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        checks.append(DoctorCheck("GStreamer", False, f"gst-inspect-1.0: {exc}"))
        return checks, missing + ["gstreamer", *REQUIRED_ELEMENTS]
    checks.append(DoctorCheck("GStreamer", True, version))

    checks.append(
        DoctorCheck(
            "Required plugins",
            not missing_elements,
            ", ".join(missing_elements)
            if missing_elements
            else "all required elements found",
        )
    )
    return checks, missing + missing_elements


def check_environment() -> EnvironmentReport:
    """Check GStreamer/GI dependencies and say how to install what is missing.

    Safe to call from other packages; it never raises for a missing dependency.
    Like ensure_gi_ready(), it applies the GIO workarounds to this process's
    environment, initialises GStreamer, and imports NumPy and OpenCV.
    """
    checks, missing = _run_checks()
    package_manager = detect_package_manager()
    hints = _HINTS.get(package_manager or "", {})
    failed = {check.label for check in checks if check.required and not check.ok}
    return EnvironmentReport(
        checks=tuple(checks),
        package_manager=package_manager,
        install_command=_install_command(
            package_manager, [key for key in missing if key in _REQUIRED_KEYS]
        ),
        optional_install_command=_install_command(
            package_manager, [key for key in missing if key in _OPTIONAL_KEYS]
        ),
        hints=tuple(hints[key] for key in dict.fromkeys(missing) if key in hints),
        # Off Linux, a missing gi also means every system package is missing.
        bindings_ready=failed == {"PyGObject"}
        and not any(key in _REQUIRED_KEYS for key in missing),
        supported=_UNSUPPORTED not in missing,
    )


def collect_checks() -> tuple[list[DoctorCheck], int]:
    report = check_environment()
    return list(report.checks), 0 if report.ok else 1


def render_doctor_report() -> int:
    report = check_environment()

    click.echo("ax-devil-rtsp doctor")
    click.echo(f"Python: {sys.version.split()[0]} ({sys.executable})")
    click.echo("")

    for check in report.checks:
        click.echo(f"{_status_text(check):8} {check.label}: {check.detail}")

    click.echo("")
    click.echo("Environment variables:")
    for name in REQUIRED_ENV_VARS:
        click.echo(f"  {name}={os.getenv(name, '<not set>')}")

    if not report.ok:
        click.echo("")
        # On Linux, PyGObject comes from the gstreamer extra, not the OS packages.
        bindings_missing = sys.platform.startswith("linux") and any(
            c.label == "PyGObject" and not c.ok for c in report.checks
        )
        system_gaps = [
            f"{c.label} ({c.detail})"
            for c in report.checks
            if c.required and not c.ok and c.label != "PyGObject"
        ]
        bindings_step: str | None = "Then install the Python bindings:"
        if not report.supported:
            bindings_step = None
            click.echo("This system cannot stream; see the MISSING items above.")
        elif report.install_command:
            click.echo("Install the missing packages:")
            click.echo(f"  {report.install_command}")
            for hint in report.hints:
                click.echo(f"  {hint}")
        elif report.bindings_ready:
            bindings_step = "Install the Python bindings:"
        elif report.package_manager is None:
            needs = system_gaps or [
                f"GStreamer with the elements {', '.join(REQUIRED_ELEMENTS)}"
            ]
            click.echo(
                f"No install command known for this OS. Install: {'; '.join(needs)}"
            )
        else:
            bindings_step = None
            click.echo(
                "Fix the MISSING items above. "
                "Python packages: pip install ax-devil-rtsp"
            )
        if bindings_missing and bindings_step:
            click.echo(bindings_step)
            click.echo("  pip install 'ax-devil-rtsp[gstreamer]'")
    if report.optional_install_command:
        click.echo("")
        click.echo("Optional, needed to run the test suite:")
        click.echo(f"  {report.optional_install_command}")

    return 0 if report.ok else 1


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def doctor_command(as_json: bool) -> None:
    """Check external GStreamer/GI dependencies and workaround status."""
    if as_json:
        report = check_environment()
        click.echo(json.dumps(report.to_dict(), indent=2))
        raise SystemExit(0 if report.ok else 1)
    raise SystemExit(render_doctor_report())


if __name__ == "__main__":
    raise SystemExit(render_doctor_report())
