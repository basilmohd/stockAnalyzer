"""Week 6 test suite — signal engine, order execution, approval wiring.
All 13 tests pass with USE_MOCK=true / USE_MOCK_AI=true.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and initialise DB tables before any test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _null_redis() -> MagicMock:
    m = MagicMock()
    m.get.return_value = None
    m.setex.return_value = True
    return m


def _mock_signal(
    symbol: str = "ICICIBANK",
    action: str = "BUY",
    confidence: float = 0.82,
) -> dict:
    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "reason": "Test signal reason",
        "rsi": 32.4,
        "macd_histogram": 1.8,
        "news_sentiment": "BULLISH",
        "suggested_quantity": 10,
        "urgency": "HIGH",
    }


# ── 1. run_signal_scan returns list ───────────────────────────────────────────

def test_run_signal_scan_returns_list():
    """run_signal_scan() returns a list (USE_MOCK_AI=true, no real API)."""
    from agent.signals import run_signal_scan

    mock_context = {"holdings": [{"symbol": "ICICIBANK", "pnl_pct": 3.5}]}

    with patch("agent.signals.build_claude_context", return_value=mock_context), \
         patch("agent.signals.get_technicals_for_holdings", return_value={}), \
         patch("agent.signals.get_news_sentiment_all_holdings", return_value={}):
        result = run_signal_scan()

    assert isinstance(result, list)


# ── 2. signal scan has required keys ─────────────────────────────────────────

def test_signal_scan_has_required_keys():
    """Each signal returned by run_signal_scan has symbol, action, confidence, reason."""
    from agent.signals import run_signal_scan

    mock_context = {"holdings": [{"symbol": "ICICIBANK", "pnl_pct": 3.5}]}

    with patch("agent.signals.build_claude_context", return_value=mock_context), \
         patch("agent.signals.get_technicals_for_holdings", return_value={}), \
         patch("agent.signals.get_news_sentiment_all_holdings", return_value={}):
        signals = run_signal_scan()

    assert len(signals) > 0
    for s in signals:
        for key in ("symbol", "action", "confidence", "reason"):
            assert key in s, f"Signal missing key '{key}': {s}"


# ── 3. filter_signals confidence gate ────────────────────────────────────────

def test_filter_signals_confidence_gate():
    """Only signals with confidence >= 0.75 (CONFIDENCE_THRESHOLD) pass through."""
    from agent.signals import filter_signals

    signals = [
        _mock_signal(confidence=0.50),
        _mock_signal(symbol="INFY", confidence=0.75),
        _mock_signal(symbol="TCS", confidence=0.90),
    ]
    result = filter_signals(signals)

    confidences = [s["confidence"] for s in result]
    assert 0.50 not in confidences, "0.50 confidence signal should be filtered"
    assert 0.75 in confidences
    assert 0.90 in confidences


# ── 4. filter_signals drops HOLD ─────────────────────────────────────────────

def test_filter_signals_drops_hold():
    """HOLD signals are dropped even when confidence is above threshold."""
    from agent.signals import filter_signals

    signals = [
        _mock_signal(symbol="INFY", action="HOLD", confidence=0.90),
        _mock_signal(symbol="TCS", action="BUY", confidence=0.80),
    ]
    result = filter_signals(signals)

    actions = [s["action"] for s in result]
    assert "HOLD" not in actions, "HOLD action should be filtered out"
    assert "BUY" in actions


# ── 5. filter_signals dedup keeps higher confidence ──────────────────────────

def test_filter_signals_dedup_keeps_higher_confidence():
    """When two signals exist for the same symbol, only the higher-confidence one survives."""
    from agent.signals import filter_signals

    signals = [
        _mock_signal(symbol="ICICIBANK", confidence=0.80),
        _mock_signal(symbol="ICICIBANK", confidence=0.90),
    ]
    result = filter_signals(signals)

    icici_signals = [s for s in result if s["symbol"] == "ICICIBANK"]
    assert len(icici_signals) == 1
    assert icici_signals[0]["confidence"] == 0.90


# ── 6. store_signals creates DB record ───────────────────────────────────────

def test_store_signals_creates_db_record():
    """store_signals() persists a Signal record that can be queried from SQLite."""
    from agent.signals import store_signals
    from core.db import get_db
    from models.signal import Signal

    unique_sym = "TESTSYM6"
    store_signals([_mock_signal(symbol=unique_sym)])

    with get_db() as db:
        record = db.query(Signal).filter(Signal.symbol == unique_sym).first()

    assert record is not None
    assert record.action == "BUY"
    assert 0.8 <= record.confidence <= 0.9


# ── 7. format_signal_telegram contains symbol ────────────────────────────────

def test_format_signal_telegram_contains_symbol():
    """format_signal_telegram() output includes the signal's symbol."""
    from agent.signals import format_signal_telegram

    text = format_signal_telegram(_mock_signal(symbol="HDFCBANK"))
    assert "HDFCBANK" in text


