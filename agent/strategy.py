"""Strategy classifier and entry-rule validator for the signal pipeline."""

NIFTY50_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "BAJFINANCE",
    "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "WIPRO", "ULTRACEMCO", "NESTLEIND",
    "TECHM", "POWERGRID", "NTPC", "ONGC", "TATAMOTORS",
    "JSWSTEEL", "TATASTEEL", "DRREDDY", "CIPLA", "DIVISLAB",
    "BRITANNIA", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "ADANIPORTS",
    "COALINDIA", "APOLLOHOSP", "TATACONSUM", "GRASIM", "HEROMOTOCO",
    "EICHERMOT", "BPCL", "INDUSINDBK", "UPL", "DMART",
    "PIDILITIND", "TATAPOWER", "HAVELLS", "BERGEPAINT", "PFC",
]

SECTOR_MAP = {
    "ICICIBANK": "Financials", "HDFCBANK": "Financials",
    "KOTAKBANK": "Financials", "AXISBANK": "Financials",
    "SBIN": "Financials", "BAJFINANCE": "Financials",
    "BAJAJFINSV": "Financials", "HDFCLIFE": "Financials",
    "SBILIFE": "Financials", "PFC": "Financials",
    "INDUSINDBK": "Financials",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "TECHM": "IT",
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "TATAPOWER": "Energy", "COALINDIA": "Energy",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG",
    "MARICO": "FMCG",
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma",
    "CIPLA": "Pharma", "DIVISLAB": "Pharma", "APOLLOHOSP": "Healthcare",
    "BHARTIARTL": "Telecom",
    "LT": "Infrastructure", "ULTRACEMCO": "Cement",
    "GRASIM": "Cement",
    "TATAMOTORS": "Auto", "MARUTI": "Auto",
    "HEROMOTOCO": "Auto", "EICHERMOT": "Auto",
    "JSWSTEEL": "Metals", "TATASTEEL": "Metals",
    "ASIANPAINT": "Paints", "BERGEPAINT": "Paints",
    "PIDILITIND": "Chemicals",
    "TITAN": "Consumer", "DMART": "Retail",
    "ADANIPORTS": "Infrastructure",
    "NTPC": "Power", "POWERGRID": "Power",
    "HAVELLS": "Electricals", "UPL": "Chemicals",
}


def classify_strategy(signal: dict, technicals: dict) -> str:
    """Classify a signal into a strategy type based on technical conditions.

    Evaluates conditions in priority order: MEAN_REVERSION → SWING_TRADE →
    TREND_FOLLOW → NO_TRADE. SELL/REDUCE/EXIT actions always return EXIT_SIGNAL.

    Args:
        signal: AI signal dict with symbol, action, confidence, rsi, macd_histogram,
                news_sentiment fields.
        technicals: Full technicals dict for the symbol with rsi, sma_50, sma_200,
                    current_price, macd (dict), bollinger, volume_ratio,
                    pct_from_52w_high, above_200dma fields.

    Returns:
        One of: "MEAN_REVERSION", "SWING_TRADE", "TREND_FOLLOW",
                "EXIT_SIGNAL", "NO_TRADE".
    """
    action = signal.get("action", "").upper()

    if action in ("SELL", "REDUCE", "EXIT"):
        return "EXIT_SIGNAL"

    symbol = signal.get("symbol", "")
    rsi = technicals.get("rsi", 0.0)
    above_200dma = technicals.get("above_200dma", False)
    pct_from_52w_high = technicals.get("pct_from_52w_high", 0.0)
    volume_ratio = technicals.get("volume_ratio", 0.0)
    current_price = technicals.get("current_price", 0.0)
    sma_50 = technicals.get("sma_50", 0.0)
    sma_200 = technicals.get("sma_200", 0.0)
    macd_dict = technicals.get("macd", {})
    macd_line = macd_dict.get("macd", 0.0) if isinstance(macd_dict, dict) else 0.0
    macd_histogram = macd_dict.get("histogram", 0.0) if isinstance(macd_dict, dict) else 0.0

    if action == "BUY":
        # MEAN_REVERSION — highest priority
        if (
            symbol in NIFTY50_SYMBOLS
            and rsi <= 38
            and above_200dma is True
            and pct_from_52w_high <= -10
            and pct_from_52w_high >= -30
        ):
            return "MEAN_REVERSION"

        # SWING_TRADE
        if (
            28 <= rsi <= 48
            and above_200dma is True
            and macd_histogram > 0
            and volume_ratio >= 1.2
            and pct_from_52w_high <= -8
        ):
            return "SWING_TRADE"

        # TREND_FOLLOW
        if (
            42 <= rsi <= 60
            and current_price > sma_50
            and sma_50 > sma_200
            and macd_line > 0
            and pct_from_52w_high >= -18
        ):
            return "TREND_FOLLOW"

    return "NO_TRADE"


