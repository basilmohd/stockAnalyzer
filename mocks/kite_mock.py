"""Mock Kite Connect client for local development (USE_MOCK_KITE=true)."""

import random
from datetime import datetime, timedelta
from typing import Any


_HOLDINGS_DATA = [
    # symbol         qty    avg_price   last_price   instrument_token
    {"tradingsymbol": "IRCTC",      "qty": 119, "avg_price":   365.28, "last_price":   539.55, "instrument_token": 3484417},
    {"tradingsymbol": "POLYCAB",    "qty":   5, "avg_price":  2402.43, "last_price":  8110.50, "instrument_token": 4152833},
    {"tradingsymbol": "RELIANCE",   "qty":  24, "avg_price":   960.03, "last_price":  1430.80, "instrument_token": 738561},
    {"tradingsymbol": "OLECTRA",    "qty":  27, "avg_price":   414.41, "last_price":  1245.60, "instrument_token": 969473},
    {"tradingsymbol": "MARUTI",     "qty":   2, "avg_price": 12932.28, "last_price": 13314.00, "instrument_token": 2815745},
    {"tradingsymbol": "KOTAKGOLD",  "qty": 200, "avg_price":   121.45, "last_price":   124.70, "instrument_token": 5122049},
    {"tradingsymbol": "VARUNBEV",   "qty":  44, "avg_price":   119.29, "last_price":   513.70, "instrument_token": 2273281},
    {"tradingsymbol": "TATAMTRDVR", "qty":  52, "avg_price":   275.06, "last_price":   409.90, "instrument_token": 884993},
    {"tradingsymbol": "MOTHERSON",  "qty": 157, "avg_price":    69.23, "last_price":   121.21, "instrument_token": 4006913},
    {"tradingsymbol": "EXIDEIND",   "qty":  50, "avg_price":   184.71, "last_price":   360.55, "instrument_token": 1629697},
    {"tradingsymbol": "SGBSEP31",   "qty":   5, "avg_price":  5873.00, "last_price": 15400.61, "instrument_token": 9900001},
]

_OHLCV_OFFSETS = {
    # symbol: (open_delta, high_pct, low_pct, volume_base)
    "IRCTC":      (  -4.20, 0.013, 0.009, 2_100_000),
    "POLYCAB":    ( -38.50, 0.011, 0.008,   480_000),
    "RELIANCE":   (  -7.80, 0.010, 0.007, 9_800_000),
    "OLECTRA":    ( -11.20, 0.015, 0.011,   760_000),
    "MARUTI":     ( -55.00, 0.010, 0.007,   380_000),
    "KOTAKGOLD":  (  -0.30, 0.006, 0.005,   540_000),
    "VARUNBEV":   (  -5.10, 0.012, 0.009, 2_200_000),
    "TATAMTRDVR": (  -3.40, 0.014, 0.010, 1_050_000),
    "MOTHERSON":  (  -1.20, 0.013, 0.010, 4_800_000),
    "EXIDEIND":   (  -2.90, 0.011, 0.008, 1_450_000),
    "SGBSEP31":   ( -15.00, 0.005, 0.004,     3_500),
}


class MockKiteClient:
    """Drop-in replacement for KiteClient when USE_MOCK_KITE=true."""

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
        """Return OHLCV quote data for each requested symbol.

        Accepts both bare symbols ("IRCTC") and exchange-prefixed form ("NSE:IRCTC").
        The returned dict is always keyed as "NSE:SYMBOL".
        """
        by_symbol = {r["tradingsymbol"]: r for r in _HOLDINGS_DATA}
        result: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            bare = sym.split(":")[-1]
            base = by_symbol.get(bare)
            if base is None:
                continue
            lp = base["last_price"]
            off = _OHLCV_OFFSETS.get(bare, (0, 0.01, 0.01, 1_000_000))
            open_price = round(lp + off[0], 2)
            high = round(lp * (1 + off[1]), 2)
            low  = round(lp * (1 - off[2]), 2)
            key = sym if ":" in sym else f"NSE:{sym}"
            result[key] = {
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
        symbol,
        from_date,
        to_date,
        interval: str = "day",
    ) -> list[dict[str, Any]]:
        """Return 200 rows of reproducible fake OHLCV history for a symbol."""
        by_symbol = {r["tradingsymbol"]: r for r in _HOLDINGS_DATA}
        by_token = {r["instrument_token"]: r for r in _HOLDINGS_DATA}
        row = by_symbol.get(symbol) or by_token.get(symbol, {})
        base_price = row.get("avg_price", 1000.0)

        if isinstance(to_date, str):
            to_date = datetime.strptime(to_date, "%Y-%m-%d")

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
