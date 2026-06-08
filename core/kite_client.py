"""
Kite Connect wrapper. Delegates to MockKiteClient when USE_MOCK_KITE=true,
or to the real KiteConnect SDK when USE_MOCK_KITE=false.
"""
from datetime import datetime
from typing import Optional
import time

import config
from config import (
    KITE_API_KEY,
    KITE_API_SECRET,
    REDIS_URL,
    USE_MOCK_KITE,
)
from core.redis_client import RedisClient

from core.logger import get_logger
logger = get_logger(__name__)

_redis = RedisClient(REDIS_URL)


class KiteClient:
    """Unified Kite Connect client — real or mock depending on USE_MOCK_KITE."""

    def __init__(self) -> None:
        """Initialise in mock or real mode based on USE_MOCK_KITE config flag."""
        self.mock: bool = USE_MOCK_KITE

        if self.mock:
            from mocks.kite_mock import MockKiteClient
            self.kite = MockKiteClient()
            logger.info("KiteClient running in MOCK mode")
        else:
            from kiteconnect import KiteConnect
            self.kite = KiteConnect(api_key=KITE_API_KEY)
            token: Optional[str] = _redis.get("kite:access_token")
            if token:
                self.kite.set_access_token(token)
                logger.info("KiteClient: loaded token from Redis")
            else:
                logger.warning("KiteClient: no token found, auth required")

    # ── Auth ──────────────────────────────────────────────────────────────────

    def get_login_url(self) -> str:
        """Return the Kite login URL for OAuth flow."""
        try:
            if self.mock:
                return "http://mock-login-url/kite"
            return self.kite.login_url()
        except Exception as exc:
            logger.error("get_login_url error: %s", exc)
            raise

    def generate_session(self, request_token: str) -> dict:
        """Exchange request_token for an access token and persist it in Redis."""
        try:
            if self.mock:
                return {"access_token": "mock_token_abc123", "user_id": "MOCK01"}
            session = self.kite.generate_session(request_token, KITE_API_SECRET)
            _redis.setex("kite:access_token", 86400, session["access_token"])
            _redis.setex("kite:user_id", 86400, session["user_id"])
            return session
        except Exception as exc:
            logger.error("generate_session error: %s", exc)
            raise

    def is_authenticated(self) -> bool:
        """Return True if a valid access token exists in Redis (or mock mode)."""
        try:
            if self.mock:
                return True
            return bool(_redis.get("kite:access_token"))
        except Exception as exc:
            logger.error("is_authenticated error: %s", exc)
            raise

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_holdings(self) -> list[dict]:
        """Return normalised portfolio holdings list with pnl and pnl_pct fields.
        
        Uses retry logic (3 attempts, exponential backoff) and Redis cache fallback.
        If API fails, returns cached data if available.
        """
        try:
            if self.mock:
                return self.kite.get_holdings()

            # Try to fetch from Kite API with retry logic
            max_retries = 3
            retry_delay = 1  # Start with 1 second
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"get_holdings: attempt {attempt + 1}/{max_retries}")
                    raw_list: list[dict] = self.kite.holdings()
                    
                    # Normalize and cache on success
                    holdings = self._normalize_holdings(raw_list)
                    from config import HOLDINGS_CACHE_TTL
                    _redis.setex("kite:holdings_cache", HOLDINGS_CACHE_TTL, str(holdings))
                    logger.info(f"get_holdings: success, cached {len(holdings)} holdings (TTL={HOLDINGS_CACHE_TTL}s)")
                    return holdings
                    
                except (TimeoutError, ConnectionError, Exception) as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"get_holdings attempt {attempt + 1} failed: {e}, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"get_holdings: all {max_retries} attempts failed: {e}")
                        raise
            
        except Exception as exc:
            logger.error(f"get_holdings error: {exc}, attempting fallback to cache...")
            
            # Try cache fallback
            cached = _redis.get("kite:holdings_cache")
            if cached:
                logger.info("Using cached holdings data")
                import ast
                return ast.literal_eval(cached)
            
            logger.error(f"get_holdings: no cache available, raising error")
            raise

    def _normalize_holdings(self, raw_list: list[dict]) -> list[dict]:
        """Normalize Kite raw holdings to our standard format.
        
        Filters out holdings with zero quantity, zero average price, or zero current price
        to prevent division by zero errors in downstream calculations.
        """
        holdings = []
        for raw in raw_list:
            qty = raw.get("quantity", 0)
            avg = raw.get("average_price", 0.0)
            lp = raw.get("last_price", 0.0)
            symbol = raw.get("tradingsymbol", "")
            
            # Skip holdings with zero quantity or zero prices (migrated stocks)
            if qty <= 0 or avg <= 0 or lp <= 0:
                logger.debug(
                    f"Skipping {symbol}: qty={qty}, avg={avg}, lp={lp} (migrated/invalid stock)"
                )
                continue
            
            pnl = raw.get("pnl", (lp - avg) * qty)
            # Safe pnl_pct calculation with zero check
            pnl_pct = raw.get(
                "pnl_pct",
                ((lp - avg) / avg * 100) if avg > 0 else 0.0,
            )
            holdings.append({
                "tradingsymbol":    symbol,
                "exchange":         raw.get("exchange", "NSE"),
                "quantity":         qty,
                "average_price":    avg,
                "last_price":       lp,
                "pnl":              round(pnl, 2),
                "pnl_pct":          round(pnl_pct, 2),
                "product":          raw.get("product", "CNC"),
                "instrument_token": raw.get("instrument_token", 0),
            })
        return holdings

    def get_quote(self, symbols: list[str]) -> dict:
        """Return OHLCV quote data keyed by 'NSE:SYMBOL'. symbols format: ['NSE:ICICIBANK'].
        
        Uses retry logic (3 attempts, exponential backoff) to handle API timeouts.
        """
        try:
            if self.mock:
                return self.kite.get_quote(symbols)

            # Try to fetch from Kite API with retry logic
            max_retries = 3
            retry_delay = 1
            
            for attempt in range(max_retries):
                try:
                    logger.info(f"get_quote: attempt {attempt + 1}/{max_retries} for {len(symbols)} symbols")
                    return self.kite.quote(symbols)
                    
                except (TimeoutError, ConnectionError, Exception) as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"get_quote attempt {attempt + 1} failed: {e}, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"get_quote: all {max_retries} attempts failed: {e}")
                        raise
                        
        except Exception as exc:
            logger.error("get_quote error: %s", exc)
            raise

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: str,
        to_date: str,
        interval: str = "day",
    ) -> list[dict]:
        """Return OHLCV history. from_date/to_date format: 'YYYY-MM-DD'."""
        try:
            if self.mock:
                return self.kite.get_historical_data(
                    instrument_token, from_date, to_date, interval
                )
            from_dt = datetime.strptime(from_date, "%Y-%m-%d")
            to_dt = datetime.strptime(to_date, "%Y-%m-%d")
            raw = self.kite.historical_data(instrument_token, from_dt, to_dt, interval)
            return [
                {
                    "date":   r["date"].strftime("%Y-%m-%d") if hasattr(r["date"], "strftime") else str(r["date"]),
                    "open":   r["open"],
                    "high":   r["high"],
                    "low":    r["low"],
                    "close":  r["close"],
                    "volume": r["volume"],
                }
                for r in raw
            ]
        except Exception as exc:
            logger.error("get_historical_data error: %s", exc)
            raise

    # ── Trading ───────────────────────────────────────────────────────────────

    def _paper_fill_price(self, symbol: str) -> float:
        """Best-effort current price to 'fill' a paper order at.

        Tries the live/mock quote; falls back to 0.0 if the quote is unavailable so
        a paper order never raises (the caller treats 0.0 as a soft fill price).
        """
        try:
            quote = self.get_quote([f"NSE:{symbol}"])
            data = quote.get(f"NSE:{symbol}") or quote.get(symbol) or {}
            return float(data.get("last_price", 0.0))
        except Exception as exc:
            logger.warning("paper fill price lookup failed for %s: %s", symbol, exc)
            return 0.0

    def place_order(self, symbol: str, action: str, quantity: int) -> dict:
        """Place a CNC MARKET order for a signal. action: BUY/SELL/REDUCE/EXIT.

        Never raises — returns error dict on failure.
        Paper: PAPER_TRADE_MODE checked FIRST — "fills" at the live quote price and
        returns a PAPER-{symbol}-{ts} order_id; the real broker is never reached.
        Mock: returns MOCK-{symbol}-{timestamp} order_id.
        Real: REDUCE sells 50% of current holdings; EXIT sells all.
        """
        import time as _time
        try:
            if not symbol or quantity <= 0:
                return {
                    "order_id": None,
                    "status": "FAILED",
                    "error": f"Invalid params: symbol={symbol!r}, quantity={quantity}",
                }

            logger.info(
                "place_order: symbol=%s action=%s qty=%d mock=%s paper=%s",
                symbol, action, quantity, self.mock, config.PAPER_TRADE_MODE,
            )

            # PAPER MODE — must precede the live branch so a real order is never
            # placed while paper mode is on. "Fills" at the current quote price.
            if config.PAPER_TRADE_MODE:
                fill_price = self._paper_fill_price(symbol)
                order_id = f"PAPER-{symbol}-{int(_time.time())}"
                logger.info(
                    "📝 PAPER ORDER: %s %d %s @ %s", action, quantity, symbol, fill_price
                )
                return {
                    "order_id": order_id,
                    "status": "COMPLETE",
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                    "fill_price": fill_price,
                    "is_paper": True,
                }

            if self.mock:
                order_id = f"MOCK-{symbol}-{int(_time.time())}"
                logger.info("Mock order placed: %s", order_id)
                return {
                    "order_id": order_id,
                    "status": "COMPLETE",
                    "symbol": symbol,
                    "action": action,
                    "quantity": quantity,
                }

            from kiteconnect import KiteConnect

            action_upper = action.upper()
            if action_upper == "BUY":
                transaction_type = KiteConnect.TRANSACTION_TYPE_BUY
                actual_qty = quantity
            elif action_upper in ("SELL", "REDUCE", "EXIT"):
                transaction_type = KiteConnect.TRANSACTION_TYPE_SELL
                actual_qty = quantity
                if action_upper in ("REDUCE", "EXIT"):
                    holdings = self.get_holdings()
                    holding = next(
                        (h for h in holdings if h["tradingsymbol"] == symbol), None
                    )
                    if holding:
                        if action_upper == "EXIT":
                            actual_qty = holding["quantity"]
                        else:
                            actual_qty = max(1, holding["quantity"] // 2)
            else:
                return {
                    "order_id": None,
                    "status": "FAILED",
                    "error": f"Unknown action: {action}",
                }

            kite_order_id = self.kite.place_order(
                tradingsymbol=symbol,
                exchange="NSE",
                transaction_type=transaction_type,
                quantity=actual_qty,
                order_type=KiteConnect.ORDER_TYPE_MARKET,
                product=KiteConnect.PRODUCT_CNC,
                variety=KiteConnect.VARIETY_REGULAR,
                market_protection=-1,  # Automatic market protection by system
            )

            return {
                "order_id": str(kite_order_id),
                "status": "COMPLETE",
                "symbol": symbol,
                "action": action,
                "quantity": actual_qty,
            }
        except Exception as exc:
            logger.error(
                "place_order failed: symbol=%s action=%s qty=%d: %s",
                symbol, action, quantity, exc,
            )
            return {"order_id": None, "status": "FAILED", "error": str(exc)}
