"""
Unit tests for agent/closure.py module.

Tests daily P&L calculation, gainers/losers extraction, message formatting,
and closure report workflow with mocked Kite/Redis data.
"""

import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from agent.closure import (
    HoldingWithDailyPnL,
    calculate_daily_pnl,
    get_top_gainers_losers,
    format_closure_message,
    send_closure_report,
)


# ============================================================================
# FIXTURES — Mock data
# ============================================================================

@pytest.fixture
def mock_holdings():
    """Mock holdings list from get_holdings()."""
    return [
        {
            "tradingsymbol": "RELIANCE",
            "quantity": 10,
            "last_price": 1500.00,
            "average_price": 1000.00,
        },
        {
            "tradingsymbol": "TCS",
            "quantity": 5,
            "last_price": 4000.00,
            "average_price": 3500.00,
        },
        {
            "tradingsymbol": "INFY",
            "quantity": 20,
            "last_price": 1600.00,
            "average_price": 1800.00,
        },
        {
            "tradingsymbol": "HDFCBANK",
            "quantity": 8,
            "last_price": 1800.00,
            "average_price": 1750.00,
        },
        {
            "tradingsymbol": "ICICIBANK",
            "quantity": 12,
            "last_price": 900.00,
            "average_price": 1000.00,
        },
    ]


@pytest.fixture
def mock_prev_close_prices():
    """Mock previous close prices."""
    return {
        "RELIANCE": 1400.00,      # Current 1500 → +7.14%
        "TCS": 4100.00,            # Current 4000 → -2.44%
        "INFY": 1500.00,           # Current 1600 → +6.67%
        "HDFCBANK": 1800.00,       # Current 1800 → 0.00%
        "ICICIBANK": 950.00,       # Current 900 → -5.26%
    }


@pytest.fixture
def mock_portfolio_summary():
    """Mock portfolio summary from get_portfolio_summary()."""
    return {
        "total_value": 100000.00,
        "total_pnl": 15000.00,
        "total_pnl_pct": 15.0,
        "holdings_count": 5,
        "breach_count": 0,
    }


# ============================================================================
# TEST: HoldingWithDailyPnL Data Class
# ============================================================================

class TestHoldingWithDailyPnL:
    """Tests for HoldingWithDailyPnL data class."""

    def test_init_positive_daily_pnl(self):
        """Test initialization with positive daily P&L."""
        h = HoldingWithDailyPnL(
            symbol="RELIANCE",
            quantity=10,
            current_price=1500.00,
            prev_close_price=1400.00,
        )
        
        assert h.symbol == "RELIANCE"
        assert h.quantity == 10
        assert h.current_price == 1500.00
        assert h.prev_close_price == 1400.00
        assert pytest.approx(h.daily_pnl_pct, 0.01) == 7.14  # (1500-1400)/1400*100
        assert h.current_value == 15000.00  # 1500 * 10
        assert h.prev_close_value == 14000.00  # 1400 * 10

    def test_init_negative_daily_pnl(self):
        """Test initialization with negative daily P&L."""
        h = HoldingWithDailyPnL(
            symbol="INFY",
            quantity=20,
            current_price=1600.00,
            prev_close_price=1700.00,
        )
        
        assert pytest.approx(h.daily_pnl_pct, 0.01) == -5.88  # (1600-1700)/1700*100
        assert h.current_value == 32000.00
        assert h.prev_close_value == 34000.00

    def test_init_zero_prev_close(self):
        """Test initialization with zero previous close price (edge case)."""
        h = HoldingWithDailyPnL(
            symbol="TEST",
            quantity=1,
            current_price=100.00,
            prev_close_price=0.0,  # Fallback case
        )
        
        assert h.daily_pnl_pct == 0.0  # Should not throw error


# ============================================================================
# TEST: calculate_daily_pnl()
# ============================================================================

@pytest.mark.asyncio
async def test_calculate_daily_pnl_happy_path(mock_holdings, mock_prev_close_prices):
    """Test daily P&L calculation with valid holdings and previous closes."""
    
    with patch("agent.closure.get_daily_open_prices", return_value=mock_prev_close_prices):
        holdings_with_pnl, portfolio_daily_pnl_pct = await calculate_daily_pnl(
            mock_holdings, prev_close_prices=mock_prev_close_prices
        )
    
    # Verify correct number of holdings processed
    assert len(holdings_with_pnl) == 5
    
    # Verify specific holdings
    rel = next(h for h in holdings_with_pnl if h.symbol == "RELIANCE")
    assert pytest.approx(rel.daily_pnl_pct, 0.01) == 7.14
    
    infy = next(h for h in holdings_with_pnl if h.symbol == "INFY")
    assert pytest.approx(infy.daily_pnl_pct, 0.01) == 6.67
    
    # Portfolio daily P&L calculation
    # Total current value: 1500*10 + 4000*5 + 1600*20 + 1800*8 + 900*12 = 92200
    # Total prev close: 1400*10 + 4100*5 + 1500*20 + 1800*8 + 950*12 = 90300
    # Daily P&L % = (92200 - 90300) / 90300 * 100 = 2.104%
    assert pytest.approx(portfolio_daily_pnl_pct, abs=0.1) == 2.104


