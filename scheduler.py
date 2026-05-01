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

from config import REDIS_URL, TIMEZONE
from core.db import init_db
from core.redis_client import RedisClient

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
    logger.info("briefing_job triggered")


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
    if not market_day_check():
        return
    logger.info("stoploss_job triggered")


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

    scheduler.add_job(briefing_job,    "cron", hour=8,  minute=30, day_of_week="mon-fri")
    scheduler.add_job(signal_job_am,   "cron", hour=11, minute=0,  day_of_week="mon-fri")
    scheduler.add_job(scanner_job,     "cron", hour=12, minute=30, day_of_week="mon-fri")
    scheduler.add_job(signal_job_pm,   "cron", hour=14, minute=0,  day_of_week="mon-fri")
    scheduler.add_job(post_market_job, "cron", hour=16, minute=0,  day_of_week="mon-fri")
    scheduler.add_job(health_job,      "cron", hour=19, minute=0,  day_of_week="sun")
    scheduler.add_job(stoploss_job,    "interval", minutes=5)

    scheduler.start()
    logger.info("Scheduler ready. All jobs registered.")

    for job in scheduler.get_jobs():
        logger.info("  %-22s  next run: %s", job.name, job.next_run_time)

    await asyncio.get_event_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
