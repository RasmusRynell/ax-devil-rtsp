import logging
import logging.handlers as log_handlers
import multiprocessing as mp

import pytest

from ax_devil_rtsp.logging import setup_logging


def _cleanup(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_setup_logging_accepts_string_level(tmp_path):
    logger = setup_logging(log_level="DEBUG", logs_dir=tmp_path, log_to_file=False)
    try:
        assert logger.getEffectiveLevel() == logging.DEBUG
        console_handlers = [
            handler for handler in logger.handlers if isinstance(handler, logging.StreamHandler)
        ]
        assert console_handlers
        assert {handler.level for handler in console_handlers} == {logging.DEBUG}
    finally:
        _cleanup(logger)


def test_setup_logging_creates_expected_files(tmp_path):
    logger = setup_logging(log_level=logging.INFO, logs_dir=tmp_path)
    try:
        assert (tmp_path / "ax-devil-rtsp.log").exists()
    finally:
        _cleanup(logger)


def test_queue_only_sets_queue_handler(tmp_path):
    log_queue = mp.Queue()
    logger = setup_logging(
        log_level=logging.INFO,
        logs_dir=tmp_path,
        queue_only=True,
        log_queue=log_queue,
        log_to_file=False,
        console=False,
    )
    try:
        assert logger.handlers
        assert all(isinstance(h, log_handlers.QueueHandler) for h in logger.handlers)
    finally:
        _cleanup(logger)
        log_queue.close()


def test_setup_logging_creates_parent_for_custom_log_file(tmp_path):
    custom_log = tmp_path / "nested" / "deep" / "custom.log"
    logger = setup_logging(
        log_level="INFO",
        log_file=custom_log,
        log_to_file=True,
        console=False,
    )
    try:
        logger.info("hello")
        for handler in logger.handlers:
            handler.flush()
        assert custom_log.exists()
    finally:
        _cleanup(logger)
