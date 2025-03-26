"""Simple logging configuration for ax-devil-rtsp."""
import logging
import sys

def configure_logging(level=logging.INFO):
    """Configure logging with a consistent format across the project.
    
    Args:
        level: The logging level to use. Defaults to INFO.
    """
    # Create a consistent format for all loggers
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Create our module's logger
    return logging.getLogger("ax-devil-rtsp") 