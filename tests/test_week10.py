"""Week 10 test suite — Trade ledger, paper trade mode, and the exit monitor.

11 tests covering open_trade / close_trade / get_open_trades, paper-aware order
placement, the exit monitor (target / stop-loss / no-trigger), and the real
get_open_positions_summary.

These run against an isolated temp SQLite DB (module fixture) with PAPER_TRADE_MODE
forced True, so they never touch the persistent data_store DB or the real broker.
"""
import asyncio
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

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
    """Wipe trades + action_logs and exit-monitor Redis keys before each test.

    Trade ids restart at 1 after a delete-all, so a leftover ``exit_alert:{id}``
    cooldown from a prior test would otherwise silence the next test's alert.
    """
    from core.db import get_db
    from models.action_log import ActionLog
    from models.trade import Trade

    with get_db() as db:
        db.query(Trade).delete()
        db.query(ActionLog).delete()
        db.commit()

    from agent.exit_monitor import _redis as exit_redis
    if exit_redis.available:
        for pattern in ("exit_alert:*", "exit_meta:*"):
            for key in exit_redis._client.keys(pattern):
                exit_redis._client.delete(key)
    yield


def _signal(symbol="INFY", strategy="SWING_TRADE", qty=10, target=107.0, sl=96.0):
    return {
        "symbol": symbol,
        "strategy_type": strategy,
        "quantity": qty,
        "position_value": round(qty * 100.0, 2),
        "suggested_target": target,
        "suggested_sl": sl,
        "signal_id": None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 1–3 · open_trade
# ═════════════════════════════════════════════════════════════════════════════

def test_open_trade_creates_record():
    from agent.journal import open_trade
    from core.db import get_db
    from models.trade import Trade

    tid = open_trade(_signal(), fill_price=100.0, order_id="PAPER-INFY-1", action_log_id=None)

    with get_db() as db:
        rows = db.query(Trade).filter(Trade.status == "OPEN").all()
        assert len(rows) == 1
        t = rows[0]
        assert t.id == tid
        assert t.symbol == "INFY"
        assert t.entry_price == 100.0
        assert t.quantity == 10
        assert t.target_price == 107.0
        assert t.stop_loss_price == 96.0
        assert t.is_paper is True
        assert t.order_id == "PAPER-INFY-1"


def test_open_trade_links_action_log():
    from agent.journal import open_trade
    from core.db import get_db
    from models.action_log import ActionLog

    with get_db() as db:
        al = ActionLog(
            signal_id=None, symbol="INFY", strategy_type="SWING_TRADE",
            signal_action="BUY", confidence=0.8, entry_price=100.0,
            suggested_qty=10, action_taken="PENDING",
        )
        db.add(al)
        db.commit()
        db.refresh(al)
        al_id = al.id

    tid = open_trade(_signal(), fill_price=100.0, order_id="PAPER-INFY-2", action_log_id=al_id)

    with get_db() as db:
        row = db.query(ActionLog).filter(ActionLog.id == al_id).first()
        assert row.trade_id == tid


def test_open_trade_computes_time_stop():
    from agent.journal import open_trade
    from core.db import get_db
    from models.trade import Trade

    tid = open_trade(_signal(strategy="SWING_TRADE"), fill_price=100.0,
                     order_id="PAPER-INFY-3", action_log_id=None)

    with get_db() as db:
        t = db.query(Trade).filter(Trade.id == tid).first()
        assert t.time_stop_date == date.today() + timedelta(days=10)


# ═════════════════════════════════════════════════════════════════════════════
# 4–6 · close_trade / get_open_trades
# ═════════════════════════════════════════════════════════════════════════════

def test_close_trade_computes_pnl():
    from agent.journal import close_trade, open_trade
    from core.db import get_db
    from models.trade import Trade

    tid = open_trade(_signal(qty=10), fill_price=100.0, order_id="P1", action_log_id=None)
    summary = close_trade(tid, exit_price=110.0, exit_reason="TARGET", exit_order_id="PX1")

    assert summary["pnl"] == 100.0          # 10 * (110 - 100)
    assert summary["pnl_pct"] == 0.10
    assert summary["status"] == "CLOSED"

    with get_db() as db:
        t = db.query(Trade).filter(Trade.id == tid).first()
        assert t.status == "CLOSED"
        assert t.exit_price == 110.0
        assert t.exit_reason == "TARGET"


def test_close_trade_negative_pnl():
    from agent.journal import close_trade, open_trade

    tid = open_trade(_signal(qty=10), fill_price=100.0, order_id="P2", action_log_id=None)
    summary = close_trade(tid, exit_price=95.0, exit_reason="STOPLOSS", exit_order_id="PX2")

    assert summary["pnl"] == -50.0          # 10 * (95 - 100)
    assert summary["pnl_pct"] == -0.05


def test_get_open_trades_excludes_closed():
    from agent.journal import close_trade, get_open_trades, open_trade

    open_trade(_signal(symbol="INFY"), fill_price=100.0, order_id="O1", action_log_id=None)
    open_trade(_signal(symbol="TCS"), fill_price=100.0, order_id="O2", action_log_id=None)
    tid3 = open_trade(_signal(symbol="WIPRO"), fill_price=100.0, order_id="O3", action_log_id=None)
    close_trade(tid3, exit_price=110.0, exit_reason="TARGET", exit_order_id="OX3")

    open_trades = get_open_trades()
    assert len(open_trades) == 2
    assert {t.symbol for t in open_trades} == {"INFY", "TCS"}


# ═════════════════════════════════════════════════════════════════════════════
# 7 · paper-aware order placement
# ═════════════════════════════════════════════════════════════════════════════

def test_paper_order_never_hits_live():
    from core.kite_client import KiteClient

    order = KiteClient().place_order("INFY", "BUY", 10)
    assert order["order_id"].startswith("PAPER-")
    assert order["is_paper"] is True
    assert order["status"] == "COMPLETE"


# ═════════════════════════════════════════════════════════════════════════════
# 8–10 · exit monitor
# ═════════════════════════════════════════════════════════════════════════════

def test_exit_monitor_triggers_on_target():
    from agent.exit_monitor import check_exit_conditions
    from agent.journal import open_trade

    open_trade(_signal(symbol="INFY", target=107.0, sl=96.0), fill_price=100.0,
               order_id="E1", action_log_id=None)

    with patch("agent.exit_monitor._get_current_price", return_value=108.0), \
         patch("agent.exit_monitor._send_exit_alert", new=AsyncMock()):
        result = asyncio.run(check_exit_conditions())

    assert len(result) == 1
    assert result[0]["exit_reason"] == "TARGET"
    assert result[0]["symbol"] == "INFY"


def test_exit_monitor_triggers_on_stoploss():
    from agent.exit_monitor import check_exit_conditions
    from agent.journal import open_trade

    open_trade(_signal(symbol="INFY", target=107.0, sl=96.0), fill_price=100.0,
               order_id="E2", action_log_id=None)

    with patch("agent.exit_monitor._get_current_price", return_value=95.0), \
         patch("agent.exit_monitor._send_exit_alert", new=AsyncMock()):
        result = asyncio.run(check_exit_conditions())

    assert len(result) == 1
    assert result[0]["exit_reason"] == "STOPLOSS"


def test_exit_monitor_no_trigger_in_range():
    from agent.exit_monitor import check_exit_conditions
    from agent.journal import open_trade

    open_trade(_signal(symbol="INFY", target=107.0, sl=96.0), fill_price=100.0,
               order_id="E3", action_log_id=None)

    with patch("agent.exit_monitor._get_current_price", return_value=102.0), \
         patch("agent.exit_monitor._send_exit_alert", new=AsyncMock()):
        result = asyncio.run(check_exit_conditions())

    assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# 11 · real open-positions summary
# ═════════════════════════════════════════════════════════════════════════════

def test_open_positions_summary_real_data():
    from agent.journal import get_open_positions_summary, open_trade

    open_trade(_signal(symbol="INFY"), fill_price=100.0, order_id="S1", action_log_id=None)
    open_trade(_signal(symbol="HDFCBANK"), fill_price=100.0, order_id="S2", action_log_id=None)

    summary = get_open_positions_summary()
    assert summary["open_count"] == 2
    assert summary["by_sector"].get("IT") == 1
    assert summary["by_sector"].get("Financials") == 1
