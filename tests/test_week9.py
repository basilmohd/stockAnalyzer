"""Week 9 test suite — position sizing, portfolio guards, and ActionLog journalling.

The 10 spec tests cover calculate_position, check_guards, and update_action_log.
A small "regression extras" section guards the safe_run/errors.log observability,
the SEND_FAILED ordering fix, and the Telegram position block built this week.

All tests pass with USE_MOCK=true / USE_MOCK_AI=true.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def fixed_capital(monkeypatch):
    """Pin capital/risk config to documented defaults so sizing math is deterministic.

    sizing.py / portfolio_guard.py read config.* at call time, so monkeypatching
    config here overrides any local .env values for the duration of each test.
    """
    import config
    monkeypatch.setattr(config, "TOTAL_CAPITAL", 25000.0)
    monkeypatch.setattr(config, "MAX_RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(config, "MAX_POSITION_PCT", 0.25)
    monkeypatch.setattr(config, "CASH_RESERVE_PCT", 0.20)
    monkeypatch.setattr(config, "MAX_OPEN_POSITIONS", 4)
    monkeypatch.setattr(config, "MAX_SAME_SECTOR", 2)
    monkeypatch.setattr(config, "WEEKLY_LOSS_LIMIT", 0.05)
    monkeypatch.setattr(config, "MIN_ORDER_VALUE", 2000.0)


def _summary(open_count=0, symbols=None, by_sector=None, total_value=0.0, week_pnl=0.0):
    return {
        "open_count": open_count,
        "symbols": symbols or [],
        "by_sector": by_sector or {},
        "total_value": total_value,
        "week_pnl": week_pnl,
    }


def _cap(deployable=14000.0):
    return {
        "total_capital": 25000.0, "open_positions_value": 6000.0,
        "available": 19000.0, "reserve_required": 5000.0, "deployable": deployable,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 1–4 · calculate_position
# ═════════════════════════════════════════════════════════════════════════════

def test_calculate_position_basic():
    """500/480 (4% stop): risk ₹500 → ₹12.5k raw → capped at ₹6.25k → qty 12."""
    from agent.sizing import calculate_position
    pos = calculate_position(entry_price=500, stop_loss_price=480, strategy_type="SWING_TRADE")
    assert pos["valid"] is True
    assert pos["quantity"] == 12
    assert pos["max_loss"] <= 500 * 1.01  # at most ~ the risk budget


def test_calculate_position_capped_at_max_pct():
    """A 1% stop would size huge; must cap at MAX_POSITION_PCT (25% of ₹25k)."""
    from agent.sizing import calculate_position
    pos = calculate_position(entry_price=100, stop_loss_price=99, strategy_type="SWING_TRADE")
    assert pos["position_value"] <= 25000 * 0.25 + 1


def test_calculate_position_invalid_stop_loss():
    """A stop above entry has no downside distance → invalid."""
    from agent.sizing import calculate_position
    pos = calculate_position(entry_price=500, stop_loss_price=510, strategy_type="SWING_TRADE")
    assert pos["valid"] is False
    assert "stop loss" in pos["reason"].lower()


def test_calculate_position_below_min_order_value():
    """A high-priced share floors to a position too small to deploy → invalid."""
    from agent.sizing import calculate_position
    pos = calculate_position(entry_price=24000, stop_loss_price=23000, strategy_type="SWING_TRADE")
    assert pos["valid"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 5–9 · check_guards
# ═════════════════════════════════════════════════════════════════════════════

def test_guard_blocks_invalid_position():
    from agent.portfolio_guard import check_guards
    signal = {"symbol": "INFY", "strategy_type": "SWING_TRADE"}
    position = {"valid": False, "reason": "Invalid stop loss"}
    passed, reason = check_guards(signal, position)
    assert passed is False


def test_guard_blocks_duplicate_symbol():
    from agent import portfolio_guard as g
    signal = {"symbol": "INFY", "strategy_type": "SWING_TRADE"}
    position = {"valid": True, "position_value": 5000, "quantity": 10}
    with patch.object(g, "get_open_positions_summary", return_value=_summary(open_count=1, symbols=["INFY"])), \
         patch.object(g, "get_available_capital", return_value=_cap()):
        passed, reason = g.check_guards(signal, position)
    assert passed is False
    assert "already held" in reason.lower()


def test_guard_blocks_sector_concentration():
    from agent import portfolio_guard as g
    # 2 Financials already open (HDFCBANK, ICICIBANK); AXISBANK is also Financials.
    signal = {"symbol": "AXISBANK", "strategy_type": "SWING_TRADE"}
    position = {"valid": True, "position_value": 5000, "quantity": 10}
    summary = _summary(open_count=2, symbols=["HDFCBANK", "ICICIBANK"], by_sector={"Financials": 2})
    with patch.object(g, "get_open_positions_summary", return_value=summary), \
         patch.object(g, "get_available_capital", return_value=_cap()):
        passed, reason = g.check_guards(signal, position)
    assert passed is False
    assert "sector" in reason.lower()


def test_guard_blocks_max_open_positions():
    from agent import portfolio_guard as g
    signal = {"symbol": "TITAN", "strategy_type": "SWING_TRADE"}
    position = {"valid": True, "position_value": 3000, "quantity": 5}
    with patch.object(g, "get_open_positions_summary", return_value=_summary(open_count=4)), \
         patch.object(g, "get_available_capital", return_value=_cap()):
        passed, reason = g.check_guards(signal, position)
    assert passed is False
    assert "max open" in reason.lower()


def test_guard_passes_clean_signal():
    from agent import portfolio_guard as g
    signal = {"symbol": "TITAN", "strategy_type": "SWING_TRADE"}
    position = {"valid": True, "position_value": 3000, "quantity": 5}
    with patch.object(g, "get_open_positions_summary", return_value=_summary()), \
         patch.object(g, "get_available_capital", return_value=_cap()):
        passed, reason = g.check_guards(signal, position)
    assert passed is True
    assert reason == ""


# ═════════════════════════════════════════════════════════════════════════════
# 10 · update_action_log
# ═════════════════════════════════════════════════════════════════════════════

def test_update_action_log_on_approve():
    """Journalling flips a PENDING ActionLog → APPROVED with a response time."""
    from agent.journal import update_action_log
    from core.db import get_db
    from models.action_log import ActionLog

    sym = "T9JOURNAL"
    signal_id = 987654
    sent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=8)
    with get_db() as db:
        row = ActionLog(
            signal_id=signal_id, symbol=sym, strategy_type="SWING_TRADE",
            signal_action="BUY", confidence=0.8, entry_price=500.0,
            suggested_qty=12, action_taken="PENDING", telegram_sent_at=sent,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        log_id = row.id

    try:
        assert update_action_log(signal_id, "APPROVED") == log_id
        with get_db() as db:
            r = db.query(ActionLog).filter(ActionLog.id == log_id).first()
        assert r.action_taken == "APPROVED"
        assert r.action_taken_at is not None
        assert r.response_time_sec is not None and r.response_time_sec >= 0
    finally:
        with get_db() as db:
            db.query(ActionLog).filter(ActionLog.symbol == sym).delete()
            db.commit()


# ═════════════════════════════════════════════════════════════════════════════
# Regression extras — features built this week (safe_run, SEND_FAILED, UI block)
# ═════════════════════════════════════════════════════════════════════════════

def test_errors_log_captures_warning_from_any_logger():
    """The root errors.log handler captures WARNING+ from ANY logger."""
    import core.exception_handler  # noqa: F401 — ensures handler is installed
    from core.exception_handler import _ERRORS_LOG

    marker = "WK9_ARBITRARY_LOGGER_WARNING"
    logging.getLogger("some.unrelated.module").warning(marker)
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass

    assert os.path.exists(_ERRORS_LOG)
    with open(_ERRORS_LOG, encoding="utf-8") as fh:
        assert marker in fh.read()


def test_pipeline_send_failure_writes_send_failed_not_pending():
    """If send_signal_alerts raises, the row is SEND_FAILED with no telegram_sent_at."""
    from data.technicals import IndicatorResult
    from agent.signals import run_signal_pipeline
    from core.db import get_db
    from models.action_log import ActionLog

    sym = "T9SENDFAIL"
    signal = {
        "symbol": sym, "action": "BUY", "confidence": 0.82,
        "news_sentiment": "BULLISH", "rsi": 39.0, "macd_histogram": 0.7,
        "reason": "wk9 test", "urgency": "HIGH",
    }
    ind = IndicatorResult(
        rsi=39.0, macd=1.5, macd_signal=0.8,
        bb_upper=1200.0, bb_middle=1150.0, bb_lower=1080.0,
        sma_50=1150.0, sma_200=1080.0, above_50sma=True, above_200sma=True,
        volume_ratio=1.5, price_vs_52w_high_pct=-11.0, price_vs_52w_low_pct=8.0,
        last_close=1120.0, computed_at=datetime.now().isoformat(),
    )
    null_redis = MagicMock()
    null_redis.get.return_value = None
    null_redis.setex.return_value = True
    failing_send = AsyncMock(side_effect=RuntimeError("telegram down"))

    with patch("agent.signals.run_signal_scan", return_value=[signal]), \
         patch("agent.signals.filter_signals", return_value=[signal]), \
         patch("agent.signals.get_technicals_for_holdings", return_value={sym: ind}), \
         patch("agent.signals.classify_strategy", return_value="SWING_TRADE"), \
         patch("agent.signals.validate_entry", return_value=(True, "")), \
         patch("agent.signals.check_guards", return_value=(True, "")), \
         patch("agent.signals.send_signal_alerts", failing_send), \
         patch("agent.signals._redis", null_redis):
        result = asyncio.run(run_signal_pipeline())

    assert result["send_failed"] is True
    assert result["alerts_sent"] == 0

    with get_db() as db:
        rows = (
            db.query(ActionLog)
            .filter(ActionLog.symbol == sym, ActionLog.action_taken == "SEND_FAILED")
            .all()
        )
    assert len(rows) >= 1
    assert rows[-1].telegram_sent_at is None
    assert rows[-1].suggested_qty == 5  # risk-sized qty still recorded


def test_format_signal_telegram_includes_position_block():
    """The Telegram message renders the Week 9 💰 Position block."""
    from agent.signals import format_signal_telegram
    signal = {
        "symbol": "INFY", "action": "BUY", "confidence": 0.80, "reason": "test",
        "strategy_type": "SWING_TRADE", "current_price": 400.0,
        "suggested_sl": 384.0, "suggested_target": 428.0,
        "quantity": 15, "position_value": 6000.0, "capital_used_pct": 0.24,
        "max_loss": 240.0, "max_loss_pct": 0.0096,
    }
    text = format_signal_telegram(signal)
    assert "Position:" in text
    assert "Qty: 15 shares" in text
    assert "24% of capital" in text
    assert "1.0%" in text  # max_loss_pct rendered with one decimal
