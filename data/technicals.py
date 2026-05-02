"""OHLC fetcher and technical indicator computation layer."""

import json
import logging
import time
from datetime import datetime, timedelta

import pandas as pd

from config import REDIS_URL
from core.kite_client import KiteClient
from core.redis_client import RedisClient

logger = logging.getLogger(__name__)
_redis = RedisClient(REDIS_URL)


def fetch_ohlc(symbol: str, instrument_token: int, days: int = 200) -> pd.DataFrame:
    """Fetch OHLCV history for *symbol* and return a date-indexed DataFrame sorted ascending."""
    today = datetime.now().date()
    from_date = (today - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    raw = KiteClient().get_historical_data(instrument_token, from_date, to_date, "day")
    df = pd.DataFrame(raw, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(ascending=True, inplace=True)
    df.dropna(subset=["close"], inplace=True)
    return df


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI using exponential smoothing (matches pandas-ta output)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _bbands(close: pd.Series, length: int = 20, std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (upper, middle, lower) Bollinger Bands."""
    middle = close.rolling(length).mean()
    sigma = close.rolling(length).std(ddof=0)
    return middle + std * sigma, middle, middle - std * sigma


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute RSI, MACD, Bollinger Bands, SMAs and derived metrics from OHLCV DataFrame."""
    if len(df) < 50:
        raise ValueError(f"Need at least 50 rows, got {len(df)}")

    close = df["close"]

    rsi_series = _rsi(close, 14)
    macd_line, signal_line, histogram = _macd(close, 12, 26, 9)
    bb_upper, bb_middle, bb_lower = _bbands(close, 20)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    last_close = float(close.iloc[-1])
    last_volume = float(df["volume"].iloc[-1])
    avg_volume_20 = float(df["volume"].tail(20).mean())
    high_52w = float(df["high"].max())
    low_52w = float(df["low"].min())

    sma50_val = float(sma50.iloc[-1])
    sma200_raw = sma200.iloc[-1]
    sma200_val = float(sma200_raw) if not pd.isna(sma200_raw) else None

    def r(val: float) -> float:
        return round(float(val), 2)

    return {
        "rsi":                   r(rsi_series.iloc[-1]),
        "macd":                  r(macd_line.iloc[-1]),
        "macd_signal":           r(signal_line.iloc[-1]),
        "macd_histogram":        r(histogram.iloc[-1]),
        "bb_upper":              r(bb_upper.iloc[-1]),
        "bb_middle":             r(bb_middle.iloc[-1]),
        "bb_lower":              r(bb_lower.iloc[-1]),
        "sma_50":                r(sma50_val),
        "sma_200":               r(sma200_val) if sma200_val is not None else None,
        "above_50sma":           bool(last_close > sma50_val),
        "above_200sma":          bool(last_close > sma200_val) if sma200_val is not None else False,
        "volume_ratio":          round(last_volume / avg_volume_20, 2),
        "price_vs_52w_high_pct": r(((last_close - high_52w) / high_52w) * 100),
        "price_vs_52w_low_pct":  r(((last_close - low_52w) / low_52w) * 100),
        "last_close":            r(last_close),
        "computed_at":           datetime.now().isoformat(),
    }


def get_technicals_for_holdings() -> dict[str, dict]:
    """Compute technical indicators for every holding, using Redis cache (TTL 1h)."""
    holdings = KiteClient().get_holdings()
    results: dict[str, dict] = {}
    start = time.time()

    for holding in holdings:
        symbol: str = holding["tradingsymbol"]
        token: int = holding["instrument_token"]
        cache_key = f"indicators:{symbol}"

        cached = _redis.get(cache_key)
        if cached:
            logger.info("Cache hit: %s", symbol)
            results[symbol] = json.loads(cached)
            continue

        try:
            df = fetch_ohlc(symbol, token)
            indicators = compute_indicators(df)
            _redis.setex(cache_key, 3600, json.dumps(indicators))
            results[symbol] = indicators
        except Exception as exc:
            logger.warning("Indicator compute failed for %s: %s", symbol, exc)
            results[symbol] = {"error": str(exc)}

    elapsed = time.time() - start
    logger.info("Technicals computed for %d stocks in %.1fs", len(results), elapsed)
    return results
