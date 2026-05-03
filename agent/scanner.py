"""Opportunity scanner — finds Nifty 200 stocks entering fresh buy zones."""

import json
import config
from core.redis_client import RedisClient
from core.telegram_bot import send_message
from data.portfolio import get_holdings_with_sl_status
from data.screener import apply_opportunity_filters, fetch_screener_data, get_universe

from core.logger import get_logger
logger = get_logger(__name__)
_redis = RedisClient(config.REDIS_URL)


def run_opportunity_scan() -> list[dict]:
    """Scan the Nifty 200 universe for stocks entering potential entry zones.

    Excludes current portfolio holdings, applies opportunity filters, sorts by RSI
    ascending, caps at MAX_OPPORTUNITIES_PER_DAY, and caches result in Redis (6h TTL).
    Returns up to config.MAX_OPPORTUNITIES_PER_DAY opportunity dicts.
    """
    portfolio_symbols: set[str] = {
        h["tradingsymbol"] for h in get_holdings_with_sl_status()
    }
    universe = get_universe()
    logger.info(
        "Opportunity scan started — %d symbols in universe, excluding %d portfolio holdings",
        len(universe), len(portfolio_symbols),
    )

    opportunities: list[dict] = []
    for symbol in universe:
        if symbol in portfolio_symbols:
            continue
        data = fetch_screener_data(symbol)
        if data is None:
            continue
        if apply_opportunity_filters(data, portfolio_symbols):
            opportunities.append(data)

    opportunities.sort(key=lambda x: x.get("rsi", 100.0))
    capped = opportunities[: config.MAX_OPPORTUNITIES_PER_DAY]

    _redis.setex("scanner:opportunities", 6 * 3600, json.dumps(capped))
    logger.info(
        "Opportunity scan complete — %d found, returning top %d",
        len(opportunities),
        len(capped),
    )
    return capped


def format_opportunity_telegram(opportunity: dict) -> str:
    """Format a single opportunity dict as an HTML Telegram watch alert."""
    symbol = opportunity.get("symbol", "?")
    sector = opportunity.get("sector", "Unknown")
    rsi = opportunity.get("rsi", 0)
    sma_200 = opportunity.get("sma_200", 0)
    pct_from_52w_high = opportunity.get("pct_from_52w_high", 0)
    news_sentiment = opportunity.get("news_sentiment", "NEUTRAL")
    current_price = opportunity.get("current_price", 0)

    return (
        f"💎 <b>New Opportunity — {symbol}</b>\n"
        f"Sector: {sector}\n"
        f"\n"
        f"📊 RSI: {rsi} (oversold)\n"
        f"📈 vs 200DMA: ✅ Above ({sma_200:.2f})\n"
        f"📉 From 52w High: {pct_from_52w_high}%\n"
        f"📰 News: {news_sentiment}\n"
        f"\n"
        f"💡 Pulled back into potential entry zone.\n"
        f"Current Price: ₹{current_price:,.2f}"
    )


async def send_opportunity_alerts() -> dict:
    """Run scan and send Telegram watch alerts for each opportunity (no order buttons).

    Returns summary: {opportunities_found, alerts_sent}.
    """
    opportunities = run_opportunity_scan()
    alerts_sent = 0

    for opp in opportunities:
        text = format_opportunity_telegram(opp)
        success = await send_message(text, parse_mode="HTML")
        if success:
            alerts_sent += 1
            logger.info("Opportunity alert sent: %s", opp.get("symbol"))
        else:
            logger.warning("Failed to send alert for %s", opp.get("symbol"))

    result = {"opportunities_found": len(opportunities), "alerts_sent": alerts_sent}
    logger.info("Opportunity alerts complete: %s", result)
    return result
