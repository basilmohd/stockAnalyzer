"""Nifty 200 universe screener — fetches and filters stocks for fresh entry opportunities.

Universe strategy (hybrid):
  - Hardcoded NIFTY200_SYMBOLS (50 stocks) is the bootstrap / offline fallback.
  - refresh_nifty200_universe() fetches all ~200 current constituents from NSE's
    public API every Sunday and caches the result in Redis for 7 days.
  - get_universe() reads the live cache; falls back to the hardcoded list when the
    cache is empty or Redis is unavailable.
  - get_cached_sector() resolves a symbol's sector from the live cache, then the
    static fallback map, then "Other".
"""

import json
import random

import config
from core.logger import get_logger
from core.redis_client import RedisClient
from data.news import compute_sentiment_score, fetch_news_for_symbol

logger = get_logger(__name__)
_redis = RedisClient(config.REDIS_URL)

_UNIVERSE_CACHE_KEY = "universe:nifty200"
_UNIVERSE_TTL = 7 * 24 * 3600  # 7 days

# ── Bootstrap universe (50 most liquid Nifty 200 stocks) ─────────────────────
# Used when Redis cache is empty or unavailable.
NIFTY200_SYMBOLS: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "BAJFINANCE", "SBILIFE", "AXISBANK", "KOTAKBANK",
    "LT", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN",
    "WIPRO", "NESTLEIND", "TECHM", "ULTRACEMCO", "POWERGRID",
    "NTPC", "ONGC", "COALINDIA", "JSWSTEEL", "TATASTEEL",
    "DRREDDY", "CIPLA", "DIVISLAB", "BRITANNIA", "DABUR",
    "MARICO", "PIDILITIND", "BERGEPAINT", "HAVELLS", "VOLTAS",
    "BAJAJFINSV", "HDFCLIFE", "ICICIPRULI", "MUTHOOTFIN", "PFC",
    "RECLTD", "CANBK", "BANKBARODA", "FEDERALBNK", "IDFCFIRSTB",
    "ADANIPORTS", "TATAPOWER", "TRENT", "NYKAA", "DMART",
]

# Static sector map for the bootstrap symbols — used as fallback when the live
# cache hasn't been populated yet (first week of operation).
_SECTOR_MAP: dict[str, str] = {
    "RELIANCE":    "Energy",
    "TCS":         "IT",
    "HDFCBANK":    "Financials",
    "ICICIBANK":   "Financials",
    "INFY":        "IT",
    "HINDUNILVR":  "FMCG",
    "BAJFINANCE":  "Financials",
    "SBILIFE":     "Insurance",
    "AXISBANK":    "Financials",
    "KOTAKBANK":   "Financials",
    "LT":          "Industrials",
    "ASIANPAINT":  "Chemicals",
    "MARUTI":      "Auto",
    "SUNPHARMA":   "Pharma",
    "TITAN":       "Consumer",
    "WIPRO":       "IT",
    "NESTLEIND":   "FMCG",
    "TECHM":       "IT",
    "ULTRACEMCO":  "Cement",
    "POWERGRID":   "Utilities",
    "NTPC":        "Utilities",
    "ONGC":        "Energy",
    "COALINDIA":   "Energy",
    "JSWSTEEL":    "Metals",
    "TATASTEEL":   "Metals",
    "DRREDDY":     "Pharma",
    "CIPLA":       "Pharma",
    "DIVISLAB":    "Pharma",
    "BRITANNIA":   "FMCG",
    "DABUR":       "FMCG",
    "MARICO":      "FMCG",
    "PIDILITIND":  "Chemicals",
    "BERGEPAINT":  "Chemicals",
    "HAVELLS":     "Consumer",
    "VOLTAS":      "Consumer",
    "BAJAJFINSV":  "Financials",
    "HDFCLIFE":    "Insurance",
    "ICICIPRULI":  "Insurance",
    "MUTHOOTFIN":  "Financials",
    "PFC":         "Financials",
    "RECLTD":      "Financials",
    "CANBK":       "Financials",
    "BANKBARODA":  "Financials",
    "FEDERALBNK":  "Financials",
    "IDFCFIRSTB":  "Financials",
    "ADANIPORTS":  "Industrials",
    "TATAPOWER":   "Utilities",
    "TRENT":       "Consumer",
    "NYKAA":       "Consumer",
    "DMART":       "Retail",
}

