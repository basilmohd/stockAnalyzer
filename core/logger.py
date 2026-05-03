"""
Centralized logger factory — returns a named logger with rotating file +
console handlers. Import and call get_logger(__name__) in every module.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = "logs"
_FMT = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with a midnight-rotating file handler and a stream handler.

    Safe to call multiple times for the same name — handlers are added once.
    Log files are written to logs/{name}.log with 7-day rotation.
    """
    from config import LOG_BACKUP_COUNT, LOG_LEVEL, LOG_ROTATION

    log = logging.getLogger(name)
    if log.handlers:
        return log

    log.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    os.makedirs(_LOG_DIR, exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(_LOG_DIR, f"{name}.log"),
        when=LOG_ROTATION,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(_FMT)
    log.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(_FMT)
    log.addHandler(sh)

    return log
