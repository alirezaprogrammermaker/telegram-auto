"""Central logging configuration."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO", root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parent.parent
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Windows consoles often default to cp1252 and crash on Persian log text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_level = getattr(logging, level.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(log_level)
    root_logger.addHandler(console)

    file_handler = RotatingFileHandler(
        logs_dir / "app.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(log_level)
    root_logger.addHandler(file_handler)

    # Quiet noisy libraries a bit
    logging.getLogger("telethon").setLevel(logging.WARNING)