# ── 8. format_signal_telegram confidence bar ─────────────────────────────────

def test_format_signal_telegram_confidence_bar():
    """format_signal_telegram() output contains filled block characters (█)."""
    from agent.signals import format_signal_telegram

    text = format_signal_telegram(_mock_signal(confidence=0.80))
    assert "█" in text, "Confidence bar block character missing from formatted signal"


# ── 9. place_order mock returns order_id ─────────────────────────────────────

def test_place_order_mock_returns_order_id():
    """place_order in mock mode returns an order_id containing 'MOCK'."""
    from core.kite_client import KiteClient

    result = KiteClient().place_order("ICICIBANK", "BUY", 10)

    assert result.get("order_id") is not None
    assert "MOCK" in result["order_id"]
    assert result["status"] == "COMPLETE"


# ── 10. place_order mock never raises ────────────────────────────────────────

def test_place_order_mock_never_raises():
    """place_order returns an error dict for invalid inputs — never raises."""
    from core.kite_client import KiteClient

    client = KiteClient()

    result_empty = client.place_order("", "BUY", 10)
    assert result_empty["order_id"] is None
    assert result_empty["status"] == "FAILED"

    result_zero_qty = client.place_order("ICICIBANK", "BUY", 0)
    assert result_zero_qty["order_id"] is None
    assert result_zero_qty["status"] == "FAILED"


# ── 11. run_signal_pipeline returns summary ───────────────────────────────────

def test_run_signal_pipeline_returns_summary():
    """run_signal_pipeline() returns a dict with scanned, filtered, alerts_sent keys."""
    from agent.signals import run_signal_pipeline

    mock_raw = [_mock_signal(), _mock_signal(symbol="INFY", confidence=0.77)]
    mock_filtered = [_mock_signal()]

    with patch("agent.signals.run_signal_scan", return_value=mock_raw), \
         patch("agent.signals.filter_signals", return_value=mock_filtered), \
         patch("agent.signals.send_signal_alerts", new_callable=AsyncMock), \
         patch("agent.signals._redis", _null_redis()):
        result = asyncio.run(run_signal_pipeline())

    for key in ("scanned", "filtered", "alerts_sent"):
        assert key in result, f"Summary missing key: {key}"


# ── 12. pipeline summary counts are consistent ───────────────────────────────

def test_signal_pipeline_summary_counts_valid():
    """filtered count <= scanned count and alerts_sent <= filtered count."""
    from agent.signals import run_signal_pipeline

    mock_raw = [_mock_signal()] * 5
    mock_filtered = [_mock_signal()] * 3

    with patch("agent.signals.run_signal_scan", return_value=mock_raw), \
         patch("agent.signals.filter_signals", return_value=mock_filtered), \
         patch("agent.signals.send_signal_alerts", new_callable=AsyncMock), \
         patch("agent.signals._redis", _null_redis()):
        result = asyncio.run(run_signal_pipeline())

    assert result["filtered"] <= result["scanned"], (
        f"filtered ({result['filtered']}) > scanned ({result['scanned']})"
    )
    assert result["alerts_sent"] <= result["filtered"], (
        f"alerts_sent ({result['alerts_sent']}) > filtered ({result['filtered']})"
    )


# ── 13. handle_signal_execution invalid token ────────────────────────────────

def test_handle_signal_execution_invalid_token():
    """handle_signal_execution returns error dict for garbage token — never raises."""
    from routes.approval_routes import handle_signal_execution

    with patch("routes.approval_routes.send_alert", new_callable=AsyncMock):
        result = asyncio.run(handle_signal_execution("garbage-token-does-not-exist"))

    assert isinstance(result, dict)
    assert result.get("status") == "error"