# NSE `meta.industry` strings → our sector labels.
# Covers the full breadth of Nifty 200 constituents.
_NSE_INDUSTRY_TO_SECTOR: dict[str, str] = {
    # IT / Telecom
    "IT-Software":                          "IT",
    "IT-Hardware":                          "IT",
    "Computers - Hardware & Software":      "IT",
    "Telecom - Services":                   "Telecom",
    "Telecom - Equipment & Accessories":    "Telecom",
    # Financials
    "Banks-Private Sector":                 "Financials",
    "Banks-Public Sector":                  "Financials",
    "Finance - NBFC":                       "Financials",
    "Finance - Others":                     "Financials",
    "Financial Technology (Fintech)":       "Financials",
    "Housing Finance":                      "Financials",
    # Insurance
    "Insurance":                            "Insurance",
    "Insurance-Life":                       "Insurance",
    "Insurance-Non-Life":                   "Insurance",
    # Energy / Utilities
    "Refineries & Marketing":               "Energy",
    "Oil Exploration & Production":         "Energy",
    "Gas Transmission/Marketing":           "Energy",
    "Mining - Coal":                        "Energy",
    "Power Generation & Distribution":      "Utilities",
    "Power Transmission & Distribution":    "Utilities",
    # Pharma / Healthcare
    "Pharmaceuticals & Biotechnology":      "Pharma",
    "Pharmaceuticals":                      "Pharma",
    "Healthcare Services":                  "Healthcare",
    "Hospitals":                            "Healthcare",
    "Hospitals & Allied Services":          "Healthcare",
    # FMCG / Consumer
    "FMCG":                                 "FMCG",
    "Food Products":                        "FMCG",
    "Consumer Durables":                    "Consumer",
    "Consumer Food":                        "FMCG",
    # Auto
    "Automobiles":                          "Auto",
    "Auto Ancillaries":                     "Auto",
    "Automobile":                           "Auto",
    # Metals / Mining
    "Iron & Steel/Interm.Products":         "Metals",
    "Mining & Minerals":                    "Metals",
    "Aluminium":                            "Metals",
    "Non Ferrous Metals":                   "Metals",
    # Industrials / Infra
    "Construction":                         "Industrials",
    "Engineering":                          "Industrials",
    "Infrastructure Companies":             "Industrials",
    "Ports":                                "Industrials",
    # Chemicals / Paints
    "Chemicals & Chemical Products":        "Chemicals",
    "Specialty Chemicals":                  "Chemicals",
    "Paints/Varnishes":                     "Chemicals",
    # Cement
    "Cement & Cement Products":             "Cement",
    # Retail
    "Retail":                               "Retail",
    "Departmental Stores":                  "Retail",
    "E-Commerce/App based Aggregator":      "Retail",
}


# ── Universe helpers ──────────────────────────────────────────────────────────

def get_universe() -> list[str]:
    """Return current scan universe as a list of NSE symbols.

    Reads from Redis cache (populated by refresh_nifty200_universe).
    Falls back to the hardcoded 50-stock bootstrap list when the cache is empty.
    """
    cached = _redis.get(_UNIVERSE_CACHE_KEY)
    if cached:
        try:
            items: list[dict] = json.loads(cached)
            symbols = [item["symbol"] for item in items if item.get("symbol")]
            if symbols:
                logger.debug("Universe loaded from cache: %d symbols", len(symbols))
                return symbols
        except Exception as exc:
            logger.warning("Failed to parse cached universe: %s", exc)

    logger.debug("Universe cache miss — using %d-symbol bootstrap list", len(NIFTY200_SYMBOLS))
    return list(NIFTY200_SYMBOLS)


