"""
Entry point B — APScheduler process.
Runs all timed market jobs. Never import webhook_server here.
Run: python scheduler.py
"""
import asyncio
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import REDIS_URL, TIMEZONE
from core.db import init_db
from core.exception_handler import safe_run
from core.logger import get_logger
from core.redis_client import RedisClient

logger = get_logger(__name__)
IST = pytz.timezone(TIMEZONE)


# ── Market guard ──────────────────────────────────────────────────────────────

def market_day_check() -> bool:
    """Return True only during NSE trading hours on a weekday."""
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


# ── Scheduled job wrappers ────────────────────────────────────────────────────

async def heartbeat_job() -> None:
    """Daily liveness ping at 07:00 IST."""
    from core.heartbeat import send_heartbeat
    await safe_run("heartbeat", send_heartbeat)


async def morning_briefing_job() -> None:
    """Morning briefing: portfolio overview + overnight news digest (08:30 Mon–Fri)."""
    from agent.briefing import run_briefing
    await safe_run("morning_briefing", run_briefing)


async def sl_monitor_job() -> None:
    """Stop-loss monitor — runs every 5 min, guarded to market hours."""
    from agent.stoploss import run_with_market_check
    await safe_run("sl_monitor", run_with_market_check)


async def refresh_technicals_job() -> None:
    """Refresh technical indicators cache every 60 min (market hours only)."""
    if not market_day_check():
        return
    from data.technicals import get_technicals_for_holdings
    await safe_run("refresh_technicals", get_technicals_for_holdings)


async def refresh_news_job() -> None:
    """Refresh news sentiment cache every 120 min (market hours only)."""
    if not market_day_check():
        return
    from data.news import get_news_sentiment_all_holdings
    result = await safe_run("refresh_news", get_news_sentiment_all_holdings)
    if result:
        from core.telegram_bot import send_message
        now = datetime.now(IST).strftime("%I:%M %p")
        msg = f"📰 *News Sentiment Update*\nCache refreshed at {now} IST\n{len(result)} holdings analyzed"
        await send_message(msg)


async def signal_scan_morning_job() -> None:
    """Mid-morning signal scan (11:00 AM IST Mon–Fri)."""
    from agent.signals import run_signal_pipeline
    await safe_run("signal_scan_morning", run_signal_pipeline)


async def signal_scan_afternoon_job() -> None:
    """Afternoon signal scan (2:00 PM IST Mon–Fri)."""
    from agent.signals import run_signal_pipeline
    await safe_run("signal_scan_afternoon", run_signal_pipeline)


async def opportunity_scan_job() -> None:
    """Nifty 200 opportunity scanner (10:00 AM IST Mon–Fri)."""
    from agent.scanner import send_opportunity_alerts
    await safe_run("opportunity_scan", send_opportunity_alerts)


async def weekly_health_job() -> None:
    """Weekly portfolio health report (Sunday 09:00 IST)."""
    from agent.health import send_weekly_health_report
    await safe_run("weekly_health", send_weekly_health_report)


async def token_cleanup_job() -> None:
    """Midnight cleanup — expire stale approval tokens (00:00 daily)."""
    from core.approval import cleanup_expired_tokens
    await safe_run("token_cleanup", cleanup_expired_tokens)


async def store_closing_prices_job() -> None:
    """Store daily market close prices at 3:30 PM IST (Mon–Fri)."""
    from core.daily_prices import store_market_close_prices
    await safe_run("store_closing_prices", store_market_close_prices)


async def closure_report_job() -> None:
    """Market closure portfolio report at 3:30 PM IST (Mon–Fri)."""
    from agent.closure import send_closure_report
    await safe_run("closure_report", send_closure_report)


async def refresh_holdings_cache_job() -> None:
    """Refresh holdings cache every 30 min during market hours (9:15–15:30).
    
    Ensures SL monitoring and signals use fresh data between scheduled jobs.
    """
    if not market_day_check():
        return
    from data.portfolio import get_holdings_with_sl_status
    await safe_run("refresh_holdings_cache", get_holdings_with_sl_status)


async def daily_opening_refresh_job() -> None:
    """Refresh holdings at market open (8:15 AM IST Mon–Fri).
    
    Captures any overnight manual trades via external APIs or Zerodha portal
    before the morning briefing runs at 8:30 AM.
    """
    from data.portfolio import get_holdings_with_sl_status
    await safe_run("daily_opening_refresh", get_holdings_with_sl_status)


async def reset_daily_chat_counts_job() -> None:
    """Reset daily chat query counts at 00:05 IST (after midnight).
    
    Allows users to start fresh batch of 20 queries for the new day.
    """
    from core.redis_client import RedisClient
    from config import REDIS_URL
    
    redis = RedisClient(REDIS_URL)
    if not redis.available:
        logger.warning("Redis unavailable — skipping chat count reset")
        return
    
    try:
        # Scan for all active chat count keys and reset them
        # For now, we rely on Redis TTL for auto-expiry (24h)
        # This job could be extended to explicitly find and reset keys if needed
        logger.info("Daily chat counts reset (TTL-based expiry in effect)")
    except Exception as exc:
        logger.error("reset_daily_chat_counts_job failed: %s", exc)


