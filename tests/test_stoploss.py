"""
Week 3 tests — stop-loss monitor (agent/stoploss.py).
All tests use mock data and patch external I/O (Redis, Telegram).
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── 1. get_sl_threshold ───────────────────────────────────────────────────────

def test_get_sl_threshold_default():
    """Symbol with no override returns DEFAULT_SL_PCT (-15.0)."""
    from agent.stoploss import get_sl_threshold
    assert get_sl_threshold("INFY") == -15.0


def test_get_sl_threshold_override():
    """Symbol present in SL_OVERRIDES returns the overridden value."""
    from agent import stoploss
    with patch.dict("config.SL_OVERRIDES", {"RELIANCE": -10.0}):
        # Reload so the patched dict is visible to get_sl_threshold
        import importlib
        importlib.reload(stoploss)
        from agent.stoploss import get_sl_threshold
        assert get_sl_threshold("RELIANCE") == -10.0


# ── 2. check_holdings_for_sl ─────────────────────────────────────────────────

def test_check_holdings_pfc_warning():
    """PFC at ~-14.1% must produce exactly one WARNING alert."""
    from agent.stoploss import check_holdings_for_sl, SLBreachAlert
    alerts = check_holdings_for_sl()

    assert len(alerts) == 1
    alert = alerts[0]
    assert isinstance(alert, SLBreachAlert)
    assert alert.symbol == "PFC"
    assert alert.severity == "WARNING"
    assert -15.0 < alert.pnl_pct < -12.0


def test_check_holdings_sorted_worst_first():
    """Returned alerts are sorted ascending by pnl_pct (worst first)."""
    from agent.stoploss import check_holdings_for_sl
    alerts = check_holdings_for_sl()
    pnl_values = [a.pnl_pct for a in alerts]
    assert pnl_values == sorted(pnl_values)


def test_check_holdings_sl_price_correct():
    """sl_price for PFC must equal avg_price * (1 + threshold/100)."""
    from agent.stoploss import check_holdings_for_sl
    alerts = check_holdings_for_sl()
    pfc = next(a for a in alerts if a.symbol == "PFC")
    expected_sl = round(pfc.entry_price * (1 + pfc.sl_threshold_pct / 100), 2)
    assert pfc.sl_price == expected_sl


def test_check_holdings_no_breach_in_mock():
    """No holding in mock data should be a full BREACH (all safe or WARNING only)."""
    from agent.stoploss import check_holdings_for_sl
    alerts = check_holdings_for_sl()
    breaches = [a for a in alerts if a.severity == "BREACH"]
    assert len(breaches) == 0


# ── 3. is_on_cooldown / set_cooldown ─────────────────────────────────────────

def test_is_on_cooldown_false_when_redis_unavailable():
    """is_on_cooldown returns False when Redis is down (key miss treated as no cooldown)."""
    from agent.stoploss import is_on_cooldown
    with patch("agent.stoploss._redis") as mock_redis:
        mock_redis.get.return_value = None
        assert is_on_cooldown("INFY") is False


def test_is_on_cooldown_true_when_key_exists():
    """is_on_cooldown returns True when Redis returns a value for the cooldown key."""
    from agent.stoploss import is_on_cooldown
    with patch("agent.stoploss._redis") as mock_redis:
        mock_redis.get.return_value = "1"
        assert is_on_cooldown("PFC") is True
        mock_redis.get.assert_called_once_with("sl:alerted:PFC")


def test_set_cooldown_calls_setex():
    """set_cooldown writes the correct key with SL_COOLDOWN_MINS * 60 as TTL."""
    from agent.stoploss import set_cooldown
    from config import SL_COOLDOWN_MINS
    with patch("agent.stoploss._redis") as mock_redis:
        set_cooldown("ICICIBANK")
        mock_redis.setex.assert_called_once_with(
            "sl:alerted:ICICIBANK", SL_COOLDOWN_MINS * 60, "1"
        )


# ── 4. run_sl_monitor ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_sl_monitor_counts():
    """run_sl_monitor returns correct counts for mock data (1 warning, 1 alerted)."""
    from agent.stoploss import run_sl_monitor
    with patch("agent.stoploss.is_on_cooldown", return_value=False), \
         patch("agent.stoploss.set_cooldown"), \
         patch("agent.stoploss.generate_token", return_value="tok-abc"), \
         patch("agent.stoploss.send_sl_breach_alert", new_callable=AsyncMock, return_value=True):
        results = await run_sl_monitor()

    assert results["checked"] == 8
    assert results["warnings"] == 1
    assert results["breaches"] == 0
    assert results["alerted"] == 1
    assert results["cooldown"] == 0


@pytest.mark.asyncio
async def test_run_sl_monitor_skips_cooldown():
    """run_sl_monitor increments cooldown counter and skips Telegram when on cooldown."""
    from agent.stoploss import run_sl_monitor
    with patch("agent.stoploss.is_on_cooldown", return_value=True), \
         patch("agent.stoploss.send_sl_breach_alert", new_callable=AsyncMock) as mock_tg:
        results = await run_sl_monitor()

    assert results["cooldown"] == 1
    assert results["alerted"] == 0
    mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_run_sl_monitor_sends_alert_with_token():
    """run_sl_monitor calls send_sl_breach_alert with the generated token."""
    from agent.stoploss import run_sl_monitor
    with patch("agent.stoploss.is_on_cooldown", return_value=False), \
         patch("agent.stoploss.set_cooldown"), \
         patch("agent.stoploss.generate_token", return_value="test-token-xyz") as mock_gen, \
         patch("agent.stoploss.send_sl_breach_alert", new_callable=AsyncMock, return_value=True) as mock_tg:
        await run_sl_monitor()

    mock_gen.assert_called_once_with("STOPLOSS")
    call_kwargs = mock_tg.call_args.kwargs
    assert call_kwargs["token"] == "test-token-xyz"
    assert call_kwargs["symbol"] == "PFC"


# ── 5. run_with_market_check ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_with_market_check_skips_weekend():
    """run_with_market_check returns None on a Saturday."""
    from agent.stoploss import run_with_market_check
    from datetime import datetime
    from zoneinfo import ZoneInfo

    saturday = datetime(2026, 5, 2, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("agent.stoploss.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        result = await run_with_market_check()

    assert result is None


@pytest.mark.asyncio
async def test_run_with_market_check_skips_outside_hours():
    """run_with_market_check returns None before market open (08:00 IST)."""
    from agent.stoploss import run_with_market_check
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Monday at 08:00 IST — before market open
    pre_open = datetime(2026, 5, 4, 8, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("agent.stoploss.datetime") as mock_dt:
        mock_dt.now.return_value = pre_open
        result = await run_with_market_check()

    assert result is None


@pytest.mark.asyncio
async def test_run_with_market_check_runs_during_hours():
    """run_with_market_check calls run_sl_monitor during market hours."""
    from agent.stoploss import run_with_market_check
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Monday at 11:00 IST — mid-session
    mid_session = datetime(2026, 5, 4, 11, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("agent.stoploss.datetime") as mock_dt, \
         patch("agent.stoploss.run_sl_monitor", new_callable=AsyncMock, return_value={"checked": 8}) as mock_mon:
        mock_dt.now.return_value = mid_session
        result = await run_with_market_check()

    mock_mon.assert_called_once()
    assert result == {"checked": 8}
