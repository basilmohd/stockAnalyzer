"""
Week 1 test suite — KiteClient, portfolio context, technicals, OAuth routes.
All 13 tests must pass with USE_MOCK=true.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── 1. KiteClient mock mode ───────────────────────────────────────────────────

def test_kite_client_mock_mode():
    """KiteClient.mock is True when USE_MOCK=true; is_authenticated returns True."""
    from core.kite_client import KiteClient
    client = KiteClient()
    assert client.mock is True
    assert client.is_authenticated() is True


# ── 2. Holdings fetch ─────────────────────────────────────────────────────────

def test_kite_client_get_holdings():
    """KiteClient.get_holdings returns ≥1 holdings with all required keys."""
    from core.kite_client import KiteClient
    required_keys = {
        "tradingsymbol", "average_price", "last_price",
        "pnl_pct", "quantity", "instrument_token",
    }
    holdings = KiteClient().get_holdings()
    assert len(holdings) >= 1
    for h in holdings:
        assert required_keys.issubset(h.keys()), f"Missing keys in {h['tradingsymbol']}"


# ── 3. PFC near stop-loss ─────────────────────────────────────────────────────

def test_holdings_pfc_near_sl():
    """PFC pnl_pct must be between -20 and -5 (near stop-loss in mock data)."""
    from core.kite_client import KiteClient
    holdings = KiteClient().get_holdings()
    pfc = next(h for h in holdings if h["tradingsymbol"] == "PFC")
    assert -20 <= pfc["pnl_pct"] <= -5, f"PFC pnl_pct={pfc['pnl_pct']} out of expected range"


# ── 4. Quote fetch ────────────────────────────────────────────────────────────

def test_kite_client_get_quote():
    """get_quote returns both requested NSE symbols keyed as 'NSE:SYMBOL'."""
    from core.kite_client import KiteClient
    result = KiteClient().get_quote(["NSE:ICICIBANK", "NSE:INFY"])
    assert "NSE:ICICIBANK" in result
    assert "NSE:INFY" in result


# ── 5. Order placement ────────────────────────────────────────────────────────

def test_kite_client_place_order_mock():
    """Mock place_order(symbol, action, qty) returns order_id containing 'MOCK'."""
    from core.kite_client import KiteClient
    result = KiteClient().place_order("ICICIBANK", "BUY", 10)
    assert "order_id" in result
    assert result["order_id"] is not None
    assert "MOCK" in result["order_id"]


# ── 6. Portfolio summary ──────────────────────────────────────────────────────

def test_portfolio_summary():
    """get_portfolio_summary returns correct totals, count, and sector data."""
    from data.portfolio import get_portfolio_summary
    summary = get_portfolio_summary()
    assert summary["total_value"] > 0
    assert summary["holdings_count"] == 8
    assert "Banking" in summary["sector_weights"]
    assert summary["top_gainer"]["pnl_pct"] > summary["top_loser"]["pnl_pct"]


# ── 7. Claude context builder ─────────────────────────────────────────────────

def test_build_claude_context():
    """build_claude_context returns correct top-level keys and non-empty risk_flags."""
    from data.portfolio import build_claude_context
    result = build_claude_context()
    assert "portfolio" in result
    assert "holdings" in result
    assert "risk_flags" in result
    assert len(result["holdings"]) == 8
    assert all("sl_status" in h for h in result["holdings"])
    assert len(result["risk_flags"]) >= 1  # PFC is near SL in mock data


# ── 8. SL status computation ──────────────────────────────────────────────────

def test_sl_status_computation():
    """PFC must be WARNING or BREACH; HDFCBANK must be SAFE."""
    from data.portfolio import build_claude_context
    result = build_claude_context()
    by_sym = {h["symbol"]: h for h in result["holdings"]}
    assert by_sym["PFC"]["sl_status"] in ("WARNING", "BREACH")
    assert by_sym["HDFCBANK"]["sl_status"] == "SAFE"


# ── 9. OHLC fetch ─────────────────────────────────────────────────────────────

def test_fetch_ohlc_mock():
    """fetch_ohlc returns a DataFrame with ≥50 rows and required columns."""
    import pandas as pd
    from data.technicals import fetch_ohlc
    df = fetch_ohlc("ICICIBANK", 408065)  # 408065 is a valid mock instrument token
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 50
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns, f"Missing column: {col}"


# ── 10. Compute indicators ────────────────────────────────────────────────────

def test_compute_indicators():
    """compute_indicators returns RSI in range, 200SMA bool flag, and volume ratio."""
    from data.technicals import fetch_ohlc, compute_indicators
    df = fetch_ohlc("ICICIBANK", 408065)
    result = compute_indicators(df)
    assert hasattr(result, "rsi")
    assert 0 < result.rsi < 100
    assert isinstance(result.above_200sma, bool)
    assert result.volume_ratio > 0


# ── 11. Technicals for all holdings ──────────────────────────────────────────

def test_get_technicals_for_holdings():
    """get_technicals_for_holdings returns indicators for all 8 holdings."""
    from data.technicals import get_technicals_for_holdings
    result = get_technicals_for_holdings()
    assert len(result) == 8
    assert "ICICIBANK" in result
    assert hasattr(result["ICICIBANK"], "rsi")


# ── 12. Kite login endpoint ───────────────────────────────────────────────────

def test_kite_login_endpoint():
    """GET /kite/login returns 200 with login_url key."""
    from fastapi.testclient import TestClient
    from webhook_server import app
    with TestClient(app) as client:
        response = client.get("/kite/login")
    assert response.status_code == 200
    assert "login_url" in response.json()


# ── 13. Kite status endpoint ──────────────────────────────────────────────────

def test_kite_status_endpoint():
    """GET /kite/status returns 200, authenticated key, and mode == 'mock'."""
    from fastapi.testclient import TestClient
    from webhook_server import app
    with TestClient(app) as client:
        response = client.get("/kite/status")
    assert response.status_code == 200
    data = response.json()
    assert "authenticated" in data
    assert data["mode"] == "mock"
