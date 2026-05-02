"""Week 4 test suite — technical indicators and news sentiment pipeline.
All 10 tests must pass with USE_MOCK=true.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and DB tables before any test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


# ── Technicals tests ──────────────────────────────────────────────────────────

def test_fetch_ohlc_returns_dataframe():
    """fetch_ohlc returns a pandas DataFrame with expected OHLCV columns."""
    from data.technicals import fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 1270529)
    assert isinstance(df, pd.DataFrame)
    for col in ["open", "high", "low", "close", "volume"]:
        assert col in df.columns, f"Missing column: {col}"


def test_ohlc_has_200_plus_rows():
    """fetch_ohlc returns ≥200 rows (mock always generates exactly 200)."""
    from data.technicals import fetch_ohlc
    df = fetch_ohlc("INFY", 408065)
    assert len(df) >= 200, f"Expected ≥200 rows, got {len(df)}"


def test_compute_indicators_returns_result():
    """compute_indicators returns an IndicatorResult dataclass instance."""
    from data.technicals import IndicatorResult, compute_indicators, fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 1270529)
    result = compute_indicators(df)
    assert isinstance(result, IndicatorResult)


def test_rsi_in_valid_range():
    """RSI value must be between 0 and 100."""
    from data.technicals import compute_indicators, fetch_ohlc
    df = fetch_ohlc("INFY", 408065)
    result = compute_indicators(df)
    assert 0.0 <= result.rsi <= 100.0, f"RSI out of range: {result.rsi}"


def test_above_sma_is_boolean():
    """above_50sma and above_200sma must be Python booleans (not numpy bool)."""
    from data.technicals import compute_indicators, fetch_ohlc
    df = fetch_ohlc("HDFCBANK", 341249)
    result = compute_indicators(df)
    assert isinstance(result.above_50sma, bool), f"above_50sma is {type(result.above_50sma)}"
    assert isinstance(result.above_200sma, bool), f"above_200sma is {type(result.above_200sma)}"


def test_get_technicals_for_all_holdings():
    """get_technicals_for_holdings returns a dict with all 8 mock holdings."""
    from data.technicals import get_technicals_for_holdings
    mock_redis = _make_null_redis()
    with patch("data.technicals._redis", mock_redis):
        results = get_technicals_for_holdings()
    assert isinstance(results, dict)
    assert len(results) == 8, f"Expected 8 holdings, got {len(results)}"


def test_technicals_cached_in_redis():
    """get_technicals_for_holdings writes each IndicatorResult to Redis under 'indicators:<symbol>'."""
    from data.technicals import get_technicals_for_holdings
    store: dict = {}
    mock_redis = _make_store_redis(store)
    with patch("data.technicals._redis", mock_redis):
        get_technicals_for_holdings()
    cached_keys = [k for k in store if k.startswith("indicators:")]
    assert len(cached_keys) >= 1, f"No indicator keys found in store: {list(store.keys())}"


# ── News sentiment tests ──────────────────────────────────────────────────────

def test_news_sentiment_0_to_1():
    """sentiment_score returned by get_news_sentiment must be between 0 and 1."""
    from data.news import get_news_sentiment
    mock_redis = _make_null_redis()
    with patch("data.news._redis", mock_redis):
        result = get_news_sentiment("ICICIBANK")
    assert 0.0 <= result["sentiment_score"] <= 1.0, (
        f"sentiment_score out of range: {result['sentiment_score']}"
    )


def test_news_headlines_count_is_3():
    """get_news_sentiment always returns exactly 3 headline dicts."""
    from data.news import get_news_sentiment
    mock_redis = _make_null_redis()
    with patch("data.news._redis", mock_redis):
        result = get_news_sentiment("PFC")
    assert len(result["headlines"]) == 3, f"Expected 3 headlines, got {len(result['headlines'])}"
    for h in result["headlines"]:
        assert "title" in h and "description" in h and "url" in h


def test_cache_hit_returns_same_data():
    """Cached Redis payload is returned as-is without re-fetching from NewsAPI."""
    from data.news import get_news_sentiment
    expected = {
        "headlines": [
            {"title": "ICICI surges on Q4 results", "description": "Strong beat", "url": "http://example.com/1"},
            {"title": "Banking sector rally", "description": "Bullish momentum", "url": "http://example.com/2"},
            {"title": "ICICI gains market share", "description": "Positive outlook", "url": "http://example.com/3"},
        ],
        "sentiment_score": 0.8,
        "fetched_at": "2026-05-02T10:00:00",
    }
    mock_redis = _make_hit_redis(json.dumps(expected))
    with patch("data.news._redis", mock_redis):
        result = get_news_sentiment("ICICIBANK")
    assert result["sentiment_score"] == 0.8
    assert len(result["headlines"]) == 3


# ── Redis mock helpers ────────────────────────────────────────────────────────

def _make_null_redis() -> MagicMock:
    """Redis mock that always misses (simulates empty cache)."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.setex.return_value = True
    return mock