@pytest.mark.asyncio
async def test_calculate_daily_pnl_fallback_no_redis(mock_holdings):
    """Test daily P&L calculation with fallback when prev close unavailable."""
    
    with patch("agent.closure.get_daily_open_prices", return_value={}):
        with patch("agent.closure.get_fallback_prices") as mock_fallback:
            # Fallback returns entry prices
            mock_fallback.return_value = {
                h["tradingsymbol"]: h["average_price"] for h in mock_holdings
            }
            
            holdings_with_pnl, portfolio_daily_pnl_pct = await calculate_daily_pnl(
                mock_holdings
            )
    
    assert len(holdings_with_pnl) == 5
    
    # With fallback (entry prices):
    # RELIANCE: current 1500 vs avg 1000 → +50%
    rel = next(h for h in holdings_with_pnl if h.symbol == "RELIANCE")
    assert pytest.approx(rel.daily_pnl_pct, 0.1) == 50.0


@pytest.mark.asyncio
async def test_calculate_daily_pnl_no_holdings():
    """Test daily P&L calculation with empty holdings."""
    
    holdings_with_pnl, portfolio_daily_pnl_pct = await calculate_daily_pnl([])
    
    assert holdings_with_pnl == []
    assert portfolio_daily_pnl_pct == 0.0


# ============================================================================
# TEST: get_top_gainers_losers()
# ============================================================================

def test_get_top_gainers_losers_happy_path(mock_holdings, mock_prev_close_prices):
    """Test extraction of top gainers and losers."""
    
    # Create holdings with P&L
    holdings_with_pnl = []
    for holding in mock_holdings:
        prev_close = mock_prev_close_prices[holding["tradingsymbol"]]
        h = HoldingWithDailyPnL(
            symbol=holding["tradingsymbol"],
            quantity=holding["quantity"],
            current_price=holding["last_price"],
            prev_close_price=prev_close,
        )
        holdings_with_pnl.append(h)
    
    gainers, losers = get_top_gainers_losers(holdings_with_pnl, top_n=3)
    
    # Calculations:
    # RELIANCE: (1500-1400)/1400 = +7.14% ✓ gainer
    # INFY: (1600-1500)/1500 = +6.67% ✓ gainer
    # HDFCBANK: (1800-1800)/1800 = 0% ✗ excluded (not a gain)
    # TCS: (4000-4100)/4100 = -2.44% ✓ loser
    # ICICIBANK: (900-950)/950 = -5.26% ✓ loser
    
    # Top gainers: only stocks with daily_pnl_pct > 0
    assert len(gainers) == 2
    assert gainers[0].symbol == "RELIANCE"  # +7.14% (highest)
    assert gainers[1].symbol == "INFY"      # +6.67%
    
    # Top losers: only stocks with daily_pnl_pct < 0, sorted by loss magnitude
    assert len(losers) == 2
    assert losers[0].symbol == "ICICIBANK"  # -5.26% (biggest loss)
    assert losers[1].symbol == "TCS"        # -2.44%


def test_get_top_gainers_losers_fewer_than_n(mock_holdings, mock_prev_close_prices):
    """Test extraction when fewer holdings than top_n."""
    
    # Only 2 holdings: RELIANCE (+7.14% gainer) and TCS (-2.44% loser)
    two_holdings = mock_holdings[:2]
    holdings_with_pnl = [
        HoldingWithDailyPnL(
            symbol=h["tradingsymbol"],
            quantity=h["quantity"],
            current_price=h["last_price"],
            prev_close_price=mock_prev_close_prices[h["tradingsymbol"]],
        )
        for h in two_holdings
    ]
    
    gainers, losers = get_top_gainers_losers(holdings_with_pnl, top_n=3)
    
    # Only 1 gainer (RELIANCE) and 1 loser (TCS) available
    assert len(gainers) == 1
    assert gainers[0].symbol == "RELIANCE"
    assert len(losers) == 1
    assert losers[0].symbol == "TCS"


