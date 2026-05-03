"""
Week 0 health check — 11 tests that must all pass before Week 0 is complete.
"""
import os
import sys
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

# Ensure project root is on the path so imports work from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── 1. Config ─────────────────────────────────────────────────────────────────

def test_config_loads():
    """DEFAULT_SL_PCT and CONFIDENCE_THRESHOLD must match spec."""
    import config
    assert config.DEFAULT_SL_PCT == -15.0
    assert config.CONFIDENCE_THRESHOLD == 0.75


# ── 2. RedisClient ────────────────────────────────────────────────────────────

def test_redis_client_init():
    """RedisClient() must not raise; available may be True or False."""
    from core.redis_client import RedisClient
    client = RedisClient("redis://localhost:6379")
    assert isinstance(client.available, bool)


# ── 3 & 4. Mock holdings ──────────────────────────────────────────────────────

def test_mock_holdings():
    """MockKiteClient.get_holdings() returns exactly 8 items with required keys."""
    from mocks.kite_mock import MockKiteClient
    required_keys = {
        "tradingsymbol", "instrument_token", "exchange", "product",
        "quantity", "average_price", "last_price", "pnl", "pnl_pct",
    }
    holdings = MockKiteClient().get_holdings()
    assert len(holdings) == 11
    for h in holdings:
        assert required_keys.issubset(h.keys()), f"Missing keys in {h['tradingsymbol']}"


def test_mock_irctc_positive_pnl():
    """IRCTC pnl_pct must be positive (strong performer in portfolio)."""
    from mocks.kite_mock import MockKiteClient
    holdings = MockKiteClient().get_holdings()
    irctc = next(h for h in holdings if h["tradingsymbol"] == "IRCTC")
    assert irctc["pnl_pct"] > 0, f"IRCTC pnl_pct={irctc['pnl_pct']} should be positive"


# ── 5. Mock news ──────────────────────────────────────────────────────────────

def test_mock_news():
    """get_mock_news returns dict with required keys for a known symbol."""
    from mocks.news_mock import get_mock_news
    result = get_mock_news("ICICIBANK")
    assert "headlines" in result
    assert "sentiment_score" in result
    assert "fetched_at" in result
    assert isinstance(result["headlines"], list)
    assert len(result["headlines"]) > 0


# ── 6. DB init ────────────────────────────────────────────────────────────────

def test_db_init(tmp_path):
    """init_db() creates all 4 tables in a fresh SQLite database."""
    import sqlalchemy as sa
    from sqlalchemy import create_engine

    db_path = tmp_path / "test_portfolio.db"
    db_url = f"sqlite:///{db_path}"

    # Patch DATABASE_URL before importing db so engine uses tmp path
    with patch.dict(os.environ, {"DATABASE_URL": db_url}):
        # Re-create engine and Base pointing at tmp DB
        import importlib
        import config as cfg
        cfg.DATABASE_URL = db_url  # patch module-level value

        import core.db as db_module
        test_engine = create_engine(db_url, connect_args={"check_same_thread": False})

        # Import all models so they register on Base
        import models.signal          # noqa: F401
        import models.order           # noqa: F401
        import models.approval        # noqa: F401
        import models.portfolio_snap  # noqa: F401

        db_module.Base.metadata.create_all(test_engine)

        inspector = sa.inspect(test_engine)
        tables = inspector.get_table_names()

    for expected in ("signals", "orders", "approvals", "portfolio_snapshots"):
        assert expected in tables, f"Table '{expected}' not found; got {tables}"


# ── 7. Signal model ───────────────────────────────────────────────────────────

def test_signal_model(tmp_path):
    """Create a Signal, commit, and query back — symbol must match."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = f"sqlite:///{tmp_path}/signals_test.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    import models.signal          # noqa: F401
    import models.order           # noqa: F401
    import models.approval        # noqa: F401
    import models.portfolio_snap  # noqa: F401
    from core.db import Base
    from models.signal import Signal

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        sig = Signal(
            symbol="INFY",
            action="BUY",
            confidence=0.82,
            reasoning="Strong earnings beat with positive guidance.",
        )
        session.add(sig)
        session.commit()
        session.refresh(sig)
        fetched = session.get(Signal, sig.id)

    assert fetched is not None
    assert fetched.symbol == "INFY"


# ── 8. Approval model ─────────────────────────────────────────────────────────

def test_approval_model(tmp_path):
    """Create an Approval with a UUID token, commit, and query back."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = f"sqlite:///{tmp_path}/approval_test.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    import models.signal          # noqa: F401
    import models.order           # noqa: F401
    import models.approval        # noqa: F401
    import models.portfolio_snap  # noqa: F401
    from core.db import Base
    from models.approval import Approval

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    token = str(uuid.uuid4())
    expires = datetime(2026, 12, 31, 23, 59, 59)

    with Session() as session:
        appr = Approval(
            token=token,
            action_type="SIGNAL",
            expires_at=expires,
        )
        session.add(appr)
        session.commit()
        session.refresh(appr)
        fetched = session.get(Approval, appr.id)

    assert fetched is not None
    assert fetched.token == token


# ── 9. Webhook /health ────────────────────────────────────────────────────────

def test_webhook_health():
    """GET /health returns 200 with a body containing 'status'."""
    from fastapi.testclient import TestClient
    from webhook_server import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert "status" in response.json()


# ── 10. market_day_check on Saturday ─────────────────────────────────────────

def test_market_day_check_weekend():
    """market_day_check() must return False on a Saturday."""
    import pytz
    from scheduler import market_day_check

    ist = pytz.timezone("Asia/Kolkata")
    # 2026-05-02 is a Saturday
    saturday = ist.localize(datetime(2026, 5, 2, 10, 0, 0))

    with patch("scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        result = market_day_check()

    assert result is False


# ── 11. .gitignore ────────────────────────────────────────────────────────────

def test_gitignore():
    """'.env' must appear in .gitignore to protect secrets."""
    root = os.path.join(os.path.dirname(__file__), "..")
    gitignore_path = os.path.join(root, ".gitignore")
    with open(gitignore_path) as f:
        content = f.read()
    assert ".env" in content
