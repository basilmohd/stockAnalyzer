"""Week 7 test suite — scanner, health score, safe_run hardening.
All 13 tests pass with USE_MOCK=true / USE_MOCK_AI=true.
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture(scope="module", autouse=True)
def ensure_mock_env():
    """Force mock mode for the entire test module."""
    with patch.dict(os.environ, {"USE_MOCK": "true", "USE_MOCK_AI": "true"}):
        import config
        config.USE_MOCK = True
        config.USE_MOCK_AI = True
        yield


# ── 1. fetch_screener_data mock returns dict ──────────────────────────────────

def test_fetch_screener_data_mock_returns_dict():
    """fetch_screener_data returns dict with required keys in mock mode."""
    import config
    config.USE_MOCK = True
    from data.screener import fetch_screener_data

    result = fetch_screener_data("RELIANCE")

    assert isinstance(result, dict)
    for key in ("symbol", "rsi", "sma_200", "above_200dma", "news_sentiment"):
        assert key in result, f"Missing key '{key}' in screener result"


# ── 2. apply_opportunity_filters pass ────────────────────────────────────────

def test_apply_opportunity_filters_pass():
    """A stock meeting all five criteria passes the opportunity filter."""
    from data.screener import apply_opportunity_filters

    data = {
        "symbol": "TESTSTOCK",
        "rsi": 35.0,
        "above_200dma": True,
        "pct_from_52w_high": -15.0,
        "news_sentiment": "BULLISH",
    }
    assert apply_opportunity_filters(data) is True


# ── 3. apply_opportunity_filters fail RSI too high ────────────────────────────

def test_apply_opportunity_filters_fail_rsi_too_high():
    """RSI >= 45 rejects the stock even if other criteria pass."""
    from data.screener import apply_opportunity_filters

    data = {
        "symbol": "TESTSTOCK",
        "rsi": 60.0,
        "above_200dma": True,
        "pct_from_52w_high": -15.0,
        "news_sentiment": "NEUTRAL",
    }
    assert apply_opportunity_filters(data) is False


# ── 4. apply_opportunity_filters fail below 200DMA ───────────────────────────

def test_apply_opportunity_filters_fail_below_200dma():
    """above_200dma=False rejects the stock even if other criteria pass."""
    from data.screener import apply_opportunity_filters

    data = {
        "symbol": "TESTSTOCK",
        "rsi": 35.0,
        "above_200dma": False,
        "pct_from_52w_high": -15.0,
        "news_sentiment": "NEUTRAL",
    }
    assert apply_opportunity_filters(data) is False


# ── 5. apply_opportunity_filters fail bearish news ───────────────────────────

def test_apply_opportunity_filters_fail_bearish_news():
    """BEARISH news_sentiment rejects the stock even if other criteria pass."""
    from data.screener import apply_opportunity_filters

    data = {
        "symbol": "TESTSTOCK",
        "rsi": 35.0,
        "above_200dma": True,
        "pct_from_52w_high": -15.0,
        "news_sentiment": "BEARISH",
    }
    assert apply_opportunity_filters(data) is False


# ── 6. run_opportunity_scan returns max 2 ─────────────────────────────────────

def test_run_opportunity_scan_returns_max_2():
    """run_opportunity_scan caps results at MAX_OPPORTUNITIES_PER_DAY (2)."""
    from agent.scanner import run_opportunity_scan

    null_redis = MagicMock()
    null_redis.get.return_value = None
    null_redis.setex.return_value = True

    with patch("agent.scanner._redis", null_redis):
        result = run_opportunity_scan()

    assert len(result) <= 2


# ── 7. format_opportunity_telegram contains symbol ───────────────────────────

def test_format_opportunity_telegram_contains_symbol():
    """format_opportunity_telegram output includes the opportunity symbol."""
    from agent.scanner import format_opportunity_telegram

    opp = {
        "symbol": "RELIANCE",
        "sector": "Energy",
        "rsi": 32.5,
        "sma_200": 2400.0,
        "pct_from_52w_high": -15.0,
        "news_sentiment": "NEUTRAL",
        "current_price": 2500.0,
    }
    text = format_opportunity_telegram(opp)
    assert "RELIANCE" in text


# ── 8. compute_health_score total in range ────────────────────────────────────

def test_compute_health_score_total_in_range():
    """compute_health_score total_score is between 0 and 100."""
    from agent.health import compute_health_score

    mock_holdings = [
        {
            "tradingsymbol": "ICICIBANK",
            "pnl_pct": 5.0,
            "sl_distance_pct": 10.0,
            "sl_status": "OK",
            "value": 100_000.0,
            "pnl": 5_000.0,
            "weight_pct": 15.0,
        }
    ]
    with patch("agent.health.get_holdings_with_sl_status", return_value=mock_holdings), \
         patch("data.technicals.get_technicals_for_holdings", return_value={}), \
         patch("agent.health.fetch_news_for_symbol", return_value=[]), \
         patch("agent.health.compute_sentiment_score", return_value={"sentiment_label": "NEUTRAL"}):
        result = compute_health_score()

    assert 0 <= result["total_score"] <= 100


# ── 9. compute_health_score has four dimensions ───────────────────────────────

def test_compute_health_score_has_four_dimensions():
    """compute_health_score result contains all four dimension keys."""
    from agent.health import compute_health_score

    mock_holdings = [
        {
            "tradingsymbol": "INFY",
            "pnl_pct": 3.0,
            "sl_distance_pct": 8.0,
            "sl_status": "OK",
            "value": 80_000.0,
            "pnl": 2_400.0,
            "weight_pct": 10.0,
        }
    ]
    with patch("agent.health.get_holdings_with_sl_status", return_value=mock_holdings), \
         patch("data.technicals.get_technicals_for_holdings", return_value={}), \
         patch("agent.health.fetch_news_for_symbol", return_value=[]), \
         patch("agent.health.compute_sentiment_score", return_value={"sentiment_label": "NEUTRAL"}):
        result = compute_health_score()

    for key in ("diversification", "momentum", "risk", "quality"):
        assert key in result, f"Missing dimension key: {key}"


# ── 10. health_score grade mapping ────────────────────────────────────────────

def test_health_score_grade_mapping():
    """_get_grade maps scores to the correct letter grades."""
    from agent.health import _get_grade

    assert _get_grade(92) == "A+"
    assert _get_grade(75) == "B+"
    assert _get_grade(55) == "C"


# ── 11. format_health_telegram contains score ─────────────────────────────────

def test_format_health_telegram_contains_score():
    """format_health_telegram output includes the total_score value."""
    from agent.health import format_health_telegram

    health = {
        "total_score": 78,
        "grade": "B+",
        "diversification": {"score": 20, "comment": "Well diversified"},
        "momentum": {"score": 18, "comment": "Strong trend"},
        "risk": {"score": 22, "comment": "Good SL distances"},
        "quality": {"score": 18, "comment": "Healthy RSI zone"},
        "top_concern": "RSI quality below ideal",
    }
    text = format_health_telegram(health)
    assert "78" in text


# ── 12. safe_run catches exception ────────────────────────────────────────────

def test_safe_run_catches_exception():
    """safe_run returns None when the wrapped function raises — never re-raises."""
    from core.exception_handler import safe_run

    def raising_fn():
        raise ValueError("intentional test error")

    with patch("core.exception_handler._send_error_alert"):
        result = asyncio.run(safe_run("test_job", raising_fn))

    assert result is None


# ── 13. safe_run returns value on success ─────────────────────────────────────

def test_safe_run_returns_value_on_success():
    """safe_run returns the wrapped function's return value on success."""
    from core.exception_handler import safe_run

    def returning_fn():
        return 42

    result = asyncio.run(safe_run("test_job", returning_fn))
    assert result == 42
