"""
SQLAlchemy engine, session factory, declarative base, and helpers.
"""
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a database session and guarantee it is closed afterwards."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_column_if_missing(table: str, column: str, col_def: str) -> None:
    """Add a column to a SQLite table if it doesn't already exist."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing = [c["name"] for c in inspector.get_columns(table)]
    if column not in existing:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
            conn.commit()
        logger.info("Migrated: added %s.%s", table, column)


def init_db() -> None:
    """Create all tables defined on Base. Safe to call on every startup."""
    # Import all models so SQLAlchemy registers them before create_all resolves FKs.
    import models.signal          # noqa: F401
    import models.order           # noqa: F401
    import models.approval        # noqa: F401
    import models.portfolio_snap  # noqa: F401
    import models.action_log      # noqa: F401
    import models.trade           # noqa: F401

    Base.metadata.create_all(engine)
    _add_column_if_missing("portfolio_snapshots", "health_score_json", "health_score_json TEXT")
    _add_column_if_missing("action_logs", "trade_id", "trade_id INTEGER")  # Wk10: link to Trade ledger
    logger.info("Database initialised")
