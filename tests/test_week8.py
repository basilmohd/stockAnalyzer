"""Week 8 test suite — strategy classifier, entry validator, ActionLog DB writes.
All 10 tests pass with USE_MOCK=true / USE_MOCK_AI=true.
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Shared mock technicals fixtures ────────────────────────────────────────────
# RSI=39.0 (not 38.0) so MEAN_REVERSION (rsi <= 38) doesn't shadow SWING_TRADE
# for a Nifty50 symbol. All other values match the original spec.

MOCK_TECHNICALS_MEAN_REVERSION = {
    "rsi": 34.0, "sma_50": 1050.0, "sma_200": 980.0,
    "current_price": 1020.0, "above_200dma": True,
    "macd": {"macd": -2.1, "signal": -3.0, "histogram": 0.9},
    "volume_ratio": 1.4, "pct_from_52w_high": -14.0,
    "bollinger": {"upper": 1100.0, "middle": 1050.0,
                  "lower": 980.0, "percent_b": 0.3},
}

MOCK_TECHNICALS_SWING = {
    "rsi": 39.0, "sma_50": 1150.0, "sma_200": 1080.0,
    "current_price": 1120.0, "above_200dma": True,
    "macd": {"macd": 1.5, "signal": 0.8, "histogram": 0.7},
    "volume_ratio": 1.5, "pct_from_52w_high": -11.0,
    "bollinger": {"upper": 1200.0, "middle": 1150.0,
                  "lower": 1080.0, "percent_b": 0.35},
}

MOCK_TECHNICALS_NO_TRADE = {
    "rsi": 78.0, "sma_50": 1200.0, "sma_200": 1100.0,
    "current_price": 1250.0, "above_200dma": True,
    "macd": {"macd": 5.0, "signal": 4.0, "histogram": 1.0},
    "volume_ratio": 0.8, "pct_from_52w_high": -2.0,
    "bollinger": {"upper": 1280.0, "middle": 1200.0,
                  "lower": 1100.0, "percent_b": 0.9},
}


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and initialise DB tables before any test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


def _null_redis() -> MagicMock:
    m = MagicMock()
    m.get.return_value = None
    m.setex.return_value = True
    return m


# ── 1. classify_strategy → MEAN_REVERSION ─────────────────────────────────────

def test_classify_mean_reversion():
    """ICICIBANK (Nifty50) with RSI=34, above 200DMA, deep pullback → MEAN_REVERSION."""
    from agent.strategy import classify_strategy

    signal = {"symbol": "ICICIBANK", "action": "BUY", "confidence": 0.82,
              "news_sentiment": "NEUTRAL"}
    result = classify_strategy(signal, MOCK_TECHNICALS_MEAN_REVERSION)
    assert result == "MEAN_REVERSION"


# ── 2. classify_strategy → SWING_TRADE ────────────────────────────────────────

def test_classify_swing_trade():
    """INFY with RSI=39, bullish MACD histogram, strong volume → SWING_TRADE."""
    from agent.strategy import classify_strategy

    signal = {"symbol": "INFY", "action": "BUY", "confidence": 0.78,
              "news_sentiment": "BULLISH"}
    result = classify_strategy(signal, MOCK_TECHNICALS_SWING)
    assert result == "SWING_TRADE"


# ── 3. classify_strategy → NO_TRADE (overbought) ──────────────────────────────

def test_classify_no_trade_overbought():
    """BUY signal with RSI=78 hits none of the entry strategies → NO_TRADE."""
    from agent.strategy import classify_strategy

    signal = {"symbol": "HDFCBANK", "action": "BUY", "confidence": 0.80,
              "news_sentiment": "BULLISH"}
    result = classify_strategy(signal, MOCK_TECHNICALS_NO_TRADE)
    assert result == "NO_TRADE"


# ── 4. classify_strategy → EXIT_SIGNAL (SELL action) ──────────────────────────

def test_classify_exit_signal():
    """SELL action always returns EXIT_SIGNAL regardless of technicals."""
    from agent.strategy import classify_strategy

    signal = {"symbol": "TATAMOTORS", "action": "SELL", "confidence": 0.85,
              "news_sentiment": "BEARISH"}
    result = classify_strategy(signal, MOCK_TECHNICALS_NO_TRADE)
    assert result == "EXIT_SIGNAL"


# ── 5. validate_entry MEAN_REVERSION → pass ───────────────────────────────────

def test_validate_entry_mean_reversion_pass():
    """All MEAN_REVERSION entry conditions met for ICICIBANK → (True, '')."""
    from agent.strategy import validate_entry

    signal = {"symbol": "ICICIBANK", "action": "BUY", "confidence": 0.82,
              "news_sentiment": "NEUTRAL",
              "rsi": 34.0, "macd_histogram": 0.9}
    passed, reason = validate_entry("MEAN_REVERSION", signal,
                                    MOCK_TECHNICALS_MEAN_REVERSION)
    assert passed is True
    assert reason == ""


# ── 6. validate_entry MEAN_REVERSION → fail (not Nifty50) ─────────────────────

def test_validate_entry_mean_reversion_fail_not_nifty50():
    """YESBANK is not in Nifty50 — MEAN_REVERSION validation must reject it."""
    from agent.strategy import validate_entry

    signal = {"symbol": "YESBANK", "action": "BUY", "confidence": 0.82,
              "news_sentiment": "NEUTRAL",
              "rsi": 34.0, "macd_histogram": 0.9}
    passed, reason = validate_entry("MEAN_REVERSION", signal,
                                    MOCK_TECHNICALS_MEAN_REVERSION)
    assert passed is False
    assert "Nifty50" in reason


# ── 7. validate_entry SWING_TRADE → fail (bearish news) ───────────────────────

def test_validate_entry_swing_fail_bearish_news():
    """Negative news sentiment blocks a SWING_TRADE entry."""
    from agent.strategy import validate_entry

    signal = {"symbol": "INFY", "action": "BUY", "confidence": 0.80,
              "news_sentiment": "BEARISH",
              "rsi": 38.0, "macd_histogram": 0.7}
    technicals = {**MOCK_TECHNICALS_SWING}
    passed, reason = validate_entry("SWING_TRADE", signal, technicals)
    assert passed is False
    assert "news" in reason.lower()


# ── 8. validate_entry → fail (low confidence) ─────────────────────────────────

def test_validate_entry_low_confidence_rejected():
    """Confidence below 0.75 threshold blocks any strategy entry."""
    from agent.strategy import validate_entry

    signal = {"symbol": "INFY", "action": "BUY", "confidence": 0.60,
              "news_sentiment": "BULLISH",
              "rsi": 38.0, "macd_histogram": 0.7}
    passed, reason = validate_entry("SWING_TRADE", signal,
                                    MOCK_TECHNICALS_SWING)
    assert passed is False
    assert "confidence" in reason.lower()


# ── 9. AUTO_REJECTED ActionLog written to DB ──────────────────────────────────

def test_action_log_auto_rejected_written_to_db():
    """Pipeline writes AUTO_REJECTED ActionLog with rejection_reason when validate_entry fails."""
    from data.technicals import IndicatorResult
    from agent.signals import run_signal_pipeline
    from core.db import get_db
    from models.action_log import ActionLog

    unique_sym = "T8SYM09A"
    signal = {
        "symbol": unique_sym, "action": "BUY", "confidence": 0.82,
        "news_sentiment": "NEUTRAL", "rsi": 34.0, "macd_histogram": 0.9,
        "reason": "test", "urgency": "HIGH",
    }
    mock_ind = IndicatorResult(
        rsi=34.0, macd=-2.1, macd_signal=-3.0,
        bb_upper=1100.0, bb_middle=1050.0, bb_lower=980.0,
        sma_50=1050.0, sma_200=980.0,
        above_50sma=True, above_200sma=True,
        volume_ratio=1.4, price_vs_52w_high_pct=-14.0,
        price_vs_52w_low_pct=5.0, last_close=1020.0,
        computed_at=datetime.now().isoformat(),
    )

    with patch("agent.signals.run_signal_scan", return_value=[signal]), \
         patch("agent.signals.filter_signals", return_value=[signal]), \
         patch("agent.signals.get_technicals_for_holdings", return_value={unique_sym: mock_ind}), \
         patch("agent.signals.classify_strategy", return_value="MEAN_REVERSION"), \
         patch("agent.signals.validate_entry", return_value=(False, "Test rejection")), \
         patch("agent.signals.send_signal_alerts", new_callable=AsyncMock), \
         patch("agent.signals._redis", _null_redis()):
        asyncio.run(run_signal_pipeline())

    with get_db() as db:
        records = (
            db.query(ActionLog)
            .filter(ActionLog.symbol == unique_sym,
                    ActionLog.action_taken == "AUTO_REJECTED")
            .all()
        )

    assert len(records) >= 1
    assert records[0].rejection_reason is not None


# ── 10. PENDING ActionLog written when alert reaches Telegram ─────────────────

def test_action_log_pending_written_on_telegram_send():
    """Pipeline writes PENDING ActionLog with telegram_sent_at after a validated signal."""
    from data.technicals import IndicatorResult
    from agent.signals import run_signal_pipeline
    from core.db import get_db
    from models.action_log import ActionLog

    unique_sym = "T8SYM10A"
    signal = {
        "symbol": unique_sym, "action": "BUY", "confidence": 0.82,
        "news_sentiment": "BULLISH", "rsi": 39.0, "macd_histogram": 0.7,
        "reason": "test", "urgency": "HIGH",
    }
    mock_ind = IndicatorResult(
        rsi=39.0, macd=1.5, macd_signal=0.8,
        bb_upper=1200.0, bb_middle=1150.0, bb_lower=1080.0,
        sma_50=1150.0, sma_200=1080.0,
        above_50sma=True, above_200sma=True,
        volume_ratio=1.5, price_vs_52w_high_pct=-11.0,
        price_vs_52w_low_pct=8.0, last_close=1120.0,
        computed_at=datetime.now().isoformat(),
    )

    with patch("agent.signals.run_signal_scan", return_value=[signal]), \
         patch("agent.signals.filter_signals", return_value=[signal]), \
         patch("agent.signals.get_technicals_for_holdings", return_value={unique_sym: mock_ind}), \
         patch("agent.signals.classify_strategy", return_value="SWING_TRADE"), \
         patch("agent.signals.validate_entry", return_value=(True, "")), \
         patch("agent.signals.send_signal_alerts", new_callable=AsyncMock), \
         patch("agent.signals._redis", _null_redis()):
        asyncio.run(run_signal_pipeline())

    with get_db() as db:
        records = (
            db.query(ActionLog)
            .filter(ActionLog.symbol == unique_sym,
                    ActionLog.action_taken == "PENDING")
            .all()
        )

    assert len(records) >= 1
    assert records[0].telegram_sent_at is not None
