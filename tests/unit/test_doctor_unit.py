"""Unit tests for doctor package-manager detection and install commands."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from ax_devil_rtsp import doctor


@pytest.fixture
def os_release(monkeypatch):
    def set_release(release):
        monkeypatch.setattr(doctor.sys, "platform", "linux")
        monkeypatch.setattr(doctor.platform, "freedesktop_os_release", lambda: release)

    return set_release


@pytest.fixture
def checks_result(monkeypatch):
    def set_result(checks, missing):
        monkeypatch.setattr(doctor, "_run_checks", lambda: (checks, missing))

    return set_result


@pytest.mark.parametrize(
    "release, expected",
    [
        ({"ID": "ubuntu", "ID_LIKE": "debian"}, "apt"),
        ({"ID": "debian"}, "apt"),
        ({"ID": "arch"}, "pacman"),
        ({"ID": "omarchy", "ID_LIKE": "arch"}, "pacman"),
        ({"ID": "fedora"}, "dnf"),
        ({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}, None),
    ],
)
def test_detect_package_manager(os_release, release, expected):
    os_release(release)
    assert doctor.detect_package_manager() == expected


def test_detect_package_manager_without_os_release(monkeypatch):
    def missing():
        raise OSError("no os-release")

    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor.platform, "freedesktop_os_release", missing)
    assert doctor.detect_package_manager() is None


@pytest.mark.parametrize(
    "interpreter_platform, expected",
    [("win-amd64", "pip"), ("win32", "pip"), ("win-arm64", None)],
)
def test_detect_package_manager_follows_windows_interpreter(
    monkeypatch, interpreter_platform, expected
):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(doctor.sysconfig, "get_platform", lambda: interpreter_platform)
    assert doctor.detect_package_manager() == expected


def test_detect_package_manager_uses_wheels_on_macos(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    assert doctor.detect_package_manager() == "pip"


def test_install_command_windows_uses_gstreamer_wheels():
    assert doctor.install_command("pip") == "pip install gstreamer-meta"


def test_doctor_text_output_on_windows_skips_pygobject_hint(
    monkeypatch, checks_result
):
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    checks_result(
        [doctor.DoctorCheck("PyGObject", False, "No module named gi")],
        list(doctor._REQUIRED_KEYS),
    )

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert "pip install gstreamer-meta" in result.output
    assert "ax-devil-rtsp[gstreamer]" not in result.output


def test_platform_check_does_not_fail_report_off_linux(monkeypatch):
    from ax_devil_rtsp import setup_workarounds

    monkeypatch.setattr(doctor.sys, "platform", "win32")
    monkeypatch.setattr(setup_workarounds, "ensure_safe_environment", lambda: None)
    monkeypatch.setattr(setup_workarounds, "get_workaround_status", lambda: {})
    monkeypatch.setitem(doctor.sys.modules, "gi", None)

    checks, _ = doctor._run_checks()

    assert checks[0] == doctor.DoctorCheck("Platform", True, "win32")


def test_install_command_full_and_optional():
    full = doctor.install_command("pacman")
    assert full.startswith("sudo pacman -S --needed ")
    assert "gst-libav" in full
    assert "gst-rtsp-server" not in full
    assert "gst-rtsp-server" in doctor.install_command("pacman", include_optional=True)


def test_install_command_unknown_os(os_release):
    os_release({"ID": "opensuse-tumbleweed"})
    assert doctor.install_command() is None


def test_report_recommends_only_missing_packages(os_release, checks_result):
    os_release({"ID": "ubuntu"})
    checks_result(
        [
            doctor.DoctorCheck("Required plugins", False, "avdec_h264"),
            doctor.DoctorCheck("GstRtspServer", False, "missing", required=False),
        ],
        ["rtsp_server", "avdec_h264"],
    )

    report = doctor.check_environment()

    assert not report.ok
    assert report.install_command == "sudo apt-get install -y gstreamer1.0-libav"
    assert (
        report.optional_install_command
        == "sudo apt-get install -y gir1.2-gst-rtsp-server-1.0"
    )


def test_missing_optional_check_does_not_fail_report(os_release, checks_result):
    os_release({"ID": "arch"})
    checks_result(
        [
            doctor.DoctorCheck("Required plugins", True, "ok"),
            doctor.DoctorCheck("GstRtspServer", False, "missing", required=False),
        ],
        ["rtsp_server"],
    )

    report = doctor.check_environment()

    assert report.ok
    assert report.install_command is None
    assert report.optional_install_command == "sudo pacman -S --needed gst-rtsp-server"


def test_doctor_json_output(os_release, checks_result):
    os_release({"ID": "arch"})
    checks_result(
        [doctor.DoctorCheck("Required plugins", False, "avdec_h264")],
        ["avdec_h264"],
    )

    result = CliRunner().invoke(doctor.doctor_command, ["--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["package_manager"] == "pacman"
    assert data["install_command"] == "sudo pacman -S --needed gst-libav"
    assert data["checks"][0]["label"] == "Required plugins"


def test_doctor_text_output_shows_install_command(os_release, checks_result):
    os_release({"ID": "arch"})
    checks_result(
        [doctor.DoctorCheck("Required plugins", False, "avdec_h264")],
        ["avdec_h264"],
    )

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert result.exit_code == 1
    assert "MISSING  Required plugins: avdec_h264" in result.output
    assert "sudo pacman -S --needed gst-libav" in result.output


def test_install_command_apt_and_unknown_manager():
    assert "gstreamer1.0-libav" in doctor.install_command("apt")
    assert doctor.install_command("yum") is None


def test_doctor_text_output_hints_when_no_system_package_is_missing(
    os_release, checks_result
):
    os_release({"ID": "arch"})
    checks_result([doctor.DoctorCheck("NumPy", False, "No module named numpy")], [])

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert result.exit_code == 1
    assert "pip install ax-devil-rtsp" in result.output


def test_doctor_text_output_hints_pygobject_reinstall(os_release, checks_result):
    os_release({"ID": "arch"})
    checks_result(
        [doctor.DoctorCheck("PyGObject", False, "No module named gi")],
        list(doctor._REQUIRED_KEYS),
    )

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert "sudo pacman -S --needed base-devel" in result.output
    assert "pip install 'ax-devil-rtsp[gstreamer]'" in result.output


class _GiWithoutGst:
    __version__ = "0.0"

    @staticmethod
    def require_version(namespace, version):
        raise ValueError(f"Namespace {namespace} not available")


@pytest.mark.parametrize(
    "gi_module, expected_missing",
    [
        (None, list(doctor._REQUIRED_KEYS)),
        (_GiWithoutGst, list(doctor._REQUIRED_KEYS[1:])),
    ],
    ids=["gi_missing", "gst_namespaces_missing"],
)
def test_run_checks_reports_everything_after_an_early_stop(
    monkeypatch, gi_module, expected_missing
):
    from ax_devil_rtsp import setup_workarounds

    # Off Linux nothing is checked without gi; Linux is covered below.
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(setup_workarounds, "ensure_safe_environment", lambda: None)
    monkeypatch.setattr(setup_workarounds, "get_workaround_status", lambda: {})
    monkeypatch.setitem(doctor.sys.modules, "gi", gi_module)

    checks, missing = doctor._run_checks()

    assert missing == expected_missing
    assert not checks[-1].ok


def test_doctor_text_output_hints_bindings_without_package_manager(
    os_release, checks_result
):
    os_release({"ID": "opensuse-tumbleweed"})
    checks_result(
        [doctor.DoctorCheck("PyGObject", False, "No module named gi")],
        list(doctor._REQUIRED_KEYS),
    )

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert "No install command known for this OS" in result.output
    assert "pip install 'ax-devil-rtsp[gstreamer]'" in result.output


@pytest.fixture
def linux_without_gi(monkeypatch, os_release):
    """Linux without PyGObject; the native system state is set per test."""
    from ax_devil_rtsp import setup_workarounds

    monkeypatch.setattr(setup_workarounds, "ensure_safe_environment", lambda: None)
    monkeypatch.setattr(setup_workarounds, "get_workaround_status", lambda: {})
    monkeypatch.setitem(doctor.sys.modules, "gi", None)
    os_release({"ID": "ubuntu", "ID_LIKE": "debian"})

    def set_system(
        glib=(2, 80, 0),
        build_missing=(),
        typelibs=True,
        gst_installed=True,
        elements_missing=(),
    ):
        def gst_inspect(*args):
            if not gst_installed:
                raise FileNotFoundError("gst-inspect-1.0")
            if args[0] == "--exists" and gst_installed == "hangs":
                raise subprocess.TimeoutExpired(["gst-inspect-1.0", *args], 60)
            missing = args[0] == "--exists" and args[1] in elements_missing
            return subprocess.CompletedProcess(
                args, 1 if missing else 0, "gst-inspect-1.0 version 1.24.2\n", ""
            )

        monkeypatch.setattr(doctor, "_glib_version", lambda: glib)
        monkeypatch.setattr(doctor, "_missing_build_tools", lambda: list(build_missing))
        monkeypatch.setattr(doctor, "_typelib_found", lambda namespace: typelibs)
        monkeypatch.setattr(doctor, "_gst_inspect", gst_inspect)

    return set_system


def test_native_prerequisites_ready_leaves_only_the_bindings(linux_without_gi):
    linux_without_gi()

    report = doctor.check_environment()
    result = CliRunner().invoke(doctor.doctor_command, [])

    assert report.bindings_ready
    assert report.install_command is None
    assert "Install the missing packages" not in result.output
    assert "Install the Python bindings:" in result.output
    assert "pip install 'ax-devil-rtsp[gstreamer]'" in result.output


def test_native_check_reports_only_missing_packages(linux_without_gi):
    linux_without_gi(
        build_missing=["girepository-2.0"], elements_missing=["avdec_h264"]
    )

    report = doctor.check_environment()

    assert not report.bindings_ready
    assert "libgirepository-2.0-dev" in report.install_command
    assert "gstreamer1.0-libav" in report.install_command
    assert "gir1.2-gstreamer-1.0" not in report.install_command
    assert "gstreamer1.0-plugins-good" not in report.install_command


def test_native_check_without_gstreamer_reports_every_element(linux_without_gi):
    linux_without_gi(gst_installed=False, typelibs=False)

    report = doctor.check_environment()

    assert "gir1.2-gstreamer-1.0" in report.install_command
    assert "gstreamer1.0-tools" in report.install_command
    assert "gstreamer1.0-libav" in report.install_command


def test_too_old_glib_is_not_an_install_step(linux_without_gi):
    # A missing element proves the check stops at GLib: nothing is offered.
    linux_without_gi(glib=(2, 72, 4), elements_missing=["avdec_h264"])

    report = doctor.check_environment()
    result = CliRunner().invoke(doctor.doctor_command, [])

    glib = next(check for check in report.checks if check.label == "GLib")
    assert not glib.ok
    assert "2.72.4 is too old" in glib.detail
    assert report.install_command is None
    assert not report.bindings_ready
    assert not report.supported
    assert "This system cannot stream" in result.output
    assert "Install the missing packages" not in result.output
    assert "ax-devil-rtsp[gstreamer]" not in result.output


def test_fedora_gets_dnf_command_and_rpm_fusion_hint(linux_without_gi, os_release):
    linux_without_gi(elements_missing=["avdec_h264"])
    os_release({"ID": "fedora"})

    report = doctor.check_environment()
    result = CliRunner().invoke(doctor.doctor_command, [])

    assert report.install_command == "sudo dnf install -y gstreamer1-plugin-libav"
    assert len(report.hints) == 1
    assert "dnf swap -y ffmpeg-free ffmpeg" in result.output


def test_typelib_found_on_gi_typelib_path(monkeypatch, tmp_path):
    (tmp_path / "GstRtp-1.0.typelib").write_bytes(b"")
    monkeypatch.setenv("GI_TYPELIB_PATH", str(tmp_path))

    assert doctor._typelib_found("GstRtp")
    assert not doctor._typelib_found("NoSuchNamespace")


def test_too_old_glib_on_unknown_distro_offers_nothing(linux_without_gi, os_release):
    linux_without_gi(glib=(2, 72, 4))
    os_release({"ID": "opensuse-leap"})

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert "This system cannot stream" in result.output
    assert "ax-devil-rtsp[gstreamer]" not in result.output


def test_unknown_distro_ready_for_bindings(linux_without_gi, os_release):
    linux_without_gi()
    os_release({"ID": "opensuse-tumbleweed"})

    report = doctor.check_environment()
    result = CliRunner().invoke(doctor.doctor_command, [])

    assert report.bindings_ready
    assert "No install command known" not in result.output
    assert "Install the Python bindings:" in result.output


def test_unknown_distro_lists_what_is_missing(linux_without_gi, os_release):
    linux_without_gi(build_missing=["C compiler"])
    os_release({"ID": "opensuse-tumbleweed"})

    result = CliRunner().invoke(doctor.doctor_command, [])

    assert "Install: PyGObject build (C compiler)" in result.output
    assert "Then install the Python bindings:" in result.output


def test_gst_inspect_timeout_reports_gstreamer_missing(linux_without_gi):
    linux_without_gi(gst_installed="hangs")

    report = doctor.check_environment()

    gstreamer = next(check for check in report.checks if check.label == "GStreamer")
    assert not gstreamer.ok
    assert "gstreamer1.0-tools" in report.install_command


def test_missing_build_tools(monkeypatch, tmp_path):
    tools = {"pkg-config": "/usr/bin/pkg-config"}
    monkeypatch.setattr(doctor.shutil, "which", tools.get)
    monkeypatch.setattr(
        doctor.sysconfig, "get_paths", lambda: {"include": str(tmp_path)}
    )

    def pkg_config(args, **kwargs):
        missing = args[-1] == "cairo-gobject"
        return subprocess.CompletedProcess(args, 1 if missing else 0)

    monkeypatch.setattr(doctor.subprocess, "run", pkg_config)

    missing = doctor._missing_build_tools()

    version = ".".join(str(part) for part in doctor.sys.version_info[:2])
    assert missing == [
        "C compiler",
        f"Python {version} headers ({tmp_path})",
        "cairo-gobject",
    ]


def test_macos_without_wheels_is_not_bindings_ready(monkeypatch):
    from ax_devil_rtsp import setup_workarounds

    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(setup_workarounds, "ensure_safe_environment", lambda: None)
    monkeypatch.setattr(setup_workarounds, "get_workaround_status", lambda: {})
    monkeypatch.setitem(doctor.sys.modules, "gi", None)

    report = doctor.check_environment()

    assert not report.bindings_ready
    assert report.install_command == "pip install gstreamer-meta"
