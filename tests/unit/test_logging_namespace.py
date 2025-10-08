"""Tests for the logging namespace and defaults."""

from __future__ import annotations

import logging

from ax_devil_rtsp.logging import get_logger, setup_logging


def test_logging_namespace_and_defaults(tmp_path, caplog) -> None:
    """`get_logger` should use the ax-devil-rtsp namespace and defaults."""

    caplog.set_level(logging.INFO)

    logger = setup_logging(logs_dir=tmp_path)

    assert logger.name == "ax-devil-rtsp.main"

    child_logger = get_logger("example")
    child_logger.info("namespace check")

    assert child_logger.name == "ax-devil-rtsp.example"

    assert (tmp_path / "ax-devil-rtsp_main.log").exists()
    assert (tmp_path / "ax-devil-rtsp_main.json").exists()

    # Close handlers created during setup to avoid interfering with other tests
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.close()
    root_logger.handlers.clear()
