from __future__ import annotations

import datetime as _dt
import json as _json
import logging as _logging
import logging.handlers as _handlers
import platform as _platform
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

# ────────────────────────────────────────────────────────────────────────────────
# Colour codes for console output (simplified ANSI)
# ────────────────────────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_COLORS: Mapping[str, str] = {
    "DEBUG": "\033[90m",  # grey
    "INFO": "\033[97m",  # white
    "WARNING": "\033[93m",  # yellow
    "ERROR": "\033[91m",  # red
    "CRITICAL": "\033[95m",  # magenta
}

# ────────────────────────────────────────────────────────────────────────────────
# Custom formatters
# ────────────────────────────────────────────────────────────────────────────────


class _ColorFormatter(_logging.Formatter):
    """Concise colourised formatter for interactive use."""

    def format(self, record: _logging.LogRecord) -> str:  # noqa: D401, N802
        color = _COLORS.get(record.levelname, "")
        time_str = _dt.datetime.fromtimestamp(
            record.created).strftime("%H:%M:%S.%f")[:-3]
        module_line = f"{record.module}:{record.lineno}"
        message = super().formatMessage(record)
        
        return f"{color}{time_str} | {record.levelname:<8} | [{record.process}] {module_line:<20} | {message}{_RESET}"


class _JsonFormatter(_logging.Formatter):
    """Minimal JSON formatter - dependency-free."""

    _BASE_KEYS = (
        "timestamp",
        "level",
        "logger",
        "file",
        "line",
        "func",
        "message",
    )

    def format(self, record: _logging.LogRecord) -> str:  # noqa: D401, N802
        payload: MutableMapping[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "file": record.pathname,
            "line": record.lineno,
            "func": record.funcName,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k not in self._BASE_KEYS and k not in (
                "msg",
                "args",
                "exc_info",
                "stack_info",
            ):
                payload[k] = v
        return _json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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


def _get_default_logs_dir() -> Path:
    """Return platform-appropriate cache directory for ax-devil-rtsp logs."""
    system = _platform.system()
    if system == "Windows":
        return Path.home() / "AppData" / "Local" / "ax-devil-rtsp"
    else:
        # Linux, macOS, and other Unix-like systems
        return Path.home() / ".cache" / "ax-devil-rtsp"


def setup_logging(
    *,
    log_level: str | int = "INFO",
    json_log_file: Optional[Path] = None,
    plain_log_file: Optional[Path] = None,
    max_file_size: int = 25 * 1024 * 1024,  # 25 MB
    backup_count: int = 10,
    logs_dir: Path | str | None = None,
    debug: bool = False,
) -> _logging.Logger:
    """Initialise root + ax-devil-rtsp loggers with JSON *and* plain-text files."""

    if debug:
        log_level = "DEBUG"
    numeric_level = _logging._nameToLevel.get(
        str(log_level).upper(), _logging.INFO)

    if logs_dir is None:
        logs_path = _get_default_logs_dir()
    else:
        logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    if json_log_file is None:
        json_log_file = logs_path / "ax-devil-rtsp_main.json"
    if plain_log_file is None:
        plain_log_file = logs_path / "ax-devil-rtsp_main.log"

    root = _logging.getLogger()
    root.handlers.clear()
    # capture everything; handlers decide display
    root.setLevel(_logging.DEBUG)

    # ─ JSON file handler ───────────────────────────────────────────────────────
    json_handler = _handlers.RotatingFileHandler(
        filename=json_log_file,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding="utf-8",
    )
    json_handler.setLevel(_logging.DEBUG)
    json_handler.setFormatter(_JsonFormatter())
    root.addHandler(json_handler)

    # ─ Plain-text file handler ────────────────────────────────────────────────
    plain_handler = _handlers.RotatingFileHandler(
        filename=plain_log_file,
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding="utf-8",
    )
    plain_handler.setLevel(_logging.DEBUG)
    plain_handler.setFormatter(_PlainFormatter())
    root.addHandler(plain_handler)

    # ─ Console handler ────────────────────────────────────────────────────────
    console_handler = _logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(_ColorFormatter())
    root.addHandler(console_handler)

    # Quiet noisy libs
    for noisy in ("urllib3", "botocore", "s3transfer"):
        _logging.getLogger(noisy).setLevel(_logging.WARNING)

    logger = get_logger("main")
    logger.info(
        "Logging initialized",
        extra={
            "console_level": _logging.getLevelName(numeric_level),
            "json_file": str(json_log_file),
            "plain_file": str(plain_log_file),
            "rotation_mb": max_file_size // (1024 * 1024),
            "backups": backup_count,
        },
    )
    return logger


def get_logger(name: str) -> _logging.Logger:  # noqa: D401
    """Return a logger within the ax-devil-rtsp namespace."""
    suffix = f".{name}" if name else ""
    return _logging.getLogger(f"ax-devil-rtsp{suffix}")


# ─ Convenience façade ──────────────────────────────────────────────────────────


def init_app_logging(*, debug: bool = False) -> _logging.Logger:  # noqa: D401
    """Initialise logging and return the main logger."""
    return setup_logging(debug=debug)