def get_cached_sector(symbol: str) -> str:
    """Resolve the sector for *symbol* using the live cache, then the static fallback.

    Order: Redis universe cache → _SECTOR_MAP → "Other".
    """
    cached = _redis.get(_UNIVERSE_CACHE_KEY)
    if cached:
        try:
            for item in json.loads(cached):
                if item.get("symbol") == symbol:
                    return item.get("sector", "Other")
        except Exception:
            pass
    return _SECTOR_MAP.get(symbol, "Other")


async def refresh_nifty200_universe() -> list[dict]:
    """Fetch the current Nifty 200 constituents and update the Redis cache.

    In mock mode: repopulates the cache from the hardcoded bootstrap list.
    In live mode: fetches from NSE's public API; falls back to hardcoded on any error.
    Returns the list actually stored in cache: [{symbol, sector}, ...].
    """
    if config.USE_MOCK:
        return _refresh_from_bootstrap()

    try:
        universe = await _fetch_nse_nifty200()
        if len(universe) < 50:
            raise ValueError(f"NSE returned only {len(universe)} symbols — suspiciously small")
        _redis.setex(_UNIVERSE_CACHE_KEY, _UNIVERSE_TTL, json.dumps(universe))
        logger.info("Universe refreshed from NSE: %d symbols cached", len(universe))
        return universe
    except Exception as exc:
        logger.warning("NSE universe fetch failed (%s) — falling back to bootstrap list", exc)
        return _refresh_from_bootstrap()


def _refresh_from_bootstrap() -> list[dict]:
    """Write the hardcoded bootstrap list into the Redis cache and return it."""
    universe = [
        {"symbol": s, "sector": _SECTOR_MAP.get(s, "Other")}
        for s in NIFTY200_SYMBOLS
    ]
    _redis.setex(_UNIVERSE_CACHE_KEY, _UNIVERSE_TTL, json.dumps(universe))
    logger.info("Universe cache refreshed from bootstrap: %d symbols", len(universe))
    return universe


