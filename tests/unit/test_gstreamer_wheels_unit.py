"""Unit tests for loading GStreamer from the pip wheels (gstreamer-meta)."""

import sys
import types

import pytest

from ax_devil_rtsp.utils import deps


@pytest.fixture(autouse=True)
def reset_wheels_flag(monkeypatch):
    monkeypatch.setattr(deps, "_gstreamer_wheels_ready", False)


def test_use_gstreamer_wheels_without_wheels(monkeypatch):
    monkeypatch.setitem(sys.modules, "gstreamer_libs", None)
    assert deps.use_gstreamer_wheels() is False


def test_use_gstreamer_wheels_sets_up_environment_once(monkeypatch):
    calls = []
    fake = types.ModuleType("gstreamer_libs")
    fake.setup_python_environment = lambda: calls.append(1)
    monkeypatch.setitem(sys.modules, "gstreamer_libs", fake)

    assert deps.use_gstreamer_wheels() is True
    assert deps.use_gstreamer_wheels() is True
    assert calls == [1]
