"""OHLC fetcher and technical indicator computation layer."""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import pandas as pd
import pandas_ta  # noqa: F401 — registers df.ta accessor

import config
from core.kite_client import KiteClient
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)
_redis = RedisClient(config.REDIS_URL)


@dataclass
class IndicatorResult:
    """Computed technical indicators for a single symbol."""

    rsi: float
    macd: float
    macd_signal: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    sma_50: float
    sma_200: float
    above_50sma: bool
    above_200sma: bool
    volume_ratio: float
    price_vs_52w_high_pct: float
    price_vs_52w_low_pct: float
    last_close: float
    computed_at: str


def fetch_ohlc(symbol: str, instrument_token: int, days: int = 200) -> pd.DataFrame:
    """Fetch OHLCV history for *symbol* and return a date-indexed DataFrame sorted ascending.

    Raises ValueError if fewer than 50 rows are returned.
    """
    today = datetime.now().date()
    from_date = (today - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    raw = KiteClient().get_historical_data(instrument_token, from_date, to_date, "day")
    df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(ascending=True, inplace=True)
    df.dropna(subset=["close"], inplace=True)

    if len(df) < 50:
        raise ValueError(f"Insufficient data for {symbol}: {len(df)} rows, need ≥50")

    return df


def compute_indicators(df: pd.DataFrame) -> IndicatorResult:
    """Compute RSI, MACD, Bollinger Bands, SMAs and derived metrics from OHLCV DataFrame."""
    if len(df) < 50:
        raise ValueError(f"Need at least 50 rows, got {len(df)}")

    close = df["close"]

    # RSI-14
    rsi_series = df.ta.rsi(length=14)
    rsi_val = float(rsi_series.iloc[-1])

    # MACD 12/26/9
    macd_df = df.ta.macd(fast=12, slow=26, signal=9)
    macd_col = next(c for c in macd_df.columns if c.startswith("MACD_"))
    macds_col = next(c for c in macd_df.columns if c.startswith("MACDs_"))
    macd_val = float(macd_df[macd_col].iloc[-1])
    macd_sig = float(macd_df[macds_col].iloc[-1])

    # Bollinger Bands, length=20, std=2
    bb_df = df.ta.bbands(length=20)
    bbu_col = next(c for c in bb_df.columns if c.startswith("BBU_"))
    bbm_col = next(c for c in bb_df.columns if c.startswith("BBM_"))
    bbl_col = next(c for c in bb_df.columns if c.startswith("BBL_"))
    bb_upper = float(bb_df[bbu_col].iloc[-1])
    bb_middle = float(bb_df[bbm_col].iloc[-1])
    bb_lower = float(bb_df[bbl_col].iloc[-1])

    # SMA 50 and 200
    sma50_series = df.ta.sma(length=50)
    sma200_series = df.ta.sma(length=200)
    sma_50 = float(sma50_series.iloc[-1])
    sma200_raw = sma200_series.iloc[-1]
    sma_200 = float(sma200_raw) if not pd.isna(sma200_raw) else sma_50

    last_close = float(close.iloc[-1])

    # Volume ratio: last candle vs 20-bar average
    last_volume = float(df["volume"].iloc[-1])
    avg_volume_20 = float(df["volume"].tail(20).mean())
    volume_ratio = last_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0

    # 52-week high/low from the last 252 rows
    hist_252 = df.tail(252)
    high_52w = float(hist_252["high"].max())
    low_52w = float(hist_252["low"].min())

    def r(val: float) -> float:
        return round(float(val), 2)

    return IndicatorResult(
        rsi=r(rsi_val),
        macd=r(macd_val),
        macd_signal=r(macd_sig),
        bb_upper=r(bb_upper),
        bb_middle=r(bb_middle),
        bb_lower=r(bb_lower),
        sma_50=r(sma_50),
        sma_200=r(sma_200),
        above_50sma=bool(last_close > sma_50),
        above_200sma=bool(last_close > sma_200),
        volume_ratio=r(volume_ratio),
        price_vs_52w_high_pct=r(((last_close - high_52w) / high_52w) * 100),
        price_vs_52w_low_pct=r(((last_close - low_52w) / low_52w) * 100),
        last_close=r(last_close),
        computed_at=datetime.now().isoformat(),
    )


def get_technicals_for_holdings() -> dict[str, "IndicatorResult | dict"]:
    """Compute technical indicators for every holding, using Redis cache (TTL 1h)."""
    holdings = KiteClient().get_holdings()
    results: dict = {}
    start = time.time()

    for holding in holdings:
        symbol: str = holding["tradingsymbol"]
        token: int = holding["instrument_token"]
        cache_key = f"indicators:{symbol}"

        cached = _redis.get(cache_key)
        if cached:
            logger.info("Cache hit: %s", symbol)
            cached_dict = json.loads(cached)
            if "error" not in cached_dict:
                results[symbol] = IndicatorResult(**cached_dict)
            else:
                results[symbol] = cached_dict
            continue

        try:
            df = fetch_ohlc(symbol, token)
            ind = compute_indicators(df)
            _redis.setex(cache_key, 3600, json.dumps(asdict(ind)))
            results[symbol] = ind
        except Exception as exc:
            logger.warning("Indicator compute failed for %s: %s", symbol, exc)
            results[symbol] = {"error": str(exc)}

    elapsed = time.time() - start
    logger.info("Technicals computed for %d stocks in %.1fs", len(results), elapsed)
    return results
