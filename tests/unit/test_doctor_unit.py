"""Unit tests for doctor package-manager detection and install commands."""

import json

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
        ({"ID": "fedora"}, None),
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
    os_release({"ID": "fedora"})
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
