"""Mock Kite Connect client for local development (USE_MOCK=true)."""

import random
from datetime import datetime, timedelta
from typing import Any


_HOLDINGS_DATA = [
    {"tradingsymbol": "ICICIBANK",  "qty": 50,  "avg_price": 1140.50, "last_price": 1162.30, "instrument_token": 1270529},
    {"tradingsymbol": "INFY",       "qty": 30,  "avg_price": 1580.00, "last_price": 1541.20, "instrument_token": 408065},
    {"tradingsymbol": "HDFCBANK",   "qty": 40,  "avg_price": 1620.75, "last_price": 1678.90, "instrument_token": 341249},
    {"tradingsymbol": "BHARTIARTL", "qty": 25,  "avg_price": 1380.00, "last_price": 1445.60, "instrument_token": 2714625},
    {"tradingsymbol": "APOLLOHOSP", "qty": 10,  "avg_price": 6820.00, "last_price": 7102.50, "instrument_token": 4343041},
    {"tradingsymbol": "TATAMOTORS", "qty": 60,  "avg_price": 780.25,  "last_price": 712.40,  "instrument_token": 884737},
    {"tradingsymbol": "SUNPHARMA",  "qty": 35,  "avg_price": 1720.00, "last_price": 1798.30, "instrument_token": 857857},
    {"tradingsymbol": "PFC",        "qty": 100, "avg_price": 480.50,  "last_price": 412.80,  "instrument_token": 4592641},
]

_OHLCV_OFFSETS = {
    # symbol: (open_delta, high_pct, low_pct, volume_base)
    "ICICIBANK":  (  -3.20, 0.012, 0.008, 4_200_000),
    "INFY":       (   5.80, 0.010, 0.009, 3_100_000),
    "HDFCBANK":   (  -8.50, 0.011, 0.007, 5_800_000),
    "BHARTIARTL": (  -2.10, 0.013, 0.006, 2_400_000),
    "APOLLOHOSP": ( -45.00, 0.014, 0.010,   480_000),
    "TATAMOTORS": (   4.30, 0.015, 0.012, 9_600_000),
    "SUNPHARMA":  ( -11.20, 0.009, 0.008, 1_900_000),
    "PFC":        (   2.50, 0.016, 0.011, 7_200_000),
}


class MockKiteClient:
    """Drop-in replacement for KiteClient when USE_MOCK=true."""

    def get_holdings(self) -> list[dict[str, Any]]:
        """Return mock portfolio holdings with pre-calculated PnL fields."""
        holdings = []
        for raw in _HOLDINGS_DATA:
            pnl = (raw["last_price"] - raw["avg_price"]) * raw["qty"]
            pnl_pct = ((raw["last_price"] - raw["avg_price"]) / raw["avg_price"]) * 100
            holdings.append({
                "tradingsymbol":    raw["tradingsymbol"],
                "instrument_token": raw["instrument_token"],
                "exchange":         "NSE",
                "product":          "CNC",
                "quantity":         raw["qty"],
                "average_price":    raw["avg_price"],
                "last_price":       raw["last_price"],
                "pnl":              round(pnl, 2),
                "pnl_pct":          round(pnl_pct, 2),
            })
        return holdings

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Return OHLCV quote data for each requested symbol."""
        by_symbol = {r["tradingsymbol"]: r for r in _HOLDINGS_DATA}
        result: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            base = by_symbol.get(sym)
            if base is None:
                continue
            lp = base["last_price"]
            off = _OHLCV_OFFSETS.get(sym, (0, 0.01, 0.01, 1_000_000))
            open_price = round(lp + off[0], 2)
            high = round(lp * (1 + off[1]), 2)
            low  = round(lp * (1 - off[2]), 2)
            result[f"NSE:{sym}"] = {
                "last_price":    lp,
                "open":          open_price,
                "high":          high,
                "low":           low,
                "close":         round(lp - off[0] * 0.4, 2),
                "volume":        int(off[3] * random.uniform(0.85, 1.15)),
                "average_price": round((open_price + high + low + lp) / 4, 2),
            }
        return result

    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Return 200 rows of reproducible fake OHLCV history for a symbol."""
        by_symbol = {r["tradingsymbol"]: r for r in _HOLDINGS_DATA}
        base_price = by_symbol.get(symbol, {}).get("avg_price", 1000.0)

        rng = random.Random(42)
        rows: list[dict[str, Any]] = []
        price = base_price
        current_date = to_date - timedelta(days=200)

        for _ in range(200):
            current_date += timedelta(days=1)
            change_pct = rng.gauss(0, 0.012)
            price = round(price * (1 + change_pct), 2)
            high  = round(price * (1 + abs(rng.gauss(0, 0.005))), 2)
            low   = round(price * (1 - abs(rng.gauss(0, 0.005))), 2)
            open_ = round(price * (1 + rng.gauss(0, 0.004)), 2)
            vol   = int(rng.uniform(500_000, 5_000_000))
            rows.append({
                "date":   current_date.strftime("%Y-%m-%d"),
                "open":   open_,
                "high":   high,
                "low":    low,
                "close":  price,
                "volume": vol,
            })
        return rows

    def place_order(self, **kwargs: Any) -> dict[str, str]:
        """Simulate order placement — always succeeds in mock mode."""
        return {"order_id": "MOCK_ORDER_123456", "status": "success"}
