import logging

import pytest

from ax_devil_rtsp.logging import setup_logging


def test_setup_logging_respects_numeric_log_level(tmp_path):
    root_logger = logging.getLogger()
    prev_handlers = list(root_logger.handlers)
    prev_level = root_logger.level

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    try:
        setup_logging(
            log_level=logging.DEBUG,
            logs_dir=logs_dir,
        )

        console_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.StreamHandler)
        ]

        assert console_handlers, "console handler should be configured"
        assert {handler.level for handler in console_handlers} == {logging.DEBUG}
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers = prev_handlers
        root_logger.setLevel(prev_level)


def test_setup_logging_rejects_string_log_level(tmp_path):
    with pytest.raises(TypeError):
        setup_logging(log_level="DEBUG", logs_dir=tmp_path)