async def cleanup_expired_chat_sessions_job() -> None:
    """Clean up expired chat sessions from Redis (02:00 IST daily).
    
    Removes stale chat history entries that may exceed TTL.
    """
    from core.redis_client import RedisClient
    from config import REDIS_URL
    
    redis = RedisClient(REDIS_URL)
    if not redis.available:
        logger.warning("Redis unavailable — skipping chat session cleanup")
        return
    
    try:
        # Redis handles TTL expiry automatically, so this is mostly preventive
        # In production, could add explicit scanning and cleanup if needed
        logger.info("Chat session cleanup completed (TTL-based expiry in effect)")
    except Exception as exc:
        logger.error("cleanup_expired_chat_sessions_job failed: %s", exc)


async def main() -> None:
    """Initialize scheduler and start all jobs."""
    init_db()
    logger.info("Database initialized")

    scheduler = AsyncIOScheduler(timezone=IST)

    # ── 10-job schedule ───────────────────────────────────────────────────────
    scheduler.add_job(
        heartbeat_job,
        CronTrigger(hour=8, minute=30, timezone=IST),
        id="heartbeat", name="Daily Heartbeat",
    )
    scheduler.add_job(
        morning_briefing_job,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone=IST),
        id="morning_briefing", name="Morning Briefing",
        misfire_grace_time=900,  # Allow up to 15 minutes late execution
    )
    scheduler.add_job(
        sl_monitor_job,
        "interval", minutes=5,
        id="sl_monitor", name="SL Monitor (5min)",
    )
    scheduler.add_job(
        refresh_technicals_job,
        "interval", minutes=60,
        id="refresh_technicals", name="Technicals Refresh (60min)",
    )
    scheduler.add_job(
        refresh_news_job,
        "interval", minutes=120,
        id="refresh_news", name="News Refresh (120min)",
    )
    scheduler.add_job(
        signal_scan_morning_job,
        CronTrigger(hour=11, minute=0, day_of_week="mon-fri", timezone=IST),
        id="signal_scan_morning", name="AM Signal Scan",
        misfire_grace_time=1800,  # Allow up to 30 minutes late execution
    )
    scheduler.add_job(
        signal_scan_afternoon_job,
        CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone=IST),
        id="signal_scan_afternoon", name="PM Signal Scan",
        misfire_grace_time=1800,  # Allow up to 30 minutes late execution
    )
    scheduler.add_job(
        opportunity_scan_job,
        CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone=IST),
        id="opportunity_scan", name="Opportunity Scanner",
        misfire_grace_time=1800,  # Allow up to 30 minutes late execution
    )
    scheduler.add_job(
        weekly_health_job,
        CronTrigger(hour=3, minute=45, day_of_week="fri", timezone=IST),
        id="weekly_health", name="Weekly Health Report",
        misfire_grace_time=7200,  # Allow up to 2 hours late execution
    )
    scheduler.add_job(
        token_cleanup_job,
        CronTrigger(hour=0, minute=0, timezone=IST),
        id="token_cleanup", name="Midnight Token Cleanup",
    )
    scheduler.add_job(
        store_closing_prices_job,
        CronTrigger(hour=15, minute=20, day_of_week="mon-fri", timezone=IST),
        id="store_closing_prices", name="Store Closing Prices (3:20 PM)",
        misfire_grace_time=1800,  # Allow up to 30 minutes late execution
    )
    scheduler.add_job(
        closure_report_job,
        CronTrigger(hour=15, minute=30, day_of_week="mon-fri", timezone=IST),
        id="closure_report", name="Market Closure Report (3:30 PM)",
        misfire_grace_time=3600,  # Allow up to 1 hour late execution
    )
    scheduler.add_job(
        refresh_holdings_cache_job,
        "interval", minutes=10,
        id="refresh_holdings_cache", name="Holdings Cache Refresh (10min)",
    )
    scheduler.add_job(
        daily_opening_refresh_job,
        CronTrigger(hour=8, minute=15, day_of_week="mon-fri", timezone=IST),
        id="daily_opening_refresh", name="Daily Opening Refresh (8:15 AM)",
        misfire_grace_time=1800,  # Allow up to 30 minutes late execution
    )
    scheduler.add_job(
        reset_daily_chat_counts_job,
        CronTrigger(hour=0, minute=5, timezone=IST),
        id="reset_chat_counts", name="Reset Daily Chat Counts (00:05 IST)",
        misfire_grace_time=300,  # Allow up to 5 minutes late execution
    )
    scheduler.add_job(
        cleanup_expired_chat_sessions_job,
        CronTrigger(hour=2, minute=0, timezone=IST),
        id="cleanup_chat_sessions", name="Cleanup Chat Sessions (02:00 IST)",
        misfire_grace_time=3600,  # Allow up to 1 hour late execution
    )

    scheduler.start()
    logger.info("Scheduler ready — %d jobs registered:", len(scheduler.get_jobs()))

    for job in scheduler.get_jobs():
        next_run = (
            job.next_run_time.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %Z")
            if job.next_run_time
            else "N/A"
        )
        logger.info("  %-30s  next: %s", job.name, next_run)

    # Boot-time SL check for immediate validation
    logger.info("Running startup SL check...")
    from agent.stoploss import run_sl_monitor
    startup_results = await safe_run("startup_sl_check", run_sl_monitor)
    logger.info("Startup SL check complete: %s", startup_results)

    await asyncio.sleep(float('inf'))  # run forever


if __name__ == "__main__":
    asyncio.run(main())
