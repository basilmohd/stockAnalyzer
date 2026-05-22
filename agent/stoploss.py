"""
Stop-loss monitor — pure rule-based logic, no Claude API.
Called by APScheduler every 5 minutes during market hours.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DEFAULT_SL_PCT, SL_OVERRIDES, SL_COOLDOWN_MINS, TIMEZONE
from core.kite_client import KiteClient
from core.redis_client import RedisClient
from core.telegram_bot import send_sl_breach_alert
from core.approval import generate_token
from data.portfolio import get_holdings_with_sl_status
from config import REDIS_URL, MARKET_OPEN, MARKET_CLOSE

IST = ZoneInfo(TIMEZONE)
from core.logger import get_logger
logger = get_logger(__name__)

_redis = RedisClient(REDIS_URL)


@dataclass
class SLBreachAlert:
    """Represents a single stop-loss breach or warning for a holding."""
    symbol: str
    entry_price: float
    current_price: float
    pnl_pct: float
    quantity: int
    sl_threshold_pct: float
    sl_price: float
    severity: str  # "BREACH" or "WARNING"


def get_sl_threshold(symbol: str) -> float:
    """Return the SL threshold for *symbol*, using per-stock override if configured."""
    return SL_OVERRIDES.get(symbol, DEFAULT_SL_PCT)


def check_holdings_for_sl() -> list[SLBreachAlert]:
    """
    Fetch holdings and return a list of SLBreachAlerts for any breach or near-SL position.

    Severity rules:
      BREACH  — pnl_pct <= threshold
      WARNING — pnl_pct <= threshold + 3  (within 3 percentage points of SL)
    Results are sorted worst-first (ascending pnl_pct).
    
    Skips holdings with zero average_price to avoid division by zero.
    """
    holdings = get_holdings_with_sl_status()
    alerts: list[SLBreachAlert] = []

    for h in holdings:
        symbol: str = h["tradingsymbol"]
        avg: float = h["average_price"]
        lp: float = h["last_price"]
        qty: int = h["quantity"]

        # Skip stocks with zero average price (migrated from other brokers)
        if avg <= 0:
            logger.debug(f"Skipping SL check for {symbol}: average_price is {avg}")
            continue

        threshold = get_sl_threshold(symbol)
        sl_price = round(avg * (1 + threshold / 100), 2)
        pnl_pct = ((lp - avg) / avg) * 100

        if pnl_pct <= threshold:
            severity = "BREACH"
        elif pnl_pct <= threshold + 3:
            severity = "WARNING"
        else:
            continue

        alerts.append(SLBreachAlert(
            symbol=symbol,
            entry_price=avg,
            current_price=lp,
            pnl_pct=round(pnl_pct, 2),
            quantity=qty,
            sl_threshold_pct=threshold,
            sl_price=sl_price,
            severity=severity,
        ))

    return sorted(alerts, key=lambda a: a.pnl_pct)


def is_on_cooldown(symbol: str) -> bool:
    """Return True if an SL alert was already sent for *symbol* within the cooldown window."""
    return _redis.get(f"sl:alerted:{symbol}") is not None


def set_cooldown(symbol: str) -> None:
    """Set a cooldown key for *symbol* so it is not re-alerted within SL_COOLDOWN_MINS."""
    _redis.setex(f"sl:alerted:{symbol}", SL_COOLDOWN_MINS * 60, "1")
    logger.info("SL cooldown set for %s (%d min)", symbol, SL_COOLDOWN_MINS)


async def run_sl_monitor() -> dict:
    """
    Main SL monitor logic — evaluate all holdings, send Telegram alerts for breaches.

    Called by APScheduler every 5 minutes during market hours.
    Returns a summary dict with counts: checked, breaches, warnings, alerted, cooldown.
    """
    logger.info("SL monitor: running check...")
    alerts = check_holdings_for_sl()
    logger.info("SL monitor: %d alerts found", len(alerts))

    holdings = get_holdings_with_sl_status()
    results = {
        "checked": len(holdings),
        "breaches": 0,
        "warnings": 0,
        "alerted": 0,
        "cooldown": 0,
    }

    for alert in alerts:
        if alert.severity == "BREACH":
            results["breaches"] += 1
        if alert.severity == "WARNING":
            results["warnings"] += 1

        if is_on_cooldown(alert.symbol):
            results["cooldown"] += 1
            logger.info("SL: %s on cooldown, skipping", alert.symbol)
            continue

        token = generate_token("STOPLOSS", symbol=alert.symbol)

        await send_sl_breach_alert(
            symbol=alert.symbol,
            entry_price=alert.entry_price,
            current_price=alert.current_price,
            pnl_pct=alert.pnl_pct,
            quantity=alert.quantity,
            token=token,
        )

        set_cooldown(alert.symbol)
        results["alerted"] += 1
        logger.info("SL: ALERT sent for %s (%+.1f%%)", alert.symbol, alert.pnl_pct)

    logger.info("SL monitor complete: %s", results)
    return results


async def run_with_market_check() -> dict | None:
    """
    Market-hours gate for the SL monitor.

    Returns None outside 09:15–15:30 IST Mon–Fri; otherwise delegates to run_sl_monitor().
    """
    now = datetime.now(IST)

    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info("SL monitor: outside market hours (weekend), skipping")
        return None

    open_h, open_m = map(int, MARKET_OPEN.split(":"))
    close_h, close_m = map(int, MARKET_CLOSE.split(":"))
    market_open = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    market_close = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    if not (market_open <= now <= market_close):
        logger.info("SL monitor: outside market hours (%s IST), skipping", now.strftime("%H:%M"))
        return None

    return await run_sl_monitor()
