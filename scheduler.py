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
    await safe_run("refresh_news", get_news_sentiment_all_holdings)


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


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    """Initialise services, register all 10 jobs, and run forever."""
    logger.info("Starting Portfolio Agent — Scheduler")

    redis = RedisClient(REDIS_URL)
    init_db()

    token = redis.get("kite:access_token")
    if not token:
        logger.warning("No Kite auth token found. Send auth link first.")

    scheduler = AsyncIOScheduler(timezone=IST)

    # ── 10-job schedule ───────────────────────────────────────────────────────
    scheduler.add_job(
        heartbeat_job,
        CronTrigger(hour=7, minute=0, timezone=IST),
        id="heartbeat", name="Daily Heartbeat",
    )
    scheduler.add_job(
        morning_briefing_job,
        CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone=IST),
        id="morning_briefing", name="Morning Briefing",
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
    )
    scheduler.add_job(
        signal_scan_afternoon_job,
        CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone=IST),
        id="signal_scan_afternoon", name="PM Signal Scan",
    )
    scheduler.add_job(
        opportunity_scan_job,
        CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone=IST),
        id="opportunity_scan", name="Opportunity Scanner",
    )
    scheduler.add_job(
        weekly_health_job,
        CronTrigger(hour=9, minute=0, day_of_week="sun", timezone=IST),
        id="weekly_health", name="Weekly Health Report",
    )
    scheduler.add_job(
        token_cleanup_job,
        CronTrigger(hour=0, minute=0, timezone=IST),
        id="token_cleanup", name="Midnight Token Cleanup",
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

    await asyncio.get_event_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
