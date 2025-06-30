"""
Entry point for running the CLI as a module.

This allows running the CLI with: python -m ax_devil_rtsp.cli
"""

from .main import cli

if __name__ == "__main__":
    cli() 