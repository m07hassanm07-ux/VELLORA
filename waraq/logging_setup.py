"""Local, size-bounded diagnostic logging without document contents."""
from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import os
import sys


def data_directory() -> Path:
    override = os.environ.get("WARAQ_DATA_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Waraqa"


def configure_logging() -> Path:
    folder = data_directory() / "logs"; folder.mkdir(parents=True, exist_ok=True)
    path = folder / "waraqa.log"
    logger = logging.getLogger("waraqa")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler); logger.propagate = False
    previous = sys.excepthook
    def unhandled(kind, value, trace):
        logger.critical("Unhandled application error", exc_info=(kind, value, trace))
        previous(kind, value, trace)
    sys.excepthook = unhandled
    logger.info("Waraqa started")
    return path
