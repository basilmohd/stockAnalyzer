"""
Global exception handler — safe_run() wraps any job function in try/except,
logs errors, sends a non-blocking Telegram alert, and returns None on failure.
"""
import asyncio
import logging
import traceback
from datetime import datetime

import pytz

from config import TIMEZONE

logger = logging.getLogger(__name__)
IST = pytz.timezone(TIMEZONE)


async def safe_run(job_name: str, fn, *args, **kwargs):
    """Run *fn* safely, catching all exceptions without re-raising.

    Awaits *fn* if it is a coroutine function, otherwise calls it synchronously.
    On success logs a completion line and returns the result.
    On failure logs the full traceback, fires a Telegram alert (non-blocking),
    and returns None.
    """
    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
        logger.info("[%s] completed successfully", job_name)
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[%s] FAILED — %s\n%s", job_name, exc, tb)
        _send_error_alert(job_name, exc)
        return None


def _send_error_alert(job_name: str, exc: Exception) -> None:
    """Send a Telegram alert for a job failure — non-blocking, never raises."""
    try:
        from core.telegram_bot import send_message
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        text = (
            f"⚠️ *System Alert*\n"
            f"Job: {job_name}\n"
            f"Error: {type(exc).__name__}: {str(exc)[:100]}\n"
            f"Time: {ts}"
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_message(text))
        except RuntimeError:
            asyncio.run(send_message(text))
    except Exception as alert_exc:
        logger.warning("Failed to send error alert for [%s]: %s", job_name, alert_exc)
