"""
Entry point B — APScheduler process.
Runs all timed market jobs. Never import webhook_server here.
Run: python scheduler.py
"""
import asyncio
import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import REDIS_URL, TIMEZONE
from core.db import init_db
from core.redis_client import RedisClient
from core.telegram_bot import send_message
from core.approval import cleanup_expired_tokens

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

IST = pytz.timezone(TIMEZONE)


# ── Market guard ─────────────────────────────────────────────────────────────

def market_day_check() -> bool:
    """Return True only during NSE trading hours on a weekday."""
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


# ── Job stubs ─────────────────────────────────────────────────────────────────

async def briefing_job() -> None:
    """Morning briefing: portfolio overview + overnight news digest."""
    from agent.briefing import run_briefing
    result = await run_briefing()
    logger.info("briefing_job complete (success=%s)", result)


async def signal_job_am() -> None:
    """Mid-morning signal scan (11:00 AM IST)."""
    logger.info("signal_job_am triggered")


async def scanner_job() -> None:
    """Nifty 200 opportunity scanner (12:30 PM IST)."""
    logger.info("scanner_job triggered")


async def signal_job_pm() -> None:
    """Afternoon signal scan (2:00 PM IST)."""
    logger.info("signal_job_pm triggered")


async def post_market_job() -> None:
    """Post-market summary and portfolio snapshot (4:00 PM IST)."""
    logger.info("post_market_job triggered")


async def health_job() -> None:
    """Weekly system health report (Sunday 7:00 PM IST)."""
    logger.info("health_job triggered")


async def stoploss_job() -> None:
    """Stop-loss monitor — runs every 5 min, guarded to market hours."""
    from agent.stoploss import run_with_market_check
    results = await run_with_market_check()
    if results:
        logger.info("SL job complete: %s", results)


async def heartbeat_job() -> None:
    """Daily liveness ping at 07:00 IST Mon–Fri."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    await send_message(f"🤖 Portfolio Agent alive — {today}\nNext: Kite auth reminder at 8:00 AM")
    logger.info("heartbeat_job: ping sent")


async def token_cleanup_job() -> None:
    """Midnight cleanup — expire stale approval tokens."""
    count = cleanup_expired_tokens()
    logger.info("token_cleanup_job: %d expired tokens cleaned up", count)


async def refresh_technicals_job() -> None:
    """Refresh technical indicators cache every 60 min, guarded to market hours."""
    if not market_day_check():
        return
    from data.technicals import get_technicals_for_holdings
    results = get_technicals_for_holdings()
    logger.info("refresh_technicals_job: indicators refreshed for %d symbols", len(results))


async def refresh_news_job() -> None:
    """Refresh news sentiment cache every 120 min, guarded to market hours."""
    if not market_day_check():
        return
    from data.news import get_news_sentiment_all_holdings
    results = get_news_sentiment_all_holdings()
    logger.info("refresh_news_job: news sentiment refreshed for %d symbols", len(results))


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    """Initialise services, register all jobs, and run forever."""
    logger.info("Starting Portfolio Agent — Scheduler")

    redis = RedisClient(REDIS_URL)
    init_db()

    token = redis.get("kite:access_token")
    if not token:
        logger.warning("Warning: No Kite auth token found. Send auth link first.")

    scheduler = AsyncIOScheduler(timezone=IST)

    scheduler.add_job(
        briefing_job, CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone=IST),
        id="briefing_job", name="Morning Briefing",
    )
    scheduler.add_job(
        signal_job_am, CronTrigger(hour=11, minute=0, day_of_week="mon-fri", timezone=IST),
        id="signal_job_am", name="AM Signal Scan",
    )
    scheduler.add_job(
        scanner_job, CronTrigger(hour=12, minute=30, day_of_week="mon-fri", timezone=IST),
        id="scanner_job", name="Nifty200 Scanner",
    )
    scheduler.add_job(
        signal_job_pm, CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone=IST),
        id="signal_job_pm", name="PM Signal Scan",
    )
    scheduler.add_job(
        post_market_job, CronTrigger(hour=16, minute=0, day_of_week="mon-fri", timezone=IST),
        id="post_market_job", name="Post-Market Summary",
    )
    scheduler.add_job(
        health_job, CronTrigger(hour=19, minute=0, day_of_week="sun", timezone=IST),
        id="health_job", name="Weekly Health Report",
    )
    scheduler.add_job(
        stoploss_job, "interval", minutes=5,
        id="stoploss_job", name="SL Monitor (5min)",
    )
    scheduler.add_job(
        heartbeat_job, CronTrigger(hour=7, minute=0, day_of_week="mon-fri", timezone=IST),
        id="heartbeat_job", name="Daily Heartbeat",
    )
    scheduler.add_job(
        token_cleanup_job, CronTrigger(hour=0, minute=0, timezone=IST),
        id="token_cleanup_job", name="Midnight Token Cleanup",
    )
    scheduler.add_job(
        refresh_technicals_job, "interval", minutes=60,
        id="refresh_technicals_job", name="Technicals Refresh (60min)",
    )
    scheduler.add_job(
        refresh_news_job, "interval", minutes=120,
        id="refresh_news_job", name="News Refresh (120min)",
    )

    scheduler.start()
    logger.info("Scheduler ready — %d jobs registered:", len(scheduler.get_jobs()))

    for job in scheduler.get_jobs():
        next_run = job.next_run_time.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %Z") if job.next_run_time else "N/A"
        logger.info("  %-28s  next: %s", job.name, next_run)

    # Startup SL check — runs immediately regardless of market hours for boot-time validation
    logger.info("Running startup SL check...")
    from agent.stoploss import run_sl_monitor
    startup_results = await run_sl_monitor()
    logger.info("Startup SL check complete: %s", startup_results)

    await asyncio.get_event_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
