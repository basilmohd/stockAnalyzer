"""
Global exception handler — safe_run() wraps any job function in try/except,
logs the FULL traceback (prefixed with the job name), mirrors WARNING+ from every
logger into logs/errors.log, sends a non-blocking Telegram alert, and returns
None on failure.

logs/errors.log is the single place to look when a job fails silently: a job that
writes DB rows but then dies before sending Telegram (the "11 PENDING but no
alert" class of bug) always leaves a visible trace there.
"""
import asyncio
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

import pytz

from config import LOG_BACKUP_COUNT, TIMEZONE

IST = pytz.timezone(TIMEZONE)

_LOG_DIR = "logs"
_ERRORS_LOG = os.path.join(_LOG_DIR, "errors.log")
_ERRORS_FMT = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
_ERRORS_MAX_BYTES = 5_000_000  # 5 MB per file before rotation


def _install_errors_handler() -> None:
    """Attach one RotatingFileHandler to the ROOT logger capturing WARNING+ from
    every logger into logs/errors.log.

    All module loggers (get_logger / logging.getLogger) propagate to root, so this
    single handler is the aggregate failure trail. Idempotent — safe to call on
    every import.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_portfolio_errors_handler", False):
            return

    os.makedirs(_LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        _ERRORS_LOG,
        maxBytes=_ERRORS_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(_ERRORS_FMT)
    handler._portfolio_errors_handler = True  # marker so we never double-install
    root.addHandler(handler)

    # Root must let WARNING+ records reach the handler (NOTSET would default to
    # WARNING already, but be explicit and never silently raise it higher).
    if root.level == logging.NOTSET or root.level > logging.WARNING:
        root.setLevel(logging.WARNING)


# Install on import so the aggregate trail is live for the whole process.
_install_errors_handler()

from core.logger import get_logger  # noqa: E402 — import after handler install

logger = get_logger(__name__)


async def safe_run(job_name: str, fn, *args, **kwargs):
    """Run *fn* safely, catching all exceptions without re-raising.

    Awaits *fn* if it is a coroutine function, otherwise calls it synchronously.
    On success logs ``[job_name] completed OK`` at INFO and returns the result.
    On failure logs the FULL traceback at ERROR (which propagates to
    logs/errors.log), fires a Telegram alert with the exception type + first 200
    chars of the message (non-blocking), and returns None.
    """
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
        logger.info("[%s] completed OK", job_name)
        return result
    except Exception as exc:
        # logger.exception logs at ERROR with the full traceback attached; because
        # this logger propagates to the root errors.log handler, the failure is
        # ALWAYS recorded in logs/errors.log regardless of which module raised.
        logger.exception("[%s] FAILED — %s: %s", job_name, type(exc).__name__, exc)
        _send_error_alert(job_name, exc)
        return None


def _send_error_alert(job_name: str, exc: Exception) -> None:
    """Send a Telegram alert for a job failure — non-blocking, never raises.

    The alert carries the exception TYPE and the first 200 chars of its message.
    """
    try:
        from core.telegram_bot import send_message
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        text = (
            f"⚠️ *System Alert*\n"
            f"Job: {job_name}\n"
            f"Error: {type(exc).__name__}: {str(exc)[:200]}\n"
            f"Time: {ts}"
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_message(text))
        except RuntimeError:
            asyncio.run(send_message(text))
    except Exception as alert_exc:
        logger.warning("Failed to send error alert for [%s]: %s", job_name, alert_exc)
