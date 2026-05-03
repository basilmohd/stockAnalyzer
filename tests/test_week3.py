"""
Week 3 test suite — stop-loss monitor, cooldown system, market-hours gate.
9 unit/mock tests + 2 integration tests (send real Telegram messages).
All 11 must pass; integration tests require TELEGRAM_BOT_TOKEN + Redis.
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DEFAULT_SL_PCT, REDIS_URL, TIMEZONE
from core.redis_client import RedisClient

IST = ZoneInfo(TIMEZONE)


@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Create data_store dir and DB tables before any test runs."""
    root = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(os.path.join(root, "data_store"), exist_ok=True)
    from core.db import init_db
    init_db()


# ── SL threshold tests ────────────────────────────────────────────────────────

def test_get_sl_threshold_default():
    """get_sl_threshold for an unknown symbol returns DEFAULT_SL_PCT (-15.0)."""
    from agent.stoploss import get_sl_threshold
    assert get_sl_threshold("RANDOMSTOCK") == DEFAULT_SL_PCT


def test_get_sl_threshold_override():
    """get_sl_threshold uses per-stock override when present in SL_OVERRIDES."""
    import config
    from agent.stoploss import get_sl_threshold
    config.SL_OVERRIDES["TESTSTOCK"] = -10.0
    try:
        assert get_sl_threshold("TESTSTOCK") == -10.0
    finally:
        del config.SL_OVERRIDES["TESTSTOCK"]


# ── check_holdings_for_sl tests ───────────────────────────────────────────────

def test_check_holdings_for_sl_mock():
    """check_holdings_for_sl returns a list; each SLBreachAlert has required fields."""
    from agent.stoploss import check_holdings_for_sl
    alerts = check_holdings_for_sl()
    assert isinstance(alerts, list)
    for alert in alerts:
        assert hasattr(alert, "symbol")
        assert hasattr(alert, "pnl_pct")
        assert hasattr(alert, "severity")
        assert hasattr(alert, "entry_price")
        assert hasattr(alert, "current_price")


def test_near_sl_stock_appears_in_alerts():
    """Holding within 3pp of -15% SL must appear in alerts as WARNING."""
    from agent.stoploss import check_holdings_for_sl
    near_sl = [{
        "tradingsymbol": "TATAMTRDVR", "instrument_token": 884993,
        "exchange": "NSE", "product": "CNC", "quantity": 52,
        "average_price": 275.06, "last_price": 240.00,
        "pnl": -1823.12, "pnl_pct": -12.74,
        "sl_price": 233.80, "sl_distance_pct": 2.65, "sl_status": "WARNING",
        "value": 12480.00, "weight_pct": 100.0,
    }]
    with patch("agent.stoploss.get_holdings_with_sl_status", return_value=near_sl):
        alerts = check_holdings_for_sl()
    symbols = [a.symbol for a in alerts]
    assert "TATAMTRDVR" in symbols, f"Expected TATAMTRDVR in SL alerts, got: {symbols}"
    alert = next(a for a in alerts if a.symbol == "TATAMTRDVR")
    assert alert.severity in ("WARNING", "BREACH"), (
        f"Expected WARNING or BREACH, got: {alert.severity}"
    )


def test_healthy_stock_not_in_alerts():
    """Stocks well above the SL threshold must not appear in alerts."""
    from agent.stoploss import check_holdings_for_sl
    alerts = check_holdings_for_sl()
    symbols = [a.symbol for a in alerts]
    assert "IRCTC" not in symbols, "IRCTC (+47.7%) should not be in SL alerts"
    assert "RELIANCE" not in symbols, "RELIANCE (+49%) should not be in SL alerts"


# ── Cooldown tests ────────────────────────────────────────────────────────────

def _make_memory_redis():
    """Return a MagicMock that behaves like RedisClient using an in-memory dict."""
    from unittest.mock import MagicMock
    store: dict = {}
    mock = MagicMock()
    mock.get.side_effect = lambda key: store.get(key)
    mock.setex.side_effect = lambda key, ttl, val: store.update({key: val}) or True
    mock.delete.side_effect = lambda key: store.pop(key, None) or True
    return mock


