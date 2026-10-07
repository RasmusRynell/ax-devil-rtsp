"""The package imports without PyGObject, which is an optional extra on Linux."""

import subprocess
import sys


def test_package_imports_without_gi():
    code = (
        "import sys\n"
        "sys.modules['gi'] = None\n"
        "import ax_devil_rtsp\n"
        "from ax_devil_rtsp import RtspDataRetriever, check_environment\n"
        "from ax_devil_rtsp.cli import cli\n"
        "from ax_devil_rtsp.utils.deps import ensure_gi_ready\n"
        "assert not check_environment().ok\n"
        "try:\n"
        "    ensure_gi_ready()\n"
        "except RuntimeError as exc:\n"
        "    assert 'ax-devil-rtsp[gstreamer]' in str(exc), exc\n"
        "else:\n"
        "    raise AssertionError('ensure_gi_ready() did not raise')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