async def _fetch_nse_nifty200() -> list[dict]:
    """Call NSE's public equity index API to retrieve current Nifty 200 constituents.

    NSE requires a browser-like session: first GET the main page to collect cookies,
    then call the JSON API endpoint using those cookies.
    """
    import httpx

    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    async with httpx.AsyncClient(
        headers=base_headers,
        follow_redirects=True,
        timeout=30,
    ) as client:
        # Step 1: establish session cookies on the NSE homepage
        await client.get(
            "https://www.nseindia.com",
            headers={**base_headers, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        )

        # Step 2: fetch Nifty 200 index constituents
        response = await client.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200",
            headers={
                **base_headers,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nseindia.com/market-data/live-equity-market",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response.raise_for_status()
        payload = response.json()

    universe: list[dict] = []
    for item in payload.get("data", []):
        symbol = item.get("symbol", "").strip()
        if not symbol:
            continue
        # Industry sits inside the nested `meta` object
        meta = item.get("meta") or {}
        industry = meta.get("industry") or item.get("industry", "")
        sector = (
            _NSE_INDUSTRY_TO_SECTOR.get(industry)
            or _SECTOR_MAP.get(symbol)
            or "Other"
        )
        universe.append({"symbol": symbol, "sector": sector})

    return universe


# ── Per-symbol data fetch ─────────────────────────────────────────────────────

def fetch_screener_data(symbol: str) -> dict | None:
    """Fetch screening data for a single symbol.

    Returns a dict with RSI, SMA200, 52w metrics, news sentiment, and sector.
    Returns None if the fetch fails (caller skips silently).
    """
    if config.USE_MOCK:
        return _mock_screener_data(symbol)
    return _live_screener_data(symbol)


def _mock_screener_data(symbol: str) -> dict:
    """Generate deterministic synthetic screening data. ~20% of stocks pass filters."""
    rng = random.Random(hash(symbol) % (2 ** 32))
    is_opportunity = rng.random() < 0.20

    base_price = rng.uniform(200, 4000)
    current_price = round(base_price, 2)

    if is_opportunity:
        rsi = round(rng.uniform(28, 44), 1)
        sma_200 = round(current_price * rng.uniform(0.80, 0.97), 2)
        pct_from_52w_high = round(rng.uniform(-25, -9), 1)
        sentiment = rng.choice(["BULLISH", "NEUTRAL", "NEUTRAL"])
    else:
        roll = rng.random()
        if roll < 0.33:
            # Overbought / near 52w high
            rsi = round(rng.uniform(55, 80), 1)
            sma_200 = round(current_price * rng.uniform(0.85, 0.99), 2)
            pct_from_52w_high = round(rng.uniform(-7, -1), 1)
            sentiment = rng.choice(["BULLISH", "NEUTRAL"])
        elif roll < 0.66:
            # Below 200DMA
            rsi = round(rng.uniform(25, 55), 1)
            sma_200 = round(current_price * rng.uniform(1.02, 1.20), 2)
            pct_from_52w_high = round(rng.uniform(-30, -5), 1)
            sentiment = rng.choice(["NEUTRAL", "BEARISH"])
        else:
            # Bearish news
            rsi = round(rng.uniform(30, 50), 1)
            sma_200 = round(current_price * rng.uniform(0.85, 0.99), 2)
            pct_from_52w_high = round(rng.uniform(-20, -10), 1)
            sentiment = "BEARISH"

    return {
        "symbol":            symbol,
        "current_price":     current_price,
        "rsi":               rsi,
        "sma_200":           sma_200,
        "above_200dma":      current_price > sma_200,
        "pct_from_52w_high": pct_from_52w_high,
        "news_sentiment":    sentiment,
        "sector":            get_cached_sector(symbol),
    }


def _live_screener_data(symbol: str) -> dict | None:
    """Fetch live price, indicators, and news for a screener symbol."""
    try:
        from core.kite_client import KiteClient
        from data.technicals import compute_indicators, fetch_ohlc

        client = KiteClient()
        quote = client.get_quote([f"NSE:{symbol}"])
        nse_key = f"NSE:{symbol}"
        if not quote or nse_key not in quote:
            logger.debug("No quote for %s", symbol)
            return None

        current_price = float(quote[nse_key].get("last_price", 0))
        if current_price <= 0:
            return None

        df = fetch_ohlc(symbol, instrument_token=0)
        ind = compute_indicators(df)

        articles = fetch_news_for_symbol(symbol)
        news = compute_sentiment_score(articles)

        return {
            "symbol":            symbol,
            "current_price":     round(current_price, 2),
            "rsi":               ind.rsi,
            "sma_200":           ind.sma_200,
            "above_200dma":      ind.above_200sma,
            "pct_from_52w_high": ind.price_vs_52w_high_pct,
            "news_sentiment":    news.get("sentiment_label", "NEUTRAL"),
            "sector":            get_cached_sector(symbol),
        }
    except Exception as exc:
        logger.debug("Screener data failed for %s: %s", symbol, exc)
        return None


# ── Opportunity filter ────────────────────────────────────────────────────────

def apply_opportunity_filters(
    stock_data: dict,
    portfolio_symbols: set[str] | None = None,
) -> bool:
    """Return True only if all five opportunity entry conditions are met.

    Conditions: RSI < 45, above 200DMA, pulled back ≥8% from 52w high,
    no bearish news, and symbol not already held in the portfolio.
    """
    symbol = stock_data.get("symbol", "")

    if portfolio_symbols and symbol in portfolio_symbols:
        logger.debug("Filter reject %s: already in portfolio", symbol)
        return False

    rsi = stock_data.get("rsi", 100.0)
    if rsi >= 45:
        logger.debug("Filter reject %s: RSI %.1f >= 45", symbol, rsi)
        return False

    if not stock_data.get("above_200dma", False):
        logger.debug("Filter reject %s: below 200DMA (SMA200=%.2f)", symbol, stock_data.get("sma_200", 0))
        return False

    pct = stock_data.get("pct_from_52w_high", 0.0)
    if pct >= -8:
        logger.debug("Filter reject %s: pct_from_52w_high %.1f >= -8", symbol, pct)
        return False

    if stock_data.get("news_sentiment") == "BEARISH":
        logger.debug("Filter reject %s: BEARISH news sentiment", symbol)
        return False

    return True