def _make_store_redis(store: dict) -> MagicMock:
    """Redis mock that records setex calls into *store* for assertion."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.setex.side_effect = lambda key, ttl, val: store.update({key: val}) or True
    return mock


def _make_hit_redis(payload: str) -> MagicMock:
    """Redis mock that always returns *payload* on get (simulates warm cache)."""
    mock = MagicMock()
    mock.get.return_value = payload
    return mock


def _make_readwrite_redis() -> MagicMock:
    """Redis mock that stores on setex and returns stored values on get."""
    store: dict = {}
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    mock.setex.side_effect = lambda key, ttl, val: store.update({key: val}) or True
    return mock


# ── Missing tests from the Week 4 test plan ──────────────────────────────────

def test_fetch_ohlc_cache_hit():
    """Second call to get_technicals_for_holdings hits Redis cache; setex not called again."""
    from data.technicals import get_technicals_for_holdings
    mock_redis = _make_readwrite_redis()
    with patch("data.technicals._redis", mock_redis):
        get_technicals_for_holdings()   # first call — populates cache via setex
        mock_redis.reset_mock(side_effect=False)  # reset call counts, keep side_effect
        get_technicals_for_holdings()   # second call — should read from cache

    assert mock_redis.get.called, "Redis.get was not called on second pass"
    mock_redis.setex.assert_not_called()


def test_compute_indicators_returns_required_keys():
    """IndicatorResult contains all 10 required numeric indicator fields."""
    from dataclasses import asdict
    from data.technicals import compute_indicators, fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 1270529)
    result = compute_indicators(df)
    data = asdict(result)
    required = [
        "rsi", "macd", "macd_signal",
        "bb_upper", "bb_middle", "bb_lower",
        "sma_50", "sma_200", "volume_ratio", "last_close",
    ]
    for key in required:
        assert key in data, f"Missing key: {key}"


def test_macd_has_three_components():
    """pandas-ta MACD computation yields MACD line, signal line, and histogram columns."""
    from data.technicals import fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 1270529)
    macd_df = df.ta.macd(fast=12, slow=26, signal=9)
    cols = list(macd_df.columns)
    assert any(c.startswith("MACD_") for c in cols), f"MACD line missing in {cols}"
    assert any(c.startswith("MACDs_") for c in cols), f"MACD signal missing in {cols}"
    assert any(c.startswith("MACDh_") for c in cols), f"MACD histogram missing in {cols}"


def test_bollinger_bands_ordering():
    """Bollinger Bands must satisfy lower < middle < upper."""
    from data.technicals import compute_indicators, fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 1270529)
    result = compute_indicators(df)
    assert result.bb_lower < result.bb_middle, (
        f"BB lower ({result.bb_lower}) not < middle ({result.bb_middle})"
    )
    assert result.bb_middle < result.bb_upper, (
        f"BB middle ({result.bb_middle}) not < upper ({result.bb_upper})"
    )


def test_get_technicals_for_symbol():
    """End-to-end: ICICIBANK is in get_technicals_for_holdings result with a valid RSI."""
    from data.technicals import get_technicals_for_holdings
    mock_redis = _make_null_redis()
    with patch("data.technicals._redis", mock_redis):
        results = get_technicals_for_holdings()
    assert "ICICIBANK" in results, "ICICIBANK missing from results"
    data = results["ICICIBANK"]
    assert hasattr(data, "rsi"), "IndicatorResult missing 'rsi'"
    assert 0.0 <= data.rsi <= 100.0, f"RSI out of range: {data.rsi}"


def test_fetch_news_mock_mode():
    """fetch_news_for_symbol returns list of articles with required keys in mock mode."""
    from data.news import fetch_news_for_symbol
    mock_redis = _make_null_redis()
    with patch("data.news._redis", mock_redis):
        articles = fetch_news_for_symbol("ICICIBANK")
    assert isinstance(articles, list), "Expected a list"
    assert len(articles) > 0, "Expected at least one article"
    for article in articles:
        for key in ["title", "summary", "published_at", "source", "url"]:
            assert key in article, f"Missing key '{key}' in article: {article}"


def test_compute_sentiment_score_bullish():
    """Strongly positive articles produce a BULLISH sentiment label."""
    from data.news import compute_sentiment_score
    articles = [
        {
            "title": "Stock surges on record profit and strong beat",
            "summary": "Analysts upgrade to buy; rally continues on growth momentum",
        },
        {
            "title": "Company gains record market share with outperform outlook",
            "summary": "Revenue beat drives buy rating and rally in sector",
        },
    ]
    result = compute_sentiment_score(articles)
    assert result["sentiment_label"] == "BULLISH", (
        f"Expected BULLISH, got {result['sentiment_label']} (score={result['overall_score']})"
    )


def test_compute_sentiment_score_bearish():
    """Strongly negative articles produce a BEARISH sentiment label."""
    from data.news import compute_sentiment_score
    articles = [
        {
            "title": "Stock drops on loss concern and weak guidance miss",
            "summary": "Analysts downgrade to sell; underperform risk flagged",
        },
        {
            "title": "Revenue fall and margin cut raise concern",
            "summary": "Weak demand and risk of further drop drive underperform call",
        },
    ]
    result = compute_sentiment_score(articles)
    assert result["sentiment_label"] == "BEARISH", (
        f"Expected BEARISH, got {result['sentiment_label']} (score={result['overall_score']})"
    )
