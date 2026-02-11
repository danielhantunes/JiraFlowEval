"""Structured logging for the evaluator. Log per-repo errors; continue on failure."""

import logging
import sys
from typing import Optional


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """Return a configured logger. Default level INFO."""
    log = logging.getLogger(name)
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        log.addHandler(handler)
        log.setLevel(level or logging.INFO)
    return log


def log_repo_error(log: logging.Logger, repo_url: str, phase: str, message: str) -> None:
    """Log an error for a specific repo and phase; evaluation continues."""
    log.error("repo=%s phase=%s error=%s", repo_url, phase, message)
