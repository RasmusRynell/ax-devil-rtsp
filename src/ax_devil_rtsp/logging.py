from __future__ import annotations

import datetime as _dt
import logging as _logging
import logging.handlers as _handlers
from pathlib import Path
from typing import Any, Iterable, Optional

# ────────────────────────────────────────────────────────────────────────────────
# Custom formatters
# ────────────────────────────────────────────────────────────────────────────────


class _PlainFormatter(_logging.Formatter):
    """Human-readable file formatter with millisecond precision."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | [%(process)d:%(thread)d] | %(name)s | %(module)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",  # base - milliseconds injected by formatTime
        )

    # override to append .mmm (milliseconds)
    def formatTime(self, record: _logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        dt = _dt.datetime.fromtimestamp(record.created)
        base = dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")
        return f"{base}.{dt.microsecond // 1000:03d}"


# ────────────────────────────────────────────────────────────────────────────────
# Public API - configuration helpers
# ────────────────────────────────────────────────────────────────────────────────


def _parse_level(log_level: int | str) -> int:
    if isinstance(log_level, str):
        return int(_logging._checkLevel(log_level.upper()))
    if isinstance(log_level, int):
        return log_level
    raise TypeError(
        f"log_level must be an int or str matching logging levels; got {log_level!r} "
        f"({type(log_level).__name__})"
    )


def _get_default_logs_dir() -> Path:
    """Return default directory for ax-devil-rtsp logs."""
    return Path.home() / ".ax_devil" / "logs" / "ax-devil-rtsp"


def setup_logging(
    *,
    log_level: int | str = _logging.INFO,
    log_file: Optional[Path | str] = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    logs_dir: Path | str | None = None,
    debug: bool = False,
    console: bool = True,
    log_to_file: bool = True,
    propagate: bool = False,
    queue_only: bool = False,
    log_queue: Any | None = None,
) -> _logging.Logger:
    """
    Configure the ax-devil-rtsp logger (not the root logger).

    - Console: colour, millisecond timestamps, level = log_level
    - File: rotating plain-text at DEBUG level
    - Optional queue-only mode for subprocesses
    """

    numeric_level = _logging.DEBUG if debug else _parse_level(log_level)

    logger = get_logger("")
    logger.setLevel(numeric_level)
    logger.propagate = propagate

    # Clean up previous handlers/listeners we own
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    handlers: list[_logging.Handler] = []
    plain_path: Path | None = None

    if queue_only:
        if log_queue is None:
            raise ValueError("queue_only=True requires a log_queue")
        queue_handler = _handlers.QueueHandler(log_queue)
        queue_handler.setLevel(numeric_level)
        handlers.append(queue_handler)
    else:
        logs_path = Path(logs_dir) if logs_dir is not None else _get_default_logs_dir()
        if log_to_file:
            logs_path.mkdir(parents=True, exist_ok=True)
            if log_file is not None:
                plain_path = Path(log_file)
                plain_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                plain_path = logs_path / "ax-devil-rtsp.log"
            plain_handler = _handlers.RotatingFileHandler(
                filename=plain_path,
                maxBytes=max_file_size,
                backupCount=backup_count,
                encoding="utf-8",
                delay=True,
            )
            plain_handler.setLevel(_logging.DEBUG)
            plain_handler.setFormatter(_PlainFormatter())
            handlers.append(plain_handler)

        if console:
            console_handler = _logging.StreamHandler()
            console_handler.setLevel(numeric_level)
            console_handler.setFormatter(_PlainFormatter())
            handlers.append(console_handler)

    for handler in handlers:
        logger.addHandler(handler)

    # Quiet noisy libs without touching root
    for noisy in ("urllib3", "botocore", "s3transfer"):
        _logging.getLogger(noisy).setLevel(_logging.WARNING)

    if not queue_only:
        logger.info(
            "Logging initialized",
            extra={
                "console_level": _logging.getLevelName(numeric_level),
                "log_file": str(plain_path) if plain_path else None,
                "rotation_mb": max_file_size // (1024 * 1024),
                "backups": backup_count,
            },
        )
    return logger


def get_logger(name: str) -> _logging.Logger:  # noqa: D401
    """Return a logger within the ax-devil-rtsp namespace."""
    suffix = f".{name}" if name else ""
    return _logging.getLogger(f"ax-devil-rtsp{suffix}")


def create_queue_listener(
    log_queue: Any, handlers: Iterable[_logging.Handler] | None = None
) -> _handlers.QueueListener | None:
    """Create a QueueListener using existing ax-devil-rtsp handlers."""
    target_handlers = list(handlers) if handlers is not None else [
        h for h in get_logger("").handlers if not isinstance(h, _handlers.QueueHandler)
    ]
    if not target_handlers:
        return None
    return _handlers.QueueListener(
        log_queue, *target_handlers, respect_handler_level=True
    )


# ─ Convenience façade ──────────────────────────────────────────────────────────


def init_app_logging(
    *,
    log_level: int | str = _logging.INFO,
    debug: bool = False,
    **kwargs: Any,
) -> _logging.Logger:  # noqa: D401
    """Initialise logging and return the main logger."""
    return setup_logging(log_level=log_level, debug=debug, **kwargs)