def validate_entry(
    strategy_type: str, signal: dict, technicals: dict
) -> tuple[bool, str]:
    """Validate that all entry conditions are met for the given strategy.

    Args:
        strategy_type: Output of classify_strategy().
        signal: AI signal dict.
        technicals: Full technicals dict for the symbol.

    Returns:
        (True, "") if all rules pass; (False, "reason") on first failure.
    """
    if strategy_type == "NO_TRADE":
        return False, "No matching strategy"

    rsi = technicals.get("rsi", 0.0)
    above_200dma = technicals.get("above_200dma", False)
    pct_from_52w_high = technicals.get("pct_from_52w_high", 0.0)
    volume_ratio = technicals.get("volume_ratio", 0.0)
    current_price = technicals.get("current_price", 0.0)
    sma_50 = technicals.get("sma_50", 0.0)
    sma_200 = technicals.get("sma_200", 0.0)
    macd_dict = technicals.get("macd", {})
    macd_line = macd_dict.get("macd", 0.0) if isinstance(macd_dict, dict) else 0.0
    macd_histogram = macd_dict.get("histogram", 0.0) if isinstance(macd_dict, dict) else 0.0

    symbol = signal.get("symbol", "")
    confidence = float(signal.get("confidence", 0.0))
    news_sentiment = signal.get("news_sentiment", "NEUTRAL")
    action = signal.get("action", "").upper()

    if strategy_type == "MEAN_REVERSION":
        if rsi > 38:
            return False, "RSI not oversold enough"
        if above_200dma is not True:
            return False, "Below 200 DMA"
        if symbol not in NIFTY50_SYMBOLS:
            return False, "Not a Nifty50 stock"
        if pct_from_52w_high > -10:
            return False, "Insufficient pullback"
        if pct_from_52w_high < -30:
            return False, "Stock in freefall"
        if news_sentiment == "BEARISH":
            return False, "Negative news catalyst"
        if confidence < 0.75:
            return False, "Confidence below threshold"
        return True, ""

    if strategy_type == "SWING_TRADE":
        if not (28 <= rsi <= 48):
            return False, "RSI out of swing range"
        if above_200dma is not True:
            return False, "Below 200 DMA"
        if macd_histogram <= 0:
            return False, "MACD not bullish"
        if volume_ratio < 1.2:
            return False, "Insufficient volume"
        if pct_from_52w_high > -8:
            return False, "Insufficient pullback"
        if news_sentiment == "BEARISH":
            return False, "Negative news catalyst"
        if confidence < 0.75:
            return False, "Confidence below threshold"
        return True, ""

    if strategy_type == "TREND_FOLLOW":
        if not (42 <= rsi <= 62):
            return False, "RSI out of trend range"
        if current_price <= sma_50:
            return False, "Price below SMA50"
        if sma_50 <= sma_200:
            return False, "SMA50 below SMA200"
        if macd_line <= 0:
            return False, "MACD negative"
        if pct_from_52w_high < -18:
            return False, "Too far from highs"
        if confidence < 0.75:
            return False, "Confidence below threshold"
        return True, ""

    if strategy_type == "EXIT_SIGNAL":
        if confidence < 0.70:
            return False, "Exit confidence too low"
        if action not in ("SELL", "REDUCE", "EXIT"):
            return False, "Invalid exit action"
        return True, ""

    return False, "No matching strategy"
