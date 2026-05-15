"""
Daily price storage and retrieval module.

Stores daily close prices in Redis for daily P&L calculations.
Provides graceful fallback to entry prices if Redis unavailable.
"""

import json
from datetime import datetime, date, timedelta
from typing import Dict, Optional

from config import REDIS_URL
from core.logger import get_logger
from core.kite_client import KiteClient
from core.redis_client import RedisClient

logger = get_logger(__name__)
redis_client = RedisClient(REDIS_URL)


async def store_market_close_prices() -> bool:
    """
    Fetch all holdings' current price at market close (3:30 PM) and store in Redis.
    
    Redis key: daily_close:{YYYY-MM-DD} (TTL: 1 day)
    Structure: {symbol: closing_price}
    
    Returns:
        bool: True if successfully stored, False on error.
    """
    try:
        # Get all holdings (excluding zero-share holdings)
        from data.portfolio import _filter_valid_holdings
        holdings = _filter_valid_holdings(KiteClient().get_holdings())
        if not holdings:
            logger.warning("No holdings found; skipping close price storage")
            return False
        
        # Build close prices dict: {symbol: last_price}
        close_prices = {
            holding["tradingsymbol"]: holding["last_price"]
            for holding in holdings
        }
        
        # Store in Redis with TTL of 86400 seconds (24 hours)
        today_str = date.today().isoformat()  # YYYY-MM-DD
        redis_key = f"daily_close:{today_str}"
        
        # Serialize as JSON
        json_data = json.dumps(close_prices)
        
        # Set in Redis (86400 seconds = 24 hours)
        redis_client.setex(redis_key, 86400, json_data)
        
        logger.info(
            f"Stored market close prices for {len(close_prices)} holdings in Redis: {redis_key}"
        )
        return True
        
    except Exception as e:
        logger.error(f"Error storing market close prices: {e}", exc_info=True)
        return False


def get_daily_open_prices(reference_date: Optional[date] = None) -> Dict[str, float]:
    """
    Retrieve previous trading day's close prices from Redis.
    
    Acts as 'opening prices' for daily P&L calculation on the given date.
    If reference_date not provided, uses today; retrieves yesterday's close.
    
    Args:
        reference_date: Date for which to get previous trading day's close prices.
                       If None, uses today's date.
    
    Returns:
        Dict[str, float]: {symbol: previous_close_price}
                         Returns empty dict if not found (fallback to entry price in caller).
    """
    try:
        if reference_date is None:
            reference_date = date.today()
        
        # Previous trading day (assuming no holidays; simple -1 day logic)
        # TODO: Integrate NSE holiday calendar for production accuracy
        prev_date = reference_date - timedelta(days=1)
        redis_key = f"daily_close:{prev_date.isoformat()}"
        
        # Retrieve from Redis
        cached_json = redis_client.get(redis_key)
        
        if cached_json is None:
            logger.warning(
                f"No cached close prices found for {prev_date.isoformat()} "
                f"(Redis key: {redis_key}); will fallback to entry prices"
            )
            return {}
        
        # Deserialize JSON
        close_prices = json.loads(cached_json)
        logger.debug(f"Retrieved {len(close_prices)} symbols from {redis_key}")
        return close_prices
        
    except json.JSONDecodeError as e:
        logger.error(f"Error deserializing close prices from Redis: {e}", exc_info=True)
        return {}
    except Exception as e:
        logger.error(f"Error retrieving daily open prices: {e}", exc_info=True)
        return {}


def get_fallback_prices(holdings: list[dict]) -> Dict[str, float]:
    """
    Build fallback price dict using holdings' average_price (entry price).
    
    Used when previous close prices unavailable from Redis.
    Ensures daily P&L calculation never fails due to missing historical data.
    
    Args:
        holdings: List of holding dicts from get_holdings().
    
    Returns:
        Dict[str, float]: {symbol: average_price}
    """
    return {
        holding["tradingsymbol"]: holding["average_price"]
        for holding in holdings
    }
