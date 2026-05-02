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


def init_db() -> None:
    """Create all tables defined on Base. Safe to call on every startup."""
    # Import all models so SQLAlchemy registers them before create_all resolves FKs.
    import models.signal          # noqa: F401
    import models.order           # noqa: F401
    import models.approval        # noqa: F401
    import models.portfolio_snap  # noqa: F401

    Base.metadata.create_all(engine)
    logger.info("Database initialised")