def test_get_top_gainers_losers_empty_list():
    """Test extraction with empty holdings list."""
    
    gainers, losers = get_top_gainers_losers([], top_n=3)
    
    assert gainers == []
    assert losers == []


# ============================================================================
# TEST: format_closure_message()
# ============================================================================

def test_format_closure_message_happy_path(mock_holdings, mock_prev_close_prices):
    """Test message formatting with valid data."""
    
    # Create holdings with P&L
    holdings_with_pnl = [
        HoldingWithDailyPnL(
            symbol=h["tradingsymbol"],
            quantity=h["quantity"],
            current_price=h["last_price"],
            prev_close_price=mock_prev_close_prices[h["tradingsymbol"]],
        )
        for h in mock_holdings
    ]
    
    gainers, losers = get_top_gainers_losers(holdings_with_pnl, top_n=3)
    
    message = format_closure_message(
        total_portfolio_value=100000.00,
        portfolio_daily_pnl_pct=1.81,
        gainers=gainers,
        losers=losers,
    )
    
    # Verify message content
    assert "MARKET CLOSURE" in message
    assert "📊" in message
    assert "100000" in message or "100,000" in message
    assert "+1.81%" in message
    assert "🔝 Top Gainers" in message
    assert "🔻 Top Losers" in message
    assert "RELIANCE" in message
    assert "ICICIBANK" in message
    assert "HTML" not in message  # No literal "<HTML>" tag, but HTML tags present


def test_format_closure_message_negative_pnl():
    """Test message formatting with negative portfolio P&L."""
    
    message = format_closure_message(
        total_portfolio_value=50000.00,
        portfolio_daily_pnl_pct=-2.50,
        gainers=[],
        losers=[],
    )
    
    assert "📉" in message  # Downward emoji
    assert "-2.50%" in message


def test_format_closure_message_zero_pnl():
    """Test message formatting with zero portfolio P&L."""
    
    message = format_closure_message(
        total_portfolio_value=75000.00,
        portfolio_daily_pnl_pct=0.0,
        gainers=[],
        losers=[],
    )
    
    assert "+0.00%" in message


# ============================================================================
# TEST: send_closure_report() — Integration
# ============================================================================

@pytest.mark.asyncio
async def test_send_closure_report_happy_path(
    mock_holdings, mock_prev_close_prices, mock_portfolio_summary
):
    """Test full closure report workflow with all mocked dependencies."""
    
    mock_kite_client = MagicMock()
    mock_kite_client.get_holdings.return_value = mock_holdings
    
    with patch("agent.closure.KiteClient", return_value=mock_kite_client):
        with patch("agent.closure.get_daily_open_prices", return_value=mock_prev_close_prices):
            with patch("agent.closure.get_portfolio_summary", return_value=mock_portfolio_summary):
                with patch("agent.closure.send_alert", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = True
                    
                    result = await send_closure_report()
    
    assert result is True
    mock_send.assert_called_once()
    
    # Verify message was formatted and sent
    call_args = mock_send.call_args
    assert call_args.kwargs["title"] == "Market Closure Report"
    assert "MARKET CLOSURE" in call_args.kwargs["body"]


@pytest.mark.asyncio
async def test_send_closure_report_no_holdings():
    """Test closure report when no holdings present."""
    
    mock_kite_client = MagicMock()
    mock_kite_client.get_holdings.return_value = []
    
    with patch("agent.closure.KiteClient", return_value=mock_kite_client):
        result = await send_closure_report()
    
    assert result is False


@pytest.mark.asyncio
async def test_send_closure_report_telegram_send_failure(
    mock_holdings, mock_prev_close_prices, mock_portfolio_summary
):
    """Test closure report when Telegram send fails."""
    
    mock_kite_client = MagicMock()
    mock_kite_client.get_holdings.return_value = mock_holdings
    
    with patch("agent.closure.KiteClient", return_value=mock_kite_client):
        with patch("agent.closure.get_daily_open_prices", return_value=mock_prev_close_prices):
            with patch("agent.closure.get_portfolio_summary", return_value=mock_portfolio_summary):
                with patch("agent.closure.send_alert", new_callable=AsyncMock) as mock_send:
                    mock_send.return_value = False  # Send failure
                    
                    result = await send_closure_report()
    
    assert result is False


@pytest.mark.asyncio
async def test_send_closure_report_exception_handling():
    """Test closure report exception handling."""
    
    mock_kite_client = MagicMock()
    mock_kite_client.get_holdings.side_effect = Exception("API Error")
    
    with patch("agent.closure.KiteClient", return_value=mock_kite_client):
        result = await send_closure_report()
    
    assert result is False


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
