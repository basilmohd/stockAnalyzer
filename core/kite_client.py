"""
Kite Connect wrapper. Delegates to MockKiteClient when USE_MOCK=true,
or to the real KiteConnect SDK when USE_MOCK=false.
"""
import logging
from datetime import datetime
from typing import Optional

from config import (
    KITE_API_KEY,
    KITE_API_SECRET,
    REDIS_URL,
    USE_MOCK,
)
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

_redis = RedisClient(REDIS_URL)


class KiteClient:
    """Unified Kite Connect client — real or mock depending on USE_MOCK."""

    def __init__(self) -> None:
        """Initialise in mock or real mode based on USE_MOCK config flag."""
        self.mock: bool = USE_MOCK

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
        """Return normalised portfolio holdings list with pnl and pnl_pct fields."""
        try:
            if self.mock:
                return self.kite.get_holdings()

            raw_list: list[dict] = self.kite.holdings()
            holdings = []
            for raw in raw_list:
                avg = raw.get("average_price", 0.0)
                lp = raw.get("last_price", 0.0)
                pnl = raw.get("pnl", (lp - avg) * raw.get("quantity", 0))
                pnl_pct = raw.get(
                    "pnl_pct",
                    ((lp - avg) / avg * 100) if avg else 0.0,
                )
                holdings.append({
                    "tradingsymbol":    raw.get("tradingsymbol", ""),
                    "exchange":         raw.get("exchange", "NSE"),
                    "quantity":         raw.get("quantity", 0),
                    "average_price":    avg,
                    "last_price":       lp,
                    "pnl":              round(pnl, 2),
                    "pnl_pct":          round(pnl_pct, 2),
                    "product":          raw.get("product", "CNC"),
                    "instrument_token": raw.get("instrument_token", 0),
                })
            return holdings
        except Exception as exc:
            logger.error("get_holdings error: %s", exc)
            raise

    def get_quote(self, symbols: list[str]) -> dict:
        """Return OHLCV quote data keyed by 'NSE:SYMBOL'. symbols format: ['NSE:ICICIBANK']."""
        try:
            if self.mock:
                return self.kite.get_quote(symbols)
            return self.kite.quote(symbols)
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

    def place_order(self, symbol: str, action: str, quantity: int) -> dict:
        """Place a CNC MARKET order for a signal. action: BUY/SELL/REDUCE/EXIT.

        Never raises — returns error dict on failure.
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
                "place_order: symbol=%s action=%s qty=%d mock=%s",
                symbol, action, quantity, self.mock,
            )

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