def test_cooldown_set_and_check():
    """set_cooldown/is_on_cooldown correctly gate re-alerts (mocked Redis)."""
    from agent.stoploss import is_on_cooldown, set_cooldown
    mock_redis = _make_memory_redis()
    with patch("agent.stoploss._redis", mock_redis):
        assert is_on_cooldown("TESTCOOL") is False
        set_cooldown("TESTCOOL")
        assert is_on_cooldown("TESTCOOL") is True


def test_cooldown_prevents_double_alert():
    """After set_cooldown, is_on_cooldown returns True for that symbol."""
    from agent.stoploss import check_holdings_for_sl, is_on_cooldown, set_cooldown
    near_sl = [{
        "tradingsymbol": "TATAMTRDVR", "instrument_token": 884993,
        "exchange": "NSE", "product": "CNC", "quantity": 52,
        "average_price": 275.06, "last_price": 240.00,
        "pnl": -1823.12, "pnl_pct": -12.74,
        "sl_price": 233.80, "sl_distance_pct": 2.65, "sl_status": "WARNING",
        "value": 12480.00, "weight_pct": 100.0,
    }]
    mock_redis = _make_memory_redis()
    with patch("agent.stoploss._redis", mock_redis), \
         patch("agent.stoploss.get_holdings_with_sl_status", return_value=near_sl):
        alerts = check_holdings_for_sl()
        assert "TATAMTRDVR" in [a.symbol for a in alerts], "TATAMTRDVR must appear in alerts before cooldown"
        set_cooldown("TATAMTRDVR")
        assert is_on_cooldown("TATAMTRDVR") is True


# ── run_sl_monitor tests ──────────────────────────────────────────────────────

def test_run_sl_monitor_returns_dict():
    """run_sl_monitor returns a summary dict with expected keys; checked == 11."""
    from agent.stoploss import run_sl_monitor

    with patch("agent.stoploss.send_sl_breach_alert", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        results = asyncio.run(run_sl_monitor())

    assert isinstance(results, dict)
    assert "checked" in results
    assert "breaches" in results
    assert "alerted" in results
    assert results["checked"] == 11


@pytest.mark.integration
def test_sl_monitor_sends_telegram():
    """run_sl_monitor sends a real Telegram alert when a holding is near SL."""
    from agent.stoploss import run_sl_monitor
    near_sl = [{
        "tradingsymbol": "TATAMTRDVR", "instrument_token": 884993,
        "exchange": "NSE", "product": "CNC", "quantity": 52,
        "average_price": 275.06, "last_price": 240.00,
        "pnl": -1823.12, "pnl_pct": -12.74,
        "sl_price": 233.80, "sl_distance_pct": 2.65, "sl_status": "WARNING",
        "value": 12480.00, "weight_pct": 100.0,
    }]
    redis = RedisClient(REDIS_URL)
    redis.delete("sl:alerted:TATAMTRDVR")

    with patch("agent.stoploss.get_holdings_with_sl_status", return_value=near_sl):
        results = asyncio.run(run_sl_monitor())

    assert results["alerted"] >= 1, (
        f"Expected at least 1 Telegram alert sent, got: {results}"
    )
    redis.delete("sl:alerted:TATAMTRDVR")


# ── Market-hours gate tests ───────────────────────────────────────────────────

def test_market_check_outside_hours():
    """run_with_market_check returns None when called on a Sunday."""
    from agent.stoploss import run_with_market_check
    # 2026-05-03 is a Sunday
    sunday_ist = datetime(2026, 5, 3, 10, 0, 0, tzinfo=IST)

    with patch("agent.stoploss.datetime") as mock_dt:
        mock_dt.now.return_value = sunday_ist
        result = asyncio.run(run_with_market_check())

    assert result is None


# ── Integration: SL breach alert ─────────────────────────────────────────────

@pytest.mark.integration
def test_sl_breach_alert_sent():
    """send_sl_breach_alert dispatches a real Telegram message and returns True."""
    from core.approval import generate_token
    from core.telegram_bot import send_sl_breach_alert

    token = generate_token("STOPLOSS")
    result = asyncio.run(send_sl_breach_alert(
        symbol="TESTSL",
        entry_price=500.0,
        current_price=420.0,
        pnl_pct=-16.0,
        quantity=50,
        token=token,
    ))
    assert result is True
