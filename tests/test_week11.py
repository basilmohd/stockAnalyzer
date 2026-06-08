"""Week 11 test suite — performance analytics engine.

12 tests covering compute_performance_stats (empty, win rate, total pnl, expectancy,
by-strategy, by-exit-reason, best/worst trade), format_weekly_report, and should_go_live.

Runs against an isolated temp SQLite DB (module fixture) with PAPER_TRADE_MODE forced
True, so it never touches the persistent data_store DB. Closed trades are inserted
directly via the make_trade helper.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures — isolated temp DB + paper mode + per-test clean slate
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module", autouse=True)
def temp_db():
    """Point core.db at a throwaway SQLite file and force PAPER_TRADE_MODE on."""
    import config
    import core.db as db_mod
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"

    old_engine, old_session = db_mod.engine, db_mod.SessionLocal
    db_mod.engine = create_engine(url, connect_args={"check_same_thread": False})
    db_mod.SessionLocal = sessionmaker(
        bind=db_mod.engine, autocommit=False, autoflush=False
    )
    db_mod.init_db()  # creates all tables (incl. trades) on the temp engine

    old_paper = config.PAPER_TRADE_MODE
    config.PAPER_TRADE_MODE = True

    yield

    config.PAPER_TRADE_MODE = old_paper
    db_mod.engine.dispose()
    db_mod.engine, db_mod.SessionLocal = old_engine, old_session
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def clean_tables():
    """Wipe trades before each test for a clean slate."""
    from core.db import get_db
    from models.trade import Trade

    with get_db() as db:
        db.query(Trade).delete()
        db.commit()
    yield


# ═════════════════════════════════════════════════════════════════════════════
# Helper — insert a closed Trade with computed pnl
# ═════════════════════════════════════════════════════════════════════════════

def make_trade(symbol, strategy, entry, exit_p, qty, exit_reason, days_ago=10):
    """Insert a CLOSED Trade record with computed pnl / pnl_pct. Returns its id.

    entry_date = days_ago in the past; exit_date = 5 days after entry. pnl_pct is a
    FRACTION (matching Trade as stored): (exit - entry) / entry.
    """
    from core.db import get_db
    from models.trade import Trade

    entry_date = datetime.now() - timedelta(days=days_ago)
    exit_date = datetime.now() - timedelta(days=max(0, days_ago - 5))
    pnl = (exit_p - entry) * qty
    pnl_pct = (exit_p - entry) / entry

    with get_db() as db:
        t = Trade(
            symbol=symbol,
            strategy_type=strategy,
            entry_date=entry_date,
            entry_price=entry,
            quantity=qty,
            position_value=round(entry * qty, 2),
            target_price=round(entry * 1.1, 2),
            stop_loss_price=round(entry * 0.9, 2),
            time_stop_date=(entry_date + timedelta(days=10)).date(),
            status="CLOSED",
            exit_date=exit_date,
            exit_price=exit_p,
            exit_reason=exit_reason,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            is_paper=True,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        return t.id


def _full_stats(**overrides):
    """A fully populated stats dict for format / go-live tests (overridable)."""
    stats = {
        "generated_at": datetime.now().isoformat(),
        "period": "all_time",
        "is_paper": True,
        "summary": {
            "total_trades": 24,
            "winning_trades": 14,
            "losing_trades": 10,
            "win_rate": 0.58,
            "avg_win_pct": 0.065,
            "avg_loss_pct": -0.032,
            "expectancy": 0.024,
            "total_pnl": 8450.0,
            "avg_hold_days": 7.2,
            "best_trade": {"symbol": "INFY", "pnl": 1500.0, "pnl_pct": 0.15,
                           "strategy": "SWING_TRADE", "exit_reason": "TARGET"},
            "worst_trade": {"symbol": "TCS", "pnl": -800.0, "pnl_pct": -0.08,
                            "strategy": "MEAN_REVERSION", "exit_reason": "STOPLOSS"},
        },
        "by_strategy": {
            "SWING_TRADE": {"trades": 12, "win_rate": 0.66, "total_pnl": 6200.0,
                            "avg_pnl_pct": 0.041, "avg_hold_days": 6.5},
            "MEAN_REVERSION": {"trades": 8, "win_rate": 0.50, "total_pnl": 1500.0,
                               "avg_pnl_pct": 0.018, "avg_hold_days": 9.1},
            "TREND_FOLLOW": {"trades": 4, "win_rate": 0.50, "total_pnl": 750.0,
                             "avg_pnl_pct": 0.022, "avg_hold_days": 12.0},
        },
        "by_exit_reason": {
            "TARGET": {"count": 12, "total_pnl": 9800.0},
            "STOPLOSS": {"count": 8, "total_pnl": -2100.0},
            "TIME_STOP": {"count": 4, "total_pnl": 750.0},
            "MANUAL": {"count": 0, "total_pnl": 0.0},
        },
        "weekly_pnl": [
            {"week": "2025-W22", "pnl": 1240.0, "trades": 3},
            {"week": "2025-W21", "pnl": 880.0, "trades": 2},
            {"week": "2025-W20", "pnl": -320.0, "trades": 2},
            {"week": "2025-W19", "pnl": 1500.0, "trades": 4},
            {"week": "2025-W18", "pnl": 600.0, "trades": 2},
            {"week": "2025-W17", "pnl": 410.0, "trades": 1},
        ],
        "open_positions": {
            "count": 2,
            "unrealized_pnl": 320.0,
            "positions": [
                {"symbol": "HDFCBANK", "entry": 1500.0, "current": 1540.0,
                 "quantity": 5, "unrealized": 200.0, "unrealized_pct": 0.0267},
                {"symbol": "WIPRO", "entry": 400.0, "current": 412.0,
                 "quantity": 10, "unrealized": 120.0, "unrealized_pct": 0.03},
            ],
        },
        "capital": {
            "starting": 25000.0,
            "current_value": 33770.0,
            "total_return_pct": 0.3508,
        },
    }
    stats["summary"].update(overrides.get("summary", {}))
    if "weekly_pnl" in overrides:
        stats["weekly_pnl"] = overrides["weekly_pnl"]
    return stats


# ═════════════════════════════════════════════════════════════════════════════
# 1–8 · compute_performance_stats
# ═════════════════════════════════════════════════════════════════════════════

def test_compute_stats_empty_returns_zeros():
    from agent.analytics import compute_performance_stats

    stats = compute_performance_stats()
    assert stats["summary"]["total_trades"] == 0
    assert stats["summary"]["total_pnl"] == 0.0


def test_compute_stats_win_rate():
    from agent.analytics import compute_performance_stats

    for i in range(4):  # winners
        make_trade(f"W{i}", "SWING_TRADE", 100, 110, 10, "TARGET")
    for i in range(2):  # losers
        make_trade(f"L{i}", "SWING_TRADE", 100, 90, 10, "STOPLOSS")

    stats = compute_performance_stats()
    assert stats["summary"]["win_rate"] == pytest.approx(4 / 6, 0.01)


def test_compute_stats_total_pnl():
    from agent.analytics import compute_performance_stats

    make_trade("A", "SWING_TRADE", 100, 150, 10, "TARGET")   # +500
    make_trade("B", "SWING_TRADE", 100, 80, 10, "STOPLOSS")  # -200
    make_trade("C", "SWING_TRADE", 100, 180, 10, "TARGET")   # +800

    stats = compute_performance_stats()
    assert stats["summary"]["total_pnl"] == 1100.0


def test_compute_stats_expectancy_positive():
    from agent.analytics import compute_performance_stats

    for i in range(6):  # winners avg +6%
        make_trade(f"W{i}", "SWING_TRADE", 100, 106, 10, "TARGET")
    for i in range(4):  # losers avg -3%
        make_trade(f"L{i}", "SWING_TRADE", 100, 97, 10, "STOPLOSS")

    stats = compute_performance_stats()
    # (0.6 * 0.06) + (0.4 * -0.03) = 0.024
    assert stats["summary"]["expectancy"] == pytest.approx(0.024, 0.005)


def test_compute_stats_by_strategy():
    from agent.analytics import compute_performance_stats

    for i in range(3):
        make_trade(f"S{i}", "SWING_TRADE", 100, 110, 10, "TARGET")
    for i in range(2):
        make_trade(f"M{i}", "MEAN_REVERSION", 100, 105, 10, "TARGET")

    stats = compute_performance_stats()
    assert "SWING_TRADE" in stats["by_strategy"]
    assert stats["by_strategy"]["SWING_TRADE"]["trades"] == 3
    assert stats["by_strategy"]["MEAN_REVERSION"]["trades"] == 2


def test_compute_stats_by_exit_reason():
    from agent.analytics import compute_performance_stats

    for i in range(4):
        make_trade(f"T{i}", "SWING_TRADE", 100, 110, 10, "TARGET")
    for i in range(2):
        make_trade(f"S{i}", "SWING_TRADE", 100, 90, 10, "STOPLOSS")

    stats = compute_performance_stats()
    assert stats["by_exit_reason"]["TARGET"]["count"] == 4
    assert stats["by_exit_reason"]["STOPLOSS"]["count"] == 2


def test_compute_stats_best_trade():
    from agent.analytics import compute_performance_stats

    make_trade("A", "SWING_TRADE", 100, 120, 10, "TARGET")   # +200
    make_trade("B", "SWING_TRADE", 100, 250, 10, "TARGET")   # +1500
    make_trade("C", "SWING_TRADE", 100, 130, 10, "TARGET")   # +300

    stats = compute_performance_stats()
    assert stats["summary"]["best_trade"]["pnl"] == 1500.0


def test_compute_stats_worst_trade():
    from agent.analytics import compute_performance_stats

    make_trade("A", "SWING_TRADE", 100, 90, 10, "STOPLOSS")  # -100
    make_trade("B", "SWING_TRADE", 100, 20, 10, "STOPLOSS")  # -800
    make_trade("C", "SWING_TRADE", 100, 70, 10, "STOPLOSS")  # -300

    stats = compute_performance_stats()
    assert stats["summary"]["worst_trade"]["pnl"] == -800.0


# ═════════════════════════════════════════════════════════════════════════════
# 9–10 · format_weekly_report
# ═════════════════════════════════════════════════════════════════════════════

def test_format_weekly_report_returns_string():
    from agent.analytics import format_weekly_report

    result = format_weekly_report(_full_stats())
    assert isinstance(result, str)
    assert len(result) > 100


def test_format_weekly_report_contains_expectancy():
    from agent.analytics import format_weekly_report

    result = format_weekly_report(_full_stats())
    assert "Expectancy" in result or "expectancy" in result.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 11–12 · should_go_live
# ═════════════════════════════════════════════════════════════════════════════

def test_should_go_live_all_conditions_met(monkeypatch):
    from agent import analytics

    stats = _full_stats(
        summary={"total_trades": 25, "win_rate": 0.60, "expectancy": 0.025},
        weekly_pnl=[
            {"week": f"2025-W{w}", "pnl": 500.0, "trades": 4} for w in range(17, 23)
        ],
    )
    monkeypatch.setattr(analytics, "compute_performance_stats", lambda *a, **k: stats)

    result = analytics.should_go_live()
    assert result["ready"] is True
    assert result["missing"] == []


def test_should_go_live_fails_insufficient_trades(monkeypatch):
    from agent import analytics

    stats = _full_stats(
        summary={"total_trades": 8, "win_rate": 0.60, "expectancy": 0.020},
        weekly_pnl=[
            {"week": f"2025-W{w}", "pnl": 300.0, "trades": 2} for w in range(17, 23)
        ],
    )
    monkeypatch.setattr(analytics, "compute_performance_stats", lambda *a, **k: stats)

    result = analytics.should_go_live()
    assert result["ready"] is False
    assert "enough_trades" in result["missing"]
