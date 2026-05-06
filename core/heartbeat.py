"""
Daily heartbeat — sends a morning system status message to Telegram at 07:00 IST.
"""
import logging
from datetime import datetime

import pytz

from config import REDIS_URL, TIMEZONE, USE_MOCK_KITE
from core.redis_client import RedisClient
from core.telegram_bot import send_message

logger = logging.getLogger(__name__)
IST = pytz.timezone(TIMEZONE)
_redis = RedisClient(REDIS_URL)


def _redis_status() -> str:
    """Return a formatted status string for Redis connectivity."""
    return "✅ Redis: UP" if _redis.ping() else "❌ Redis: DOWN"


def _db_status() -> str:
    """Return a formatted status string for the SQLite database."""
    try:
        import sqlalchemy
        from core.db import get_db
        with get_db() as db:
            db.execute(sqlalchemy.text("SELECT 1"))
        return "✅ Database: UP"
    except Exception:
        return "❌ Database: DOWN"


def _kite_auth_status() -> str:
    """Return a formatted Kite auth status line for the heartbeat message."""
    if USE_MOCK_KITE:
        return "🔵 Kite: MOCK mode"
    token = _redis.get("kite:access_token")
    if token:
        return "✅ Kite: Authenticated"
    return "⚠️ Kite: TOKEN MISSING — re-auth required"


def _is_market_day() -> bool:
    """Return True if today is a weekday (NSE trading day)."""
    return datetime.now(IST).weekday() < 5


async def send_heartbeat() -> None:
    """Collect system status and send a morning heartbeat message to Telegram."""
    now = datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d %A")
    market_status = "OPEN" if _is_market_day() else "CLOSED"

    redis_line = _redis_status()
    db_line = _db_status()
    kite_line = _kite_auth_status()

    last_sl = _redis.get("sl_monitor:last_run") or "Not run yet"
    last_briefing = _redis.get("briefing:latest") or "Pending"

    auth_reminder = ""
    if not USE_MOCK_KITE and not _redis.get("kite:access_token"):
        auth_reminder = (
            "\n"
            "🔐 <b>Action required:</b> Kite token expired.\n"
            '<a href="http://127.0.0.1:8000/kite/login">Tap here to re-authenticate</a>\n'
            "(Briefing and SL monitor will fail without this)\n"
        )

    text = (
        f"🤖 <b>Portfolio Agent — Daily Heartbeat</b>\n"
        f"{date_str} | Market: {market_status} today\n"
        f"\n"
        f"System Status:\n"
        f"{redis_line}\n"
        f"{db_line}\n"
        f"{kite_line}\n"
        f"{auth_reminder}"
        f"\n"
        f"Last SL Check: {last_sl}\n"
        f"Last Briefing: {last_briefing}\n"
        f"\n"
        f"Jobs scheduled today:\n"
        f"• 08:30 — Morning Briefing\n"
        f"• 09:15 — SL Monitor starts\n"
        f"• 11:00 — Signal Scan\n"
        f"• 14:00 — Signal Scan"
    )
    await send_message(text)
    logger.info(
        "Heartbeat sent — date=%s market=%s kite_authed=%s",
        date_str, market_status, bool(_redis.get("kite:access_token")),
    )
